import json
import os
import pathlib
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="pp-test-api-")
os.environ["PROCESSPATCH_DATA"] = TMP
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _event(method, path, body=None):
    return {"routeKey": f"{method} {path}", "queryStringParameters": {},
            "body": json.dumps(body or {})}


def test_lambda_serves_same_surface():
    from services.aws_handlers import api_handler
    from services.api import actions
    h = api_handler(_event("GET", "/"), None)
    assert h["statusCode"] == 200
    assert json.loads(h["body"])["status"] == "ok"
    b = api_handler(_event("POST", "/builds", {"domain": "research_grant"}), None)
    assert b["statusCode"] == 200
    bid = json.loads(b["body"])["build_id"]
    for route in ("diff", "witnesses", "patch", "impact", "guardrails"):
        r = api_handler(_event("GET", f"/builds/{bid}/{route}"), None)
        assert r["statusCode"] == 200, route
    assert actions.get_build_view(bid)["build_id"] == bid
    r = api_handler(_event("GET", "/nope"), None)
    assert r["statusCode"] == 404
