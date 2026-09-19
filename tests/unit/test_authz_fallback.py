"""T41 fallback — API GW JWT authorizers can drop colon-carrying claims
(cognito:groups, cognito:username) before they reach the function. Live
verified during the first cloud smoke: role collapsed to READ_ONLY and every
write 403'd despite a valid pp-admins token. claims_from_event must re-derive
identity from the Bearer token (full RS256 verify, cached JWKS) when the
authorizer context is group-less — and fall back SECURELY (readonly) when the
header is absent or malformed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import random

import pytest

from services.api import authz


@pytest.fixture()
def signed_token(monkeypatch):
    """Real RS256-signed token (stdlib RSA keygen, monkeypatched JWKS)."""
    monkeypatch.setenv("PROCESSPATCH_AUTH", "cognito")
    monkeypatch.setenv("PP_USER_POOL_ID", "ap-south-1_TEST")
    monkeypatch.setenv("PP_CLIENT_ID", "pp-test-client")

    random.seed(7)

    def gen_prime(bits: int) -> int:
        while True:
            p = random.getrandbits(bits) | (1 << (bits - 1)) | 1
            if pow(2, p - 1, p) == 1:
                return p

    p, q = gen_prime(512), gen_prime(512)
    n, e = p * q, 65537
    d = pow(e, -1, (p - 1) * (q - 1))

    def i2b(i: int) -> str:
        return base64.urlsafe_b64encode(i.to_bytes((i.bit_length() + 7) // 8, "big")).decode().rstrip("=")

    kid = "test-key"
    authz._CACHE["jwks"] = {"keys": [{"kid": kid, "kty": "RSA", "n": i2b(n), "e": i2b(e)}]}
    authz._CACHE["fetched"] = authz.time.time() + 9999

    claims = {
        "sub": "11b39d0a",
        "email": "demo-admin@processpatch.demo",
        "aud": "pp-test-client",
        "iss": "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_TEST",
        "cognito:groups": ["pp-admins"],
        "token_use": "id",
        "exp": authz.time.time() + 3600,
    }
    h = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "kid": kid}).encode()).decode().rstrip("=")
    pl = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420")
    H = hashlib.sha256(f"{h}.{pl}".encode()).digest()
    k = (n.bit_length() + 7) // 8
    em = b"\x00\x01" + b"\xff" * (k - len(digest_info) - len(H) - 3) + b"\x00" + digest_info + H
    sig = pow(int.from_bytes(em, "big"), d, n)
    return f"{h}.{pl}.{i2b(sig)}"


def _gw_event(token: str | None, with_groups: bool = False) -> dict:
    """HTTP API event as API GW passes it: authorizer claims, bearer header."""
    claims = {
        "sub": "11b39d0a",
        "email": "demo-admin@processpatch.demo",
        "aud": "pp-test-client",
        "iss": "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_TEST",
        "token_use": "id",
    }
    if with_groups:  # the happy case — groups survive the hop
        claims["cognito:groups"] = ["pp-admins"]
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return {
        "requestContext": {"http": {"method": "POST"}, "authorizer": {"jwt": {"claims": claims, "scopes": []}}},
        "headers": headers,
    }


def test_groups_present_uses_authorizer_claims(signed_token):
    ident = authz.claims_from_event(_gw_event(signed_token, with_groups=True))
    assert ident["role"] == "admin" and ident["via"] == "cognito-authorizer"


def test_groupless_claims_fall_back_to_token(signed_token):
    """The live bug: GW strips cognito:groups — token is ground truth."""
    ident = authz.claims_from_event(_gw_event(signed_token, with_groups=False))
    assert ident["role"] == "admin" and ident["via"] == "cognito"
    # and the write the live stack 403'd is authorized
    authz.authorize("POST", "/builds", ident, {"domain": "research_grant", "defer": True})


def test_stringified_groups_recognized(signed_token):
    """Authorizer contexts that stringify claims: 'pp-admins' must be one
    group, NOT a set of 9 characters (set('pp-admins') is non-empty so the
    group-less fallback never fires, but membership fails -> READ_ONLY)."""
    tok = signed_token
    event = _gw_event(tok, with_groups=False)
    event["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:groups"] = "pp-admins"
    ident = authz.claims_from_event(event)
    assert ident["role"] == "admin"
    assert ident["groups"] == ["pp-admins"]
    # comma-joined shape too
    event["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:groups"] = "pp-reviewers,pp-admins"
    ident = authz.claims_from_event(event)
    assert ident["role"] == "admin" and set(ident["groups"]) == {"pp-admins", "pp-reviewers"}


def test_bracket_flattened_groups_live_shape(signed_token):
    """THE LIVE SHAPE (T41c AUTHDEBUG, 2026-09-19T15:50Z): API GW delivers
    cognito:groups as the literal string '\"[pp-admins]\"' — the list
    flattened to bracket form and quoted. Must parse to ['pp-admins']."""
    event = _gw_event(signed_token, with_groups=False)
    event["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:groups"] = '["pp-admins"]'
    ident = authz.claims_from_event(event)
    assert ident["role"] == "admin" and ident["groups"] == ["pp-admins"]
    # and the bracket-flattened, JSON-unquoted variant
    event["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:groups"] = "[pp-admins]"
    ident = authz.claims_from_event(event)
    assert ident["role"] == "admin" and ident["groups"] == ["pp-admins"]
    # multiple groups, flattened
    event["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:groups"] = "[pp-reviewers, pp-admins]"
    ident = authz.claims_from_event(event)
    assert ident["role"] == "admin" and set(ident["groups"]) == {"pp-admins", "pp-reviewers"}
    # garbage stays fail-closed
    event["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:groups"] = "[[["
    ident = authz.claims_from_event(event)
    assert ident["role"] == "readonly"


def test_groupless_with_malformed_token_stays_readonly(signed_token):
    """Secure default: garbage token + group-less claims -> readonly, no 500."""
    ident = authz.claims_from_event(_gw_event("garbage.sig.here", with_groups=False))
    assert ident["role"] == "readonly"


def test_groupless_without_header_stays_readonly(signed_token):
    """No header, no groups: reads-only identity, writes still denied."""
    ident = authz.claims_from_event(_gw_event(None, with_groups=False))
    assert ident["role"] == "readonly"
    with pytest.raises(authz.AuthzError):
        authz.authorize("POST", "/builds", ident, {"domain": "research_grant", "defer": True})
