"""Multi-procedure workspaces: create workspace, register any procedure,
build against it by procedure_version_id. INVALID_WORKFLOW fails closed.
"""
from __future__ import annotations

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

from services.api import actions
from services.storage import _save


def _setup():
    for f in ("workspaces.json", "procedure_versions.json", "builds.json"):
        _save(f, [] if f != "builds.json" else {})


def _grant_graph(wid="WF-CUSTOM", pid="WF-CUSTOM-V1", threshold=8.0):
    return {
        "workflow_id": wid, "procedure_version_id": pid, "version_label": pid,
        "nodes": [
            {"node_id": "NODE-START", "workflow_id": wid, "type": "start", "label": "Start",
             "preconditions": [], "postconditions": [], "implementation": {}, "provenance_links": []},
            {"node_id": "NODE-GATE", "workflow_id": wid, "type": "gate", "label": "Check cgpa",
             "preconditions": [], "postconditions": [],
             "implementation": {"kind": "threshold_gate", "field": "cgpa", "operator": ">=", "value": threshold},
             "provenance_links": []},
            {"node_id": "NODE-SUBMIT", "workflow_id": wid, "type": "action", "label": "Submit",
             "preconditions": [], "postconditions": [], "implementation": {"action": "submit"},
             "provenance_links": []},
        ],
        "edges": [
            {"from": "NODE-START", "to": "NODE-GATE", "type": "NEXT", "condition": None},
            {"from": "NODE-GATE", "to": "NODE-SUBMIT", "type": "NEXT", "condition": None},
        ],
    }


def test_workspace_create_and_list():
    _setup()
    rec = actions.create_workspace({"name": "Fellowships 2027"})
    assert rec["workspace_id"] and rec["name"] == "Fellowships 2027"
    assert any(w["workspace_id"] == rec["workspace_id"] for w in actions.list_workspaces()["workspaces"])
    with pytest.raises(ValueError):
        actions.create_workspace({"name": "  "})


def test_register_procedure_validates_dag():
    _setup()
    good = actions.register_procedure({"procedure": _grant_graph()})
    assert good["procedure_version_id"] == "WF-CUSTOM-V1"
    assert good["status"] == "active"
    broken = _grant_graph(wid="WF-BAD", pid="WF-BAD-V1")
    broken["edges"] = []  # 3 start nodes -> INVALID_WORKFLOW
    with pytest.raises(ValueError) as e:
        actions.register_procedure({"procedure": broken})
    assert "INVALID_WORKFLOW" in str(e.value)


def test_register_procedure_rejects_duplicate_version_id():
    _setup()
    actions.register_procedure({"procedure": _grant_graph()})
    with pytest.raises(ValueError):
        actions.register_procedure({"procedure": _grant_graph(threshold=7.0)})


def test_build_against_registered_procedure():
    _setup()
    actions.register_procedure({"procedure": _grant_graph(pid="WF-CUSTOM-V2", threshold=7.5)})
    rules = [{"rule_id": "R-ELIG-2", "kind": "threshold", "subject": "applicant", "action": "eligible",
              "condition": {"field": "cgpa", "operator": ">=", "value": 7.0, "datatype": "decimal"},
              "normalized_expression": "cgpa >= 7.0", "effective_from": "2026-09-18",
              "effective_to": None, "status": "active", "supersedes": None,
              "provenance": {"policy_version_id": "PV", "document_sha256": "t", "page": None,
                             "section": "1", "source_text": "cgpa >= 7.0"},
              "extraction": {"model": "gold", "confidence": 1.0, "review_state": "accepted"}}]
    build = actions.create_build({"procedure_version_id": "WF-CUSTOM-V2", "old_rules": rules,
                                  "new_rules": rules, "policy_version_id": "POLICY-CUSTOM"})
    assert build["build_id"]
    # The stale graph gate is 7.5; the model says 7.0 -> drift is detected.
    assert build.get("witnesses"), "expected a witness for the 7.0-vs-7.5 mismatch"
    kinds = {w["kind"] for w in build["witnesses"]}
    assert "wrong_rejection" in kinds


def test_build_unknown_procedure_version_404():
    _setup()
    with pytest.raises(KeyError):
        actions.create_build({"procedure_version_id": "WF-DOES-NOT-EXIST"})
