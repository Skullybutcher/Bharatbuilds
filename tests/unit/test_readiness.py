"""Regression checks for production-readiness audit findings."""
from io import BytesIO

import pytest

from services import storage
from services.api import authz, actions
from services.api.server import Handler, _AuthzHTTP
from services.aws_handlers import api_handler


@pytest.mark.parametrize("token", ["bad", "a.b.c.d", "e30.e30.!", "W10.W10.eA"])
def test_malformed_tokens_are_unauthorized(monkeypatch, token):
    monkeypatch.setenv("PROCESSPATCH_AUTH", "hs256-test")
    monkeypatch.setenv("PP_DEV_HS256_SECRET", "test-secret")
    with pytest.raises(authz.AuthzError) as exc:
        authz.authenticate({"Authorization": "Bearer " + token})
    assert exc.value.status == 401


@pytest.mark.parametrize("expiry", [None, "tomorrow", float("nan"), float("inf"), True, 0])
def test_invalid_expiry_is_rejected(expiry):
    with pytest.raises(authz.AuthzError) as exc:
        authz._check_claims({"exp": expiry})
    assert exc.value.status == 401


@pytest.mark.parametrize("groups", [["pp-admins"], '["pp-admins"]', '[pp-admins]', 'pp-admins'])
def test_gateway_group_serialization(monkeypatch, groups):
    monkeypatch.setenv("PROCESSPATCH_AUTH", "cognito")
    event = {"requestContext": {"authorizer": {"jwt": {"claims": {
        "cognito:groups": groups, "sub": "reviewer-1"}}}}}
    assert authz.claims_from_event(event)["role"] == "admin"


def test_dynamodb_reads_all_pages(monkeypatch):
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "dynamodb")
    calls = []

    class Table:
        def query(self, **kwargs):
            calls.append(kwargs)
            if "ExclusiveStartKey" not in kwargs:
                return {"Items": [{"SK": "a", "data_json": '{"id":1}'}],
                        "LastEvaluatedKey": {"PK": "COLL#test", "SK": "a"}}
            return {"Items": [{"SK": "b", "data_json": '{"id":2}'}]}

    monkeypatch.setattr(storage, "_dd", lambda: Table())
    assert storage._load("test", []) == [{"id": 1}, {"id": 2}]
    assert len(calls) == 2
    assert calls[1]["ExclusiveStartKey"]["SK"] == "a"


def test_failed_file_replace_preserves_previous_data(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage._file_save("test.json", {"original": True})

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(OSError):
        storage._file_save("test.json", {"replacement": True})
    assert storage._file_load("test.json", {}) == {"original": True}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("body", ['{bad', '[]', 'null', '42'])
def test_bad_request_body_rejected_on_both_surfaces(monkeypatch, body):
    monkeypatch.setenv("PROCESSPATCH_AUTH", "off")
    event = {"routeKey": "POST /builds", "rawPath": "/builds",
             "requestContext": {"http": {"method": "POST"}}, "body": body}
    assert api_handler(event, None)["statusCode"] == 400
    handler = object.__new__(Handler)
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = BytesIO(body.encode())
    with pytest.raises(_AuthzHTTP) as exc:
        handler._body()
    assert exc.value.status == 400


def test_build_save_failure_is_not_success(monkeypatch):
    from services.registry import store

    def fail(*args):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(store, "save_build", fail)
    with pytest.raises(RuntimeError):
        actions._store({"build_id": "READINESS-FAIL"})
    assert "READINESS-FAIL" not in actions.MEMO


def test_build_read_uses_current_persisted_state(monkeypatch):
    from services.registry import store
    monkeypatch.setitem(actions.MEMO, "READINESS-STALE", {"status": "old"})
    monkeypatch.setattr(store, "get_build", lambda bid: {"status": "current"})
    assert actions._get_build("READINESS-STALE")["status"] == "current"


def test_model_rules_cannot_opt_into_automatic_acceptance(monkeypatch, tmp_path):
    from services.extractor import model_fallback
    from services.governance.store import rule_reviews
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    _, rules, _ = actions._demo()
    monkeypatch.setattr(model_fallback, "extract_with_fallback", lambda *args: {
        "rules": rules, "status": "EXTRACTED", "backend": "bedrock:test"})
    build = actions.create_build({"policy_text": "model input", "auto_accept": True, "force": True})
    reviews = rule_reviews(build["build_id"])
    assert reviews
    assert all(r["decision"] == "PENDING" for r in reviews)


def test_storage_outage_returns_service_unavailable(monkeypatch):
    monkeypatch.setenv("PROCESSPATCH_AUTH", "off")

    def fail(*_args, **_kwargs):
        # arity-agnostic: this simulates a storage outage whatever the route
        # passes (GET /builds now forwards the include_archived flag)
        raise RuntimeError("private database detail")

    monkeypatch.setattr(actions, "list_builds", fail)
    result = api_handler({"routeKey": "GET /builds", "rawPath": "/builds",
                          "requestContext": {"http": {"method": "GET"}}}, None)
    assert result["statusCode"] == 503
    assert "private" not in result["body"]
