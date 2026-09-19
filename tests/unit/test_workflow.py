import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.workflow.interpreter import execute, validate_dag


def _wf(nodes, edges):
    return {"workflow_id": "W", "procedure_version_id": "V1", "nodes": nodes, "edges": edges}


def _n(nid, label="N", impl=None):
    return {"node_id": nid, "workflow_id": "W", "type": "action", "label": label,
            "preconditions": [], "postconditions": [], "implementation": impl or {},
            "provenance_links": []}


def test_branch_skip_shortens_journey():
    wf = _wf(
        [_n("START", impl={}), _n("GATE", impl={"kind": "threshold_gate", "field": "cgpa", "operator": ">=", "value": 7.5}),
         _n("REC", impl={"form_field": "rec", "action": "rec", "required": True,
                         "required_condition": {"field": "cgpa", "operator": "<", "value": 8.0}}),
         _n("SUB", impl={"action": "submit"})],
        [{"from": "START", "to": "GATE", "type": "NEXT", "condition": None},
         {"from": "GATE", "to": "REC", "type": "NEXT", "condition": None},
         {"from": "REC", "to": "SUB", "type": "NEXT", "condition": None}])
    lo = execute(wf, {"cgpa": 7.6}, [])
    hi = execute(wf, {"cgpa": 8.5}, [])
    assert "REC" in lo["path"] and "REC" not in hi["path"]
    assert len(hi["path"]) < len(lo["path"])
    assert hi["required"].get("rec", False) is False


def test_gate_reject_is_terminal():
    wf = _wf(
        [_n("START", impl={}), _n("GATE", impl={"kind": "threshold_gate", "field": "cgpa", "operator": ">=", "value": 8.0}),
         _n("SUB", impl={"action": "submit"})],
        [{"from": "START", "to": "GATE", "type": "NEXT", "condition": None},
         {"from": "GATE", "to": "SUB", "type": "NEXT", "condition": None}])
    out = execute(wf, {"cgpa": 7.0}, [])
    assert out["eligible"] is False
    assert "SUB" not in out["path"]


def test_branch_edges_follow_conditions():
    wf = _wf(
        [_n("START", impl={}), _n("A", impl={}), _n("B", impl={}), _n("SUB", impl={"action": "submit"})],
        [{"from": "START", "to": "A", "type": "BRANCH", "condition": {"field": "x", "operator": ">", "value": 5}},
         {"from": "START", "to": "B", "type": "BRANCH", "condition": {"field": "x", "operator": "<=", "value": 5}},
         {"from": "A", "to": "SUB", "type": "NEXT", "condition": None},
         {"from": "B", "to": "SUB", "type": "NEXT", "condition": None}])
    assert execute(wf, {"x": 9}, [])["path"] == ["START", "A", "SUB"]
    assert execute(wf, {"x": 1}, [])["path"] == ["START", "B", "SUB"]


def test_cycle_rejected_not_tolerated():
    wf = _wf([_n("A", impl={}), _n("B", impl={})],
             [{"from": "A", "to": "B", "type": "NEXT", "condition": None},
              {"from": "B", "to": "A", "type": "NEXT", "condition": None}])
    with pytest.raises(ValueError, match="INVALID_WORKFLOW"):
        validate_dag(wf)
    with pytest.raises(ValueError, match="INVALID_WORKFLOW"):
        execute(wf, {}, [])


def test_orphan_rejected():
    wf = _wf([_n("START", impl={}), _n("LOST", impl={})],
             [])
    with pytest.raises(ValueError, match="INVALID_WORKFLOW"):
        validate_dag(wf)


def test_dangling_ref_rejected():
    wf = _wf([_n("START", impl={})],
             [{"from": "START", "to": "GHOST", "type": "NEXT", "condition": None}])
    with pytest.raises(ValueError, match="INVALID_WORKFLOW"):
        validate_dag(wf)


def test_prohibition_gate_blocks():
    wf = _wf(
        [_n("START", impl={}),
         _n("PG", impl={"kind": "prohibition_gate", "field": "amount", "operator": ">", "value": 100000}),
         _n("SUB", impl={"action": "submit"})],
        [{"from": "START", "to": "PG", "type": "NEXT", "condition": None},
         {"from": "PG", "to": "SUB", "type": "NEXT", "condition": None}])
    assert execute(wf, {"amount": 150000}, [])["prohibited"] is True
    assert "SUB" not in execute(wf, {"amount": 150000}, [])["path"]
    assert execute(wf, {"amount": 50000}, [])["prohibited"] is False


def test_all_benchmark_patches_structurally_valid():
    import json
    from services.compiler.compiler import compile_rules
    from services.witness.generator import find_witnesses
    from services.localizer.localizer import localize_all
    from services.patcher.patcher import propose
    cases = list((ROOT / "benchmark" / "processpatchbench" / "cases").iterdir())
    assert len(cases) >= 29
    for d in sorted(cases):
        if not d.is_dir():
            continue
        rules2 = json.loads((d / "rules_v2.json").read_text())
        proc = json.loads((d / "procedure.json").read_text())
        model = compile_rules(rules2)
        ws = find_witnesses(model, proc)
        p = propose(model, proc, localize_all(ws, proc, model))
        stats = validate_dag(p["patched_workflow"])
        assert stats["nodes"] >= len(proc["nodes"])
        for e in p["patched_workflow"]["edges"]:
            assert e["from"] != e["to"], f"self-loop in {d.name}"
