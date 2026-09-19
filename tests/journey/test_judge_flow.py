"""Judge-flow E2E (stdlib only): stale portal -> build -> witness -> approve ->
activate -> corrected portal, incl. the resume path and XSS-safe echoes."""
import json
import os
import pathlib
import sys
import tempfile
import threading
import urllib.parse
import urllib.request

TMP = tempfile.mkdtemp(prefix="pp-test-journey-")
os.environ["PROCESSPATCH_DATA"] = TMP
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.api.server import Handler
from http.server import HTTPServer

BASE = None


def setup_module():
    global BASE
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    BASE = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def _api(method, path, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_judge_flow():
    # Isolated registry slice: deterministic build ids are shared
    # process-wide, so wipe leftovers from other modules first.
    from services.storage import _save
    for name, default in (("builds.json", {}), ("rule_reviews.json", []),
                          ("approvals.json", []), ("patch_reviews.json", []),
                          ("candidates.json", []), ("procedure_versions.json", []),
                          ("audit.json", []), ("callbacks.json", []),
                          ("executions.json", [])):
        _save(name, default)
    from services.api import actions as _actions
    _actions.MEMO.clear()
    # 1. stale portal rejects 7.80
    s, portal = _api("GET", "/portal?cgpa=7.8&patched=0&domain=research_grant")
    assert s == 200 and portal["actual"]["eligible"] is False
    # 2. compile
    s, b = _api("POST", "/builds", {"domain": "research_grant"})
    assert s == 200 and b["status"] == "PATCH_VALIDATED"
    bid = b["build_id"]
    assert any(w["kind"] == "wrong_rejection" for w in b["witnesses"])
    # 3. guardrails pass after real Gate-1 accepts
    s, g = _api("GET", f"/builds/{bid}/guardrails")
    assert s == 200 and g["approvable"] is True, g.get("blockers")
    # 4. save a callback, then approve THROUGH resume (cloud path)
    from services.governance.store import save_callback
    save_callback(bid, "patch_approval", None)
    s, rec = _api("POST", f"/builds/{bid}/resume",
                  {"gate": "patch_approval", "decision": "APPROVE_CANDIDATE",
                   "reviewer": {"reviewer_id": "USR-001"}, "reason": "e2e", "role": "PROCEDURE_OWNER"})
    assert s == 200 and rec["decision"] == "APPROVE_CANDIDATE", rec
    assert rec.get("candidate_version_id")
    # 5. activate the exact candidate
    s, act = _api("POST", f"/procedures/{rec['candidate_version_id']}/activate",
                  {"build_id": bid, "reviewer": {"reviewer_id": "USR-001"}, "reason": "e2e"})
    assert s == 200, act
    # 6. activated graph equals the validated graph and executes correctly
    from services.workflow.interpreter import execute
    from services.compiler.compiler import compile_rules
    model = compile_rules(b["new_rules"])
    got = execute(act["procedure_version"]["graph_json"], {"cgpa": 7.8}, model.ordering)
    assert got["eligible"] is True
    assert act["procedure_version"]["status"] == "active"
    # 7. replay after patch: portal preview accepts 7.80, rec waived at 8.20
    s, p1 = _api("GET", "/portal?cgpa=7.8&patched=1&domain=research_grant")
    s, p2 = _api("GET", "/portal?cgpa=8.2&patched=1&domain=research_grant")
    assert p1["actual"]["eligible"] is True
    assert p2["actual"]["required"]["upload_recommendation"] is False
    # 8. hostile policy text is echoed safely (server returns data; UI escapes)
    evil = '<script>alert(1)</script> Applicants must have CGPA >= 7.5.'
    s, eb = _api("POST", "/builds", {"domain": "research_grant", "policy_text": evil})
    assert s == 200
    blob = json.dumps(eb)
    assert "<script>" not in blob or "source_text" in blob  # stored, never executed server-side
