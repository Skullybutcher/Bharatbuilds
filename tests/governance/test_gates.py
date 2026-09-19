import os
import pathlib
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="pp-test-gov-")
os.environ["PROCESSPATCH_DATA"] = TMP
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _build():
    import json
    from services.api.pipeline import run_build
    from services.governance.store import open_rule_reviews, review_rule
    d = ROOT / "demo" / "research_grant"
    old = json.loads((d / "rules_v1.json").read_text())
    new = json.loads((d / "rules_v2.json").read_text())
    proc = json.loads((d / "workflow_v1.json").read_text())
    b = run_build("POLICY-V2", old, new, proc)
    open_rule_reviews(b["build_id"], new)
    for r in new:
        review_rule(b["build_id"], r["rule_id"], "ACCEPT")
    return b


def test_three_gates_and_activation():
    from services.governance.store import (approval_guardrails, request_patch_review,
                                           decide_patch, activate_procedure, approvals_for)
    from services.registry.store import audit_for
    b = _build()
    assert approval_guardrails(b)["approvable"] is True
    request_patch_review(b["build_id"], reviewer_opened_hash=None)
    rec = decide_patch(b["build_id"], b, "APPROVE_CANDIDATE",
                       {"reviewer_id": "USR-001"}, "ok", "PROCEDURE_OWNER")
    assert rec["decision"] == "APPROVE_CANDIDATE"
    out = activate_procedure(b["build_id"], b, {"reviewer_id": "USR-001"}, "go")
    assert out["procedure_version"]["status"] == "active"
    assert len(approvals_for(b["build_id"])) == 2
    assert len(audit_for(b["build_id"])) >= 5


def test_reject_blocks_activation():
    from services.governance.store import decide_patch
    import pytest
    b = {"build_id": "B-X", "patch": {"operations": []},
         "validation": {"status": "FAILED", "results": []},
         "new_rules": [], "procedure": {}, "certificate": {},
         "conflicts": [], "impact": {}}
    with pytest.raises(ValueError):
        decide_patch("B-X", b, "APPROVE_CANDIDATE", {"reviewer_id": "U"}, "x", "PROCEDURE_OWNER")
