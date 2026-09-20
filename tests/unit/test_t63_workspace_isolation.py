"""Workspace isolation (T63, D3 multi-tenancy) — HS256-test mode, no network.

Covers the compat contract: membership from ws-* groups (pp-admins =
superuser, zero ws-* groups = {"default"} only), off-mode passthrough,
scoped lists, per-build 403 + ACCESS_DENIED audit, admin override, compile
refused into non-member workspaces, trace ingest stamping + scoping.
Storage is hermetic (PROCESSPATCH_DATA functional equivalent: the shared
services.storage.DATA_DIR pointed at tmp_path).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

import services.storage as _storage
from services.api import actions, authz
from services.registry.store import audit_for, save_build


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


@pytest.fixture()
def hs_mode(monkeypatch):
    secret = "t63-secret-not-for-prod"
    monkeypatch.setenv("PROCESSPATCH_AUTH", "hs256-test")
    monkeypatch.setenv("PP_DEV_HS256_SECRET", secret)
    return secret


@pytest.fixture()
def _iso_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(_storage, "DATA_DIR", str(tmp_path))
    yield tmp_path


def _token(secret: str, groups=(), email="u@example.com") -> str:
    head = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {"email": email, "cognito:groups": list(groups),
              "exp": int(time.time()) + 600}
    body = _b64u(json.dumps(claims).encode())
    sig = _b64u(hmac.new(secret.encode(), f"{head}.{body}".encode(),
                         hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def _ident(secret, groups=(), email="u@example.com"):
    return authz.authenticate(
        {"authorization": f"Bearer {_token(secret, groups, email)}"})


def _seed_builds():
    save_build({"build_id": "B-DEF", "status": "READY", "workspace_id": "default"})
    save_build({"build_id": "B-ACME", "status": "READY", "workspace_id": "acme"})
    save_build({"build_id": "B-LEGACY", "status": "READY"})  # no workspace: legacy


def _denials():
    return [e for e in audit_for() if e.get("event") == "ACCESS_DENIED"]


def test_zero_ws_groups_is_default_only(hs_mode):
    _, members = authz.ws_membership(_ident(hs_mode, ("pp-reviewers",)))
    assert members == {"default"}


def test_admin_is_superuser_scope(hs_mode):
    is_admin, members = authz.ws_membership(
        _ident(hs_mode, ("pp-admins",), "adm@example.com"))
    assert is_admin and members is None


def test_off_mode_passes_through(monkeypatch):
    monkeypatch.delenv("PROCESSPATCH_AUTH", raising=False)
    body = {"workspace_id": "acme", "reviewer": "spoof"}
    assert authz.authorize("POST", "/builds", None, body) is body
    assert authz.resolve_list_filter(None, "acme", "/builds") == (None, "acme")
    authz.require_build_member(None, {"workspace_id": "nope"}, "/builds/X")
    assert authz.check_request_workspace(None, {}, "/builds", "compile") == "default"


def test_member_list_filtered(hs_mode, _iso_tmp):
    _seed_builds()
    ident = _ident(hs_mode, ("pp-reviewers", "ws-acme"))
    scope, ws = authz.resolve_list_filter(ident, None, "/builds")
    assert (scope, ws) == ({"acme"}, None)
    got = {b["build_id"] for b in actions.list_builds(False, scope, ws)["builds"]}
    assert got == {"B-ACME"}


def test_member_read_ok_and_own_filter(hs_mode, _iso_tmp):
    _seed_builds()
    ident = _ident(hs_mode, ("pp-reviewers", "ws-acme"))
    scope, ws = authz.resolve_list_filter(ident, "acme", "/builds")
    assert (scope, ws) == (None, "acme")
    got = {b["build_id"] for b in actions.list_builds(False, scope, ws)["builds"]}
    assert got == {"B-ACME"}
    authz.require_build_member(
        ident, {"build_id": "B-ACME", "workspace_id": "acme"}, "/builds/B-ACME")


def test_explicit_foreign_workspace_403_and_audit(hs_mode, _iso_tmp):
    ident = _ident(hs_mode, ("pp-reviewers",), "rev@example.com")
    with pytest.raises(authz.AuthzError) as e:
        authz.resolve_list_filter(ident, "acme", "/builds")
    assert e.value.status == 403
    rows = _denials()
    assert len(rows) == 1
    row = rows[0]
    assert row["workspace"] == "acme" and row["path"] == "/builds"
    assert row["reviewer"] == "rev@example.com"


def test_single_build_403_and_audit(hs_mode, _iso_tmp):
    _seed_builds()
    ident = _ident(hs_mode, ("pp-reviewers",), "rev@example.com")
    with pytest.raises(authz.AuthzError) as e:
        authz.require_build_member(
            ident, {"build_id": "B-ACME", "workspace_id": "acme"},
            "/builds/B-ACME/diff")
    assert e.value.status == 403
    rows = _denials()
    assert len(rows) == 1
    assert rows[0]["build_id"] == "B-ACME"
    assert rows[0]["workspace"] == "acme"
    # legacy record without workspace_id counts as default: visible here
    authz.require_build_member(
        ident, {"build_id": "B-LEGACY"}, "/builds/B-LEGACY")


def test_admin_override(hs_mode, _iso_tmp):
    _seed_builds()
    adm = _ident(hs_mode, ("pp-admins",), "adm@example.com")
    scope, ws = authz.resolve_list_filter(adm, None, "/builds")
    assert (scope, ws) == (None, None)
    got = {b["build_id"] for b in actions.list_builds(False, scope, ws)["builds"]}
    assert got == {"B-DEF", "B-ACME", "B-LEGACY"}
    scope, ws = authz.resolve_list_filter(adm, "acme", "/builds")
    assert (scope, ws) == (None, "acme")
    authz.require_build_member(
        adm, {"build_id": "B-ACME", "workspace_id": "acme"}, "/builds/B-ACME")
    out = authz.authorize("POST", "/builds", adm, {"domain": "research_grant"})
    assert out["workspace_id"] == "default"


def test_compile_workspace_refused_and_stamped(hs_mode, _iso_tmp):
    rev = _ident(hs_mode, ("pp-reviewers",), "rev@example.com")
    with pytest.raises(authz.AuthzError) as e:
        authz.authorize("POST", "/builds", rev,
                        {"domain": "research_grant", "workspace_id": "acme"})
    assert e.value.status == 403
    assert _denials()[0]["action"] == "compile"
    out = authz.authorize("POST", "/builds", rev, {"domain": "research_grant"})
    assert out["workspace_id"] == "default"  # absent means default
    with pytest.raises(authz.AuthzError) as e:
        authz.authorize("POST", "/builds", rev, {"workspace_id": 123})
    assert e.value.status == 400


def test_traces_scoped_and_stamped(hs_mode, _iso_tmp):
    member = _ident(hs_mode, ("pp-reviewers", "ws-acme"))
    other = _ident(hs_mode, ("pp-reviewers",))
    t1 = actions.ingest_trace(authz.authorize("POST", "/traces", member, {
        "case": {"cgpa": 7.1}, "outcome": {"eligible": False},
        "workspace_id": "acme"}))
    assert t1["workspace_id"] == "acme"
    t0 = actions.ingest_trace(authz.authorize("POST", "/traces", member, {
        "case": {"cgpa": 7.0}, "outcome": {"eligible": False}}))
    assert t0["workspace_id"] == "default"  # absent means default
    t2 = actions.ingest_trace(authz.authorize("POST", "/traces", other, {
        "case": {"cgpa": 7.2}, "outcome": {"eligible": False}}))
    assert t2["workspace_id"] == "default"
    scope, ws = authz.resolve_list_filter(member, None, "/traces")
    got = {t["trace_id"] for t in actions.list_traces(None, scope, ws)["traces"]}
    assert got == {t1["trace_id"]}
    scope, ws = authz.resolve_list_filter(other, None, "/traces")
    got = {t["trace_id"] for t in actions.list_traces(None, scope, ws)["traces"]}
    assert got == {t0["trace_id"], t2["trace_id"]}
    with pytest.raises(authz.AuthzError) as e:
        authz.authorize("POST", "/traces", other,
                        {"case": {"cgpa": 1}, "outcome": {"eligible": False},
                         "workspace_id": "acme"})
    assert e.value.status == 403


def test_demo_user_compat(hs_mode, _iso_tmp):
    # pp-admins + pp-reviewers, zero ws-* groups: full default visibility.
    demo = _ident(hs_mode, ("pp-admins", "pp-reviewers"), "demo@example.com")
    _, members = authz.ws_membership(demo)
    assert members is None  # admin: superuser
    _seed_builds()
    scope, ws = authz.resolve_list_filter(demo, None, "/builds")
    got = {b["build_id"] for b in actions.list_builds(False, scope, ws)["builds"]}
    assert got == {"B-DEF", "B-ACME", "B-LEGACY"}
    out = authz.authorize("POST", "/builds", demo, {"domain": "research_grant"})
    assert out["workspace_id"] == "default"
