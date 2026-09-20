"""Authentication + authorization — shared by the local stdlib server and the
Lambda ApiFn, so both surfaces enforce identical rules.

Design (docs/auth.md):
- Cloud: Cognito UserPool + hosted UI (PKCE). Clients send
  `Authorization: Bearer <JWT>`. Lambda trusts API Gateway's Cognito
  authorizer (claims arrive in event.requestContext.authorizer.jwt.claims);
  the local server verifies the same JWTs itself.
- Groups gate writes: `pp-admins` (approve + activate), `pp-reviewers`
  (rule review + patch decisions). Users in neither group are read-only.
- Modes via PROCESSPATCH_AUTH:
    off         default; credential-free local dev. Caller-supplied reviewer
                fields are trusted exactly as before (zero behavior change).
    cognito     enforce Cognito JWTs (RS256 verified against the pool JWKS).
    hs256-test  TEST ONLY: HMAC verification against PP_DEV_HS256_SECRET so
                unit/journey tests can exercise enforcement without network.
                Never enable in production.
- A verified identity is stamped into the request body (reviewer/role), so
  callers cannot spoof reviewer identity when auth is enforced.

The server/lambda routes call authorize(method, path, identity, body) which
returns the (possibly identity-stamped) body or raises AuthzError.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import math
import binascii
import urllib.request

ADMIN_GROUP = "pp-admins"
REVIEWER_GROUP = "pp-reviewers"
READ_ONLY = "readonly"
W_ROLES = ("admin", "reviewer")

# Routes reachable without a token (mirror of the HttpApi NO_AUTH events).
PUBLIC_PATHS = frozenset({"/", "/health", "/demo/canonical", "/auth/config"})

_CACHE: dict = {"jwks": None, "fetched": 0.0}


class AuthzError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def mode() -> str:
    return (os.environ.get("PROCESSPATCH_AUTH") or "off").strip().lower()


# ---------------------------------------------------------------- tokens ----
def _b64url_dec(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def _b64url_enc(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _pool_coords() -> tuple[str, str, str]:
    """(region, user_pool_id, app_client_id) from env."""
    pool = os.environ.get("PP_USER_POOL_ID", "")
    if "_" not in pool:
        raise AuthzError(500, "PP_USER_POOL_ID missing/malformed")
    region = os.environ.get("AWS_REGION") or pool.split("_", 1)[0]
    client = os.environ.get("PP_CLIENT_ID", "")
    if not client:
        raise AuthzError(500, "PP_CLIENT_ID missing")
    return region, pool, client


def _issuer() -> str:
    region, pool, _ = _pool_coords()
    return f"https://cognito-idp.{region}.amazonaws.com/{pool}"


def _fetch_jwks() -> dict:
    if _CACHE["jwks"] and time.time() - _CACHE["fetched"] < 3600:
        return _CACHE["jwks"]
    url = _issuer() + "/.well-known/jwks.json"
    with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 (fixed https URL)
        _CACHE["jwks"] = json.loads(r.read().decode())
    _CACHE["fetched"] = time.time()
    return _CACHE["jwks"]


def _rs256_verify(token: str) -> dict:
    h, p, s = (token.split(".") + ["", ""])[:3]
    header = json.loads(_b64url_dec(h))
    if header.get("alg") != "RS256":
        raise AuthzError(401, "unsupported alg")
    jwk = next((k for k in _fetch_jwks().get("keys", []) if k.get("kid") == header.get("kid")), None)
    if not jwk:
        raise AuthzError(401, "unknown signing key")
    n = int.from_bytes(_b64url_dec(jwk["n"]), "big")
    e = int.from_bytes(_b64url_dec(jwk["e"]), "big")
    sig = int.from_bytes(_b64url_dec(s), "big")
    if sig >= n:
        raise AuthzError(401, "bad signature")
    k = (n.bit_length() + 7) // 8
    em = pow(sig, e, n).to_bytes(k, "big")
    # PKCS#1 v1.5: 00 01 FF..FF 00 || DigestInfo(SHA-256) || hash(head.payload)
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420")
    expected = b"\x00\x01" + b"\xff" * (k - len(digest_info) - len(hashlib.sha256(f"{h}.{p}".encode()).digest()) - 3) + b"\x00" + digest_info + hashlib.sha256(f"{h}.{p}".encode()).digest()
    if not hmac.compare_digest(em, expected):
        raise AuthzError(401, "signature mismatch")
    return json.loads(_b64url_dec(p))


def _hs256_verify(token: str) -> dict:
    secret = os.environ.get("PP_DEV_HS256_SECRET", "")
    if not secret:
        raise AuthzError(500, "PP_DEV_HS256_SECRET not set")
    h, p, s = (token.split(".") + ["", ""])[:3]
    header = json.loads(_b64url_dec(h))
    if header.get("alg") != "HS256":
        raise AuthzError(401, "unsupported alg")
    want = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(want, _b64url_dec(s)):
        raise AuthzError(401, "signature mismatch")
    return json.loads(_b64url_dec(p))


def _check_claims(claims: dict) -> None:
    expiry = claims.get("exp", 0)
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry):
        raise AuthzError(401, "invalid token expiry")
    if expiry <= time.time():
        raise AuthzError(401, "token expired")
    if mode() == "cognito":
        _, _, client = _pool_coords()
        if claims.get("iss") != _issuer():
            raise AuthzError(401, "wrong issuer")
        if claims.get("token_use") == "access":
            if claims.get("client_id") != client:
                raise AuthzError(401, "wrong client")
        elif claims.get("token_use") != "id":
            raise AuthzError(401, "unsupported token use")
        elif claims.get("aud") != client:
            raise AuthzError(401, "wrong audience")


# ------------------------------------------------------------- identity ----
def authenticate(headers: dict) -> dict | None:
    """Verify the bearer token (if any) and return an identity dict.
    Returns None in `off` mode. Raises AuthzError(401) on bad tokens."""
    if mode() == "off":
        return None
    auth = (headers.get("authorization") or headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        raise AuthzError(401, "sign in required (Authorization: Bearer <token>)")
    token = auth[7:].strip()
    if mode() not in ("cognito", "hs256-test"):
        raise AuthzError(500, "unsupported authentication mode")
    try:
        if len(token.split(".")) != 3:
            raise ValueError("invalid token segments")
        claims = _rs256_verify(token) if mode() == "cognito" else _hs256_verify(token)
        _check_claims(claims)
        groups = _groups(claims.get("cognito:groups"))
    except (ValueError, TypeError, KeyError, AttributeError, binascii.Error) as exc:
        raise AuthzError(401, "malformed bearer token") from exc
    if ADMIN_GROUP in groups:
        role = "admin"
    elif REVIEWER_GROUP in groups:
        role = "reviewer"
    else:
        role = READ_ONLY
    return {"reviewer_id": claims.get("email") or claims.get("username") or claims.get("sub", "?"),
            "display_name": claims.get("email") or claims.get("name") or "reviewer",
            "role": role, "groups": sorted(groups), "via": mode()}


def _groups(value) -> set[str]:
    # HTTP API authorizer claims may serialize an array as a string.
    if isinstance(value, str):
        value = value.strip()
        try:
            value = json.loads(value)
        except ValueError:
            value = value.strip("[]").split(",")
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {g.strip() for g in value if isinstance(g, str) and g.strip()}


def claims_from_event(event: dict) -> dict | None:
    """Lambda path: API Gateway Cognito authorizer already validated the JWT."""
    if mode() == "off":
        return None
    ctx = (event.get("requestContext") or {}).get("authorizer") or {}
    claims = ctx.get("jwt", {}).get("claims") or ctx.get("claims") or {}
    if not claims:
        return None  # authorizer absent -> authenticate(headers) will 401
    groups = _groups(claims.get("cognito:groups"))
    if not groups:
        # Some HTTP API JWT-authorizer configurations drop colon-carrying claim
        # keys (cognito:groups, cognito:username) before they reach the
        # function — live-verified in the T41 smoke: role collapsed to
        # READ_ONLY and every write 403'd despite a valid pp-admins token. The
        # bearer header is ground truth (API GW already verified its
        # signature), so re-derive the identity from the token itself with a
        # full RS256 verify (cached JWKS) instead of trusting a group-less
        # claims dict. If the header is missing/invalid, keep the claims-based
        # identity (reads still work; writes stay denied).
        try:
            return authenticate(event.get("headers") or {})
        except (AuthzError, ValueError):  # ValueError: malformed token base64 (binascii.Error subclasses it)
            pass
    role = "admin" if ADMIN_GROUP in groups else ("reviewer" if REVIEWER_GROUP in groups else READ_ONLY)
    return {"reviewer_id": claims.get("email") or claims.get("username") or claims.get("sub", "?"),
            "display_name": claims.get("email") or claims.get("name") or "reviewer",
            "role": role, "groups": sorted(groups), "via": "cognito-authorizer"}


# ---------------------------------------------------------- authorization ----
_ACTIVATE = ("procedures", "activate")


def _needs_admin(method: str, path: str, body: dict) -> bool:
    if method == "POST" and path.startswith("/procedures/") and path.endswith("/activate"):
        return True
    # Hard deletion is admin-only (and still refused unless PP_DEMO_PURGE is set).
    if method == "POST" and path.endswith("/purge"):
        return True
    if method == "POST" and "/resume" in path and body.get("gate") == "activation":
        return True
    return False


def _writable(method: str, path: str) -> bool:
    """POSTs that reviewers (not just admins) may perform."""
    if method != "POST":
        return False
    if path in ("/builds", "/builds/", "/traces", "/traces/csv", "/workspaces", "/procedures") or \
       path.endswith("/execute") or path.endswith("/replay") or path.endswith("/resume") or \
       path.endswith("/patch/validate") or path.endswith("/patch/review-request") or \
       path.endswith("/nominate-witness"):
        return True
    if "/rules/" in path and path.split("/")[-1] in ("accept", "edit", "reject", "escalate"):
        return True
    if path.endswith(("patch/approve", "patch/reject", "patch/request-revision")):
        return True
    # Retiring a build from the console is a reviewer-level write; the hard
    # delete next to it (`/purge`) is admin-only via _needs_admin.
    if path.endswith(("/archive", "/unarchive")):
        return True
    # Re-verification re-runs the deterministic pipeline and writes one audit
    # row — a read-shaped write any reviewer may run.
    if path.endswith("/reverify"):
        return True
    return False


def is_public(method: str, path: str) -> bool:
    return method == "GET" and path in PUBLIC_PATHS


def authorize(method: str, path: str, identity: dict | None, body: dict | None = None) -> dict:
    """Enforce the route policy and stamp verified identity into the body.
    `off` mode: returns the body untouched (legacy caller-supplied identity)."""
    body = body or {}
    if mode() == "off":
        return body
    if not identity:
        if is_public(method, path):
            return body
        raise AuthzError(401, "sign in required")
    if _needs_admin(method, path, body):
        if identity["role"] != "admin":
            raise AuthzError(403, "activation requires the pp-admins group")
        body = {**body, "reviewer": {"reviewer_id": identity["reviewer_id"],
                                     "display_name": identity["display_name"]}}
        return body
    if _writable(method, path):
        if identity["role"] not in W_ROLES:
            raise AuthzError(403, "writes require the pp-reviewers or pp-admins group")
        if method == "POST" and path in ("/builds", "/builds/"):
            body = {**body, "workspace_id": check_request_workspace(identity, body, path, "compile")}
        elif method == "POST" and path in ("/traces", "/traces/csv"):
            body = {**body, "workspace_id": check_request_workspace(identity, body, path, "ingest")}
        if "/rules/" in path:
            body = {**body, "reviewer": identity["reviewer_id"]}
        elif path.endswith(("patch/approve", "patch/reject", "patch/request-revision")) or \
                "/resume" in path:
            body = {**body, "reviewer": {"reviewer_id": identity["reviewer_id"],
                                         "display_name": identity["display_name"]},
                    "role": "FINAL_APPROVER" if identity["role"] == "admin" else "PROCEDURE_OWNER"}
        return body
    return body  # GETs and reads: any signed-in identity


# ------------------------------------------------- workspace isolation ----
# D3 multi-tenancy (T63): membership comes from Cognito groups. `ws-<id>` is
# membership in that workspace; pp-admins is superuser (all workspaces); a
# caller with zero ws-* groups belongs to {"default"} only, so the demo user
# (pp groups, no ws groups) keeps working with zero setup. PROCESSPATCH_AUTH
# =off (local dev): identity is None everywhere below, so behavior is
# identical to before. Procedures/procedure versions stay a GLOBAL shared
# registry by explicit decision (activation is workspace-agnostic today).
WS_PREFIX = "ws-"
DEFAULT_WS = "default"


def ws_membership(identity):
    """(is_admin, members) for workspace enforcement.

    members None means no enforcement (off-mode / no identity): treat None
    as 'no filtering'. Admins are superusers. Everyone else belongs to
    their ws-* groups, or to {"default"} when they have none."""
    if identity is None:
        return (False, None)
    groups = identity.get("groups") or []
    if ADMIN_GROUP in groups:
        return (True, None)
    members = {g[len(WS_PREFIX):] for g in groups
               if isinstance(g, str) and g.startswith(WS_PREFIX)
               and g[len(WS_PREFIX):].strip()}
    return (False, members or {DEFAULT_WS})


def _deny_workspace(identity, workspace, path, action, build_id=None):
    """Record every workspace denial in the governance ledger, then let the
    caller raise. An audit-write failure must never convert a denial into a
    500, so write errors are swallowed — the 403 below always stands."""
    try:
        from services.registry.store import audit as _audit
        payload = {"workspace": workspace, "path": path, "action": action,
                   "reviewer": (identity or {}).get("reviewer_id", "?")}
        if build_id:
            payload["build_id"] = build_id
        _audit("ACCESS_DENIED", payload)
    except Exception:
        pass


def resolve_list_filter(identity, requested, path):
    """(scope, workspace) for list endpoints. scope None = unfiltered.

    Honors an explicit ?workspace_id= only for members (admins: always).
    Raises AuthzError(403) — audited — on non-member requests."""
    if requested is not None:
        requested = requested.strip() if isinstance(requested, str) else ""
        requested = requested or None
    if identity is None:
        return (None, requested)  # off-mode legacy: plain filter, no checks
    is_admin, members = ws_membership(identity)
    if is_admin:
        return (None, requested)
    if requested is not None and requested not in members:
        _deny_workspace(identity, requested, path, "list-filter")
        raise AuthzError(403, f"workspace '{requested}' is not one of yours")
    if requested is not None:
        return (None, requested)
    return (set(members), None)


def require_build_member(identity, build, path):
    """Per-build gate for the /builds/{id} subtree (both surfaces call this
    with the loaded record; unknown builds never reach here — they 404
    first). Legacy records without workspace_id count as 'default'."""
    if identity is None:
        return  # off-mode legacy
    ws = (build or {}).get("workspace_id") or DEFAULT_WS
    is_admin, members = ws_membership(identity)
    if is_admin or (members is not None and ws in members):
        return
    _deny_workspace(identity, ws, path, "build-access", (build or {}).get("build_id"))
    raise AuthzError(403, "build is not in a workspace you can access")


def check_request_workspace(identity, body, path, action):
    """Validate + normalize body workspace_id for compile/ingest POSTs.

    Absent means 'default'; the value must be a member workspace (admins:
    any). Returns the normalized id. Raises 400 (malformed) or 403 (denied,
    audited). No-op without identity (off-mode legacy)."""
    ws = (body or {}).get("workspace_id")
    if ws is None:
        return DEFAULT_WS
    if not isinstance(ws, str) or not ws.strip():
        raise AuthzError(400, "workspace_id must be a non-empty string")
    ws = ws.strip()
    if identity is None:
        return ws
    is_admin, members = ws_membership(identity)
    if not is_admin and (members is None or ws not in members):
        _deny_workspace(identity, ws, path, action)
        raise AuthzError(403, f"workspace '{ws}' is not one of yours")
    return ws
