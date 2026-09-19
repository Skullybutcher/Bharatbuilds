"""Authn/authz enforcement tests — HS256-test mode (no network).

Covers: mode off is a no-op; tampered/expired tokens rejected; group → role
mapping; readonly cannot write; reviewer can review/approve but not activate;
admin can activate; verified identity is stamped over caller-supplied
reviewer/role; public paths stay open.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

import pytest

from services.api import authz


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


@pytest.fixture()
def hs_mode(monkeypatch):
    secret = "test-secret-not-for-prod"
    monkeypatch.setenv("PROCESSPATCH_AUTH", "hs256-test")
    monkeypatch.setenv("PP_DEV_HS256_SECRET", secret)
    return secret


def _token(secret: str, groups=("pp-reviewers",), email="rev@example.com", **extra) -> str:
    head = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {"email": email, "cognito:groups": list(groups), "exp": int(time.time()) + 600, **extra}
    body = _b64u(json.dumps(claims).encode())
    sig = _b64u(hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def _auth_header(tok: str) -> dict:
    return {"authorization": f"Bearer {tok}"}


def test_mode_off_is_legacy(monkeypatch):
    monkeypatch.delenv("PROCESSPATCH_AUTH", raising=False)
    assert authz.mode() == "off"
    assert authz.authenticate({}) is None
    body = {"reviewer": {"reviewer_id": "spoofed"}}
    assert authz.authorize("POST", "/procedures/V1/activate", None, body) is body


def test_missing_token_401(hs_mode):
    with pytest.raises(authz.AuthzError) as e:
        authz.authenticate({})
    assert e.value.status == 401


def test_tampered_token_401(hs_mode):
    tok = _token(hs_mode)
    h, b, s = tok.rsplit(".", 2)
    bad = f"{h}.{b}." + _b64u(b"forged")
    with pytest.raises(authz.AuthzError) as e:
        authz.authenticate(_auth_header(bad))
    assert e.value.status == 401


def test_expired_token_401(hs_mode):
    tok = _token(hs_mode, exp=int(time.time()) - 10)
    with pytest.raises(authz.AuthzError) as e:
        authz.authenticate(_auth_header(tok))
    assert e.value.status == 401


def test_group_mapping(hs_mode):
    rev = authz.authenticate(_auth_header(_token(hs_mode, groups=("pp-reviewers",))))
    assert rev["role"] == "reviewer"
    adm = authz.authenticate(_auth_header(_token(hs_mode, groups=("pp-admins",))))
    assert adm["role"] == "admin"
    ro = authz.authenticate(_auth_header(_token(hs_mode, groups=())))
    assert ro["role"] == "readonly"


def test_public_paths_open(hs_mode):
    assert authz.is_public("GET", "/health")
    assert authz.is_public("GET", "/auth/config")
    assert authz.is_public("GET", "/demo/canonical")
    assert not authz.is_public("GET", "/builds")
    # public paths reachable without identity even in enforced mode
    authz.authorize("GET", "/health", None)


def test_readonly_cannot_write(hs_mode):
    ro = authz.authenticate(_auth_header(_token(hs_mode, groups=())))
    with pytest.raises(authz.AuthzError) as e:
        authz.authorize("POST", "/builds/B1/rules/R1/accept", ro, {"reason": "ok"})
    assert e.value.status == 403
    with pytest.raises(authz.AuthzError) as e:
        authz.authorize("POST", "/builds/B1/patch/approve", ro, {})
    assert e.value.status == 403


def test_reviewer_can_review_and_approve_not_activate(hs_mode):
    rev = authz.authenticate(_auth_header(_token(hs_mode, groups=("pp-reviewers",))))
    out = authz.authorize("POST", "/builds/B1/rules/R1/accept", rev, {"reason": "ok", "reviewer": "spoof"})
    assert out["reviewer"] == "rev@example.com"  # stamped, not caller-supplied
    out = authz.authorize("POST", "/builds/B1/patch/approve", rev, {"reviewer": {"reviewer_id": "spoof"}})
    assert out["reviewer"]["reviewer_id"] == "rev@example.com"
    assert out["role"] == "PROCEDURE_OWNER"
    with pytest.raises(authz.AuthzError) as e:
        authz.authorize("POST", "/procedures/V1/activate", rev, {"build_id": "B1"})
    assert e.value.status == 403


def test_admin_activation_and_role_stamp(hs_mode):
    adm = authz.authenticate(_auth_header(_token(hs_mode, groups=("pp-admins",), email="adm@example.com")))
    out = authz.authorize("POST", "/procedures/V1/activate", adm,
                          {"build_id": "B1", "reviewer": {"reviewer_id": "spoof"}, "role": "POLICY_REVIEWER"})
    assert out["reviewer"]["reviewer_id"] == "adm@example.com"
    assert out["reviewer"]["reviewer_id"] != "spoof"
    # activation gate via resume path is admin-only too
    rev = authz.authenticate(_auth_header(_token(hs_mode, groups=("pp-reviewers",))))
    with pytest.raises(authz.AuthzError):
        authz.authorize("POST", "/builds/B1/resume", rev, {"gate": "activation", "decision": "APPROVE"})


def test_resume_gate_decides_policy(hs_mode):
    rev = authz.authenticate(_auth_header(_token(hs_mode, groups=("pp-reviewers",))))
    out = authz.authorize("POST", "/builds/B1/resume", rev,
                          {"gate": "patch_approval", "decision": "APPROVE_CANDIDATE"})
    assert out["reviewer"]["reviewer_id"] == "rev@example.com"
    assert out["role"] == "PROCEDURE_OWNER"


def test_reads_open_to_any_signed_in(hs_mode):
    ro = authz.authenticate(_auth_header(_token(hs_mode, groups=())))
    assert authz.authorize("GET", "/builds/B1/impact", ro, None) == {}
