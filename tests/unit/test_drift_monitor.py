"""T70 — post-activation drift monitor.

compare_traces (build-scoped) answers "did the patch fix what traces flagged?"
before activation. drift_report is the missing half of the CI loop: AFTER a
patch activates, do runtime traces keep agreeing with the ACTIVE procedure?
A rising disagreement rate is the evidence-backed signal that reality has
moved and a new amendment should be compiled.

The shared mismatch logic is extracted into one helper so the build-scoped and
active-scoped comparisons can never drift apart — that sameness is itself
tested. Refusals fail closed: no active procedure is a 404, not an empty
happy-path report; no trace is ever auto-accepted as a witness.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services import storage  # noqa: E402
from services.api import actions  # noqa: E402
from services.traces import store as traces  # noqa: E402


@pytest.fixture()
def activated(tmp_path, monkeypatch):
    """A canonical build pushed through gate 2 + activation, so a procedure
    version is ACTIVE — the monitor's anchor."""
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    storage._FILE_VERSIONS.clear()
    actions.MEMO.clear()
    b = actions.canonical("research_grant")
    bid = b["build_id"]
    from services.governance import store as gov
    gov.request_patch_review(bid, None)
    gov.save_callback(bid, "patch_approval", "tok-t70")
    out = gov.resume_callback(bid, "patch_approval",
                              {"gate": "patch_approval", "decision": "APPROVE_CANDIDATE",
                               "role": "PROCEDURE_OWNER",
                               "reviewer": {"reviewer_id": "rev"}, "reason": "t70"})
    cand = out["candidate_version_id"]
    # Gate 3 the honest way: activate the EXACT candidate the gate minted
    gov.activate_procedure(bid, b, {"reviewer_id": "rev"}, "t70")
    return {"build": b, "candidate": cand, "workflow_id": "WF-RESEARCH-GRANT"}


def _ingest(case, eligible, occurred_at=None, wf="WF-RESEARCH-GRANT", ws=None):
    from services.traces.store import ingest_trace
    body = {"case": case, "outcome": {"eligible": eligible},
            "source": "monitor-test", "workflow_id": wf}
    if ws:
        body["workspace_id"] = ws
    if occurred_at:
        body["occurred_at"] = occurred_at
    return ingest_trace(body)


# a case the canonical graph+rules resolve deterministically: the witness list
# of the canonical build holds known-good cases — reuse the first one as AGREE
def _agree_case(build):
    return (build.get("witnesses") or [{}])[0].get("case") or \
        {"cgpa": 8.5, "amount": 0, "year": 3, "category": "general"}


def test_mismatch_helper_is_shared_by_both_comparisons():
    """The sameness guarantee: compare_traces and drift_report MUST use the
    same mismatch logic, or the pre/post halves of the loop could disagree."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                            "services", "traces", "store.py"), encoding="utf-8").read()
    assert "def _outcome_mismatches(" in src
    assert src.count("_outcome_mismatches(") >= 3  # def + both call sites
    assert "unmodeled_action" in src.split("def _outcome_mismatches")[1].split("def ")[0]


def test_no_active_procedure_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    storage._FILE_VERSIONS.clear()
    with pytest.raises(KeyError):
        actions.drift_report("WF-RESEARCH-GRANT")
    with pytest.raises(KeyError):
        traces.drift_report("WF-RESEARCH-GRANT")


def test_agreeing_traces_give_rate_zero(activated):
    b = activated["build"]
    _ingest(_agree_case(b), True, occurred_at=time.time())
    rep = traces.drift_report("WF-RESEARCH-GRANT")
    assert rep["kind"] == "processpatch-drift-report"
    assert rep["evaluated"] == 1 and rep["disagree"] == 0
    assert rep["disagreement_rate"] == 0.0
    assert rep["procedure_version_id"] == activated["candidate"]
    assert rep["results"][0]["status"] == "AGREE"


def test_disagreeing_traces_are_named_not_accepted(activated):
    """A drifted trace shows up as DISAGREE with the mismatch named — and is
    still only a signal (honesty note), never a witness or a change."""
    b = activated["build"]
    # reality moved: the same case the active graph approves now records a
    # rejection in the field
    _ingest(_agree_case(b), False, occurred_at=time.time())
    _ingest(_agree_case(b), True, occurred_at=time.time() + 1)
    rep = actions.drift_report("WF-RESEARCH-GRANT")
    assert rep["evaluated"] == 2 and rep["disagree"] == 1
    assert rep["disagreement_rate"] == 0.5
    drifts = [r for r in rep["results"] if r["status"] == "DISAGREE"]
    assert len(drifts) == 1 and drifts[0]["trace_id"] in rep["disagree_trace_ids"]
    assert drifts[0]["mismatches"], "the drifted dimension must be named"
    assert drifts[0]["mismatches"][0].startswith("eligible")
    assert "never" in rep["honesty_note"] or "evidence only" in rep["honesty_note"]


def test_workspace_scoping_and_default_workflow(activated):
    """The console path: GET /drift with no parameters resolves the active
    procedure's own workflow; traces from other workspaces don't count."""
    b = activated["build"]
    _ingest(_agree_case(b), True, occurred_at=time.time(), ws="default")
    _ingest(_agree_case(b), False, occurred_at=time.time(), ws="ws-other-tenant")
    rep = actions.drift_report(None, None, "default")
    assert rep["workflow_id"] == "WF-RESEARCH-GRANT"
    assert rep["evaluated"] == 1 and rep["disagree"] == 0


def test_invalid_cases_are_skipped_and_counted(activated):
    b = activated["build"]
    from services.traces.store import ingest_trace
    # a case missing required fields still ingests (traces are evidence) but
    # the interpreter can't evaluate it — SKIPPED, never silently dropped
    _ingest({"nonsense": True}, True, occurred_at=time.time())
    _ingest(_agree_case(b), True, occurred_at=time.time() + 1)
    rep = traces.drift_report("WF-RESEARCH-GRANT")
    assert rep["checked"] == 2
    assert rep["evaluated"] + sum(1 for r in rep["results"] if r["status"] == "SKIPPED") \
        == rep["checked"]
