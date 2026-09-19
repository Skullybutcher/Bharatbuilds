"""Runtime trace ingestion + read-only comparison (docs/traces.md).

Doctrine under test: traces are evidence only. Ingestion validates + stores;
comparison replays deterministically and reports agreement; nothing here can
mint a verified witness or mutate procedure versions.
"""
from __future__ import annotations

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

from services.traces import store as traces


def _demo(domain="research_grant"):
    d = ROOT / "demo" / domain
    return (json.loads((d / "rules_v1.json").read_text()),
            json.loads((d / "rules_v2.json").read_text()),
            json.loads((d / "workflow_v1.json").read_text()))


def _build():
    from services.api.pipeline import run_build
    old, new, proc = _demo()
    return run_build("POLICY-TRACE-TEST", old, new, proc)


def _canonical_build():
    """Reset local trace storage so tests are order-independent."""
    from services.storage import _save
    _save("traces.json", [])
    return _build()


def test_ingest_roundtrip_and_idempotency():
    traces._save("traces.json", [])
    body = {"case": {"cgpa": 7.8, "year": 3, "backlogs": 0, "category": "general",
                     "submission_date": "2026-09-28"},
            "outcome": {"eligible": True, "on_time": True},
            "steps_done": ["submit_form", "upload_thesis"],
            "source": "runtime-log", "workflow_id": "WF-TEST"}
    rec = traces.ingest_trace(body)
    assert rec["trace_id"].startswith("TRC-")
    assert traces.get_trace(rec["trace_id"])["source"] == "runtime-log"
    again = traces.ingest_trace(body)  # idempotent: same case/outcome => same id
    assert again["trace_id"] == rec["trace_id"]
    assert len(traces.list_traces()) == 1
    assert traces.list_traces(workflow_id="WF-TEST") and not traces.list_traces(workflow_id="WF-OTHER")


def test_outcome_coercion_and_rejection():
    traces._save("traces.json", [])
    case = {"cgpa": 7.8, "year": 3, "backlogs": 0, "category": "general",
            "submission_date": "2026-09-28"}
    rec = traces.ingest_trace({"case": case, "outcome": {"eligible": "ELIGIBLE", "on_time": "late"}})
    assert rec["outcome"]["eligible"] is True and rec["outcome"]["on_time"] is False
    rec = traces.ingest_trace({"case": case, "outcome": {"required": ["rec_file"]}})
    assert rec["outcome"]["required"] == {"rec_file": True}
    with pytest.raises(ValueError):
        traces.ingest_trace({"case": {}, "outcome": {"eligible": True}})
    with pytest.raises(ValueError):
        traces.ingest_trace({"case": {"cgpa": 7.8}, "outcome": {}})
    with pytest.raises(ValueError):
        traces.ingest_trace({"case": {"cgpa": 7.8}, "outcome": {"eligible": "maybe"}})
    with pytest.raises(ValueError):
        traces.ingest_trace({"case": {"cgpa": {"nested": 1}}, "outcome": {"eligible": True}})


def test_compare_disagrees_with_stale_agrees_with_patched():
    build = _canonical_build()
    # Witness-style case: policy says eligible; the STALE portal rejects it.
    rec = traces.ingest_trace({
        "case": {"cgpa": 7.8, "amount": 0, "year": 3, "backlogs": 0, "category": "general",
                 "submission_date": "2026-09-28"},
        "outcome": {"eligible": True}, "source": "incident-export"})
    out = traces.compare_traces(build)
    assert out["checked"] >= 1
    assert rec["trace_id"] in out["disagree_trace_ids"]
    r = next(x for x in out["results"] if x["trace_id"] == rec["trace_id"])
    assert r["vs_stale"]["status"] == "DISAGREE" and "eligible" in r["vs_stale"]["mismatches"]
    assert r["vs_patched"]["status"] == "AGREE"
    assert "candidate witness" in r["note"]
    assert "evidence only" in out["honesty_note"]


def test_compare_agrees_with_stale_disagrees_with_patched():
    build = _canonical_build()
    rec = traces.ingest_trace({
        "case": {"cgpa": 7.8, "amount": 0, "year": 3, "backlogs": 0, "category": "general",
                 "submission_date": "2026-09-28"},
        "outcome": {"eligible": False}, "source": "runtime-log"})
    out = traces.compare_traces(build)
    r = next(x for x in out["results"] if x["trace_id"] == rec["trace_id"])
    assert r["vs_stale"]["status"] == "AGREE"
    assert r["vs_patched"]["status"] == "DISAGREE"
    assert rec["trace_id"] not in out["disagree_trace_ids"]  # stale-side disagreement is the metric


def test_compare_skips_invalid_workflows_never_swallowed():
    from services.storage import _save
    _save("traces.json", [])
    old, new, _proc = _demo()
    broken = {"nodes": [], "edges": []}  # INVALID_WORKFLOW: no start node
    build = _build()
    build["procedure"] = broken
    build["patched_workflow"] = broken
    traces.ingest_trace({"case": {"cgpa": 7.8}, "outcome": {"eligible": True}})
    out = traces.compare_traces(build)
    assert out["results"] and all(r["status"] == "SKIPPED" for r in out["results"])
    assert "INVALID_WORKFLOW" in out["results"][0]["detail"]


def test_traces_exposed_over_api(monkeypatch):
    from services.api import actions
    from services.storage import _save
    _save("traces.json", [])
    build = actions.create_build({"domain": "research_grant"})
    rec = actions.ingest_trace({"case": {"cgpa": 7.8, "amount": 0, "year": 3, "backlogs": 0,
                                         "category": "general", "submission_date": "2026-09-28"},
                                "outcome": {"eligible": True}, "source": "api-test"})
    assert actions.get_trace(rec["trace_id"])["trace_id"] == rec["trace_id"]
    assert len(actions.list_traces()["traces"]) == 1
    cmp = actions.compare_traces(build["build_id"])
    assert cmp["checked"] == 1 and cmp["disagree"] == 1
