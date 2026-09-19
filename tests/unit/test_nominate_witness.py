"""Witness nomination from runtime traces (T15) — human suggests, the
verified pipeline disposes.

Covers: agreeing traces are refused (honesty gate); a trace whose case the
pipeline already covers yields verified=False (no duplicate witnesses); a
nominated case the pipeline does NOT yet cover is verified through
find_witnesses + the regression validator and added; every nomination is
audited; unknown traces 404.
"""
import os
import pathlib
import sys
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="pp-test-nom-")
os.environ["PROCESSPATCH_DATA"] = TMP
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _build():
    import services.api.actions as A
    b = A.canonical("research_grant")
    return b


def _ingest_case(case, eligible=True, source="trace-test"):
    from services.traces.store import ingest_trace
    return ingest_trace({"case": case,
                         "outcome": {"eligible": eligible, "on_time": True},
                         "source": source})


def test_refuses_trace_that_agrees_with_stale():
    import services.api.actions as A
    b = _build()
    stale = A.compare_traces(b["build_id"])
    agree = next((r["trace_id"] for r in stale["results"]
                  if r.get("vs_stale", {}).get("status") == "AGREE"), None)
    if agree is None:  # ingest a case both graphs handle identically
        from services.compiler.compiler import compile_rules, evaluate_expected
        from services.workflow.interpreter import execute
        model = compile_rules(b["new_rules"])
        case = {"cgpa": 9.9, "amount": 1000, "year": 1, "backlogs": 0,
                "category": "general", "submission_date": "2026-09-01"}
        ok = (evaluate_expected(model, case).get("eligible")
              == execute(b["procedure"], case, model.ordering).get("eligible"))
        assert ok, "test needs a case both graphs agree on"
        agree = _ingest_case(case)["trace_id"]
    with pytest.raises(ValueError, match="nothing to nominate"):
        A.nominate_witness(b["build_id"], {"trace_id": agree})


def test_nomination_requires_honest_disagreement_or_full_coverage():
    """A disagreeing trace either adds a verified witness or is reported as
    already-covered by the pipeline — never silently dropped."""
    import services.api.actions as A
    b = _build()
    stale = A.compare_traces(b["build_id"])
    cand = next((r["trace_id"] for r in stale["results"]
                 if r.get("vs_stale", {}).get("status") == "DISAGREE"), None)
    if cand is None:  # ingest a case that breaks against the stale graph
        case = {"cgpa": 5.0, "amount": 99999, "year": 2, "backlogs": 3,
                "category": "obc", "submission_date": "2026-10-01"}
        from services.traces.store import ingest_trace
        ingest_trace({"case": case, "outcome": {"eligible": True, "on_time": True},
                      "source": "trace-test"})
        stale = A.compare_traces(b["build_id"])
        cand = next((r["trace_id"] for r in stale["results"]
                     if r.get("vs_stale", {}).get("status") == "DISAGREE"), None)
    assert cand, "fixture must produce at least one disagreeing trace"
    out = A.nominate_witness(b["build_id"], {"trace_id": cand,
                                             "reviewer": {"reviewer_id": "USR-002"}})
    assert out["nominated"] is True
    assert out["verified"] in (True, False)
    if out["verified"]:
        assert out["witness"]["verified"] is True
        assert out["witness"]["witness_id"] not in [
            w["witness_id"] for w in b.get("witnesses", [])]
        assert out["validation"]["results"], "validation re-run included"
    else:
        assert "already covers" in out["reason"]


def test_nomination_is_audited():
    from services.registry.store import audit_for
    import services.api.actions as A
    b = _build()
    stale = A.compare_traces(b["build_id"])
    cand = next((r["trace_id"] for r in stale["results"]
                 if r.get("vs_stale", {}).get("status") == "DISAGREE"), None)
    if not cand:
        pytest.skip("no disagreeing trace available in this fixture")
    try:
        A.nominate_witness(b["build_id"], {"trace_id": cand,
                                           "reviewer": {"reviewer_id": "USR-002"}})
    except ValueError:
        pass
    events = [e["event"] for e in audit_for(b["build_id"])]
    assert "WITNESS_NOMINATED" in events


def test_unknown_trace_is_404():
    import services.api.actions as A
    b = _build()
    with pytest.raises(KeyError):
        A.nominate_witness(b["build_id"], {"trace_id": "TR-NOPE"})
