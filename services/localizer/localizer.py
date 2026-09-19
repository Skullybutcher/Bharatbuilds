"""Fault localizer: earliest expected/actual divergence -> suspect workflow region."""
from __future__ import annotations


def _gate_nodes(workflow: dict, field: str | None = None) -> list[str]:
    out = []
    for n in workflow.get("nodes", []):
        impl = n.get("implementation", {}) or {}
        if impl.get("kind") in ("threshold_gate", "deadline_gate"):
            if field is None or impl.get("field") == field:
                out.append(n["node_id"])
    return out


def _action_nodes(workflow: dict, action: str) -> list[str]:
    out = []
    for n in workflow.get("nodes", []):
        impl = n.get("implementation", {}) or {}
        act = impl.get("action") or (str(impl.get("form_field", "")).replace("_file", "") if "form_field" in impl else None)
        if act and (act == action or action in str(impl.get("form_field", ""))):
            out.append(n["node_id"])
    return out


def localize(witness: dict, workflow: dict, model=None) -> dict:
    kind, key = witness.get("kind"), witness.get("key")
    case = witness.get("case", {})
    if kind in ("wrong_rejection", "wrong_acceptance"):
        fields = [k for k in case if k in ("cgpa", "amount", "score", "gpa", "income")]
        affected = _gate_nodes(workflow, fields[0] if fields else None) or ["NODE-ELIGIBILITY"]
        ops = ["CHANGE_CONDITION"]
        expl = (f"Eligibility divergence for {case}: expected={witness.get('expected')} "
                f"actual={witness.get('actual')}. Earliest divergence: eligibility gate.")
    elif kind in ("unnecessary_burden", "missing_safeguard"):
        affected = _action_nodes(workflow, key or "")
        ops = ["CHANGE_REQUIRED_FLAG", "CHANGE_CONDITION", "ADD_GATE", "ADD_NODE"]
        if affected:
            expl = (f"Step requirement divergence for action {key!r} at {case}. "
                    f"Earliest divergence: {affected} + incoming edge.")
        else:
            ops = ["ADD_NODE"]
            expl = (f"Step requirement divergence for action {key!r} at {case}, but no "
                    f"workflow node implements it. Suspect region: missing step (ADD_NODE).")
    elif kind == "deadline_mismatch":
        affected = _gate_nodes(workflow) or [n["node_id"] for n in workflow.get("nodes", [])[:1]]
        ops = ["CHANGE_CONDITION", "ADD_NODE"]
        expl = f"Deadline divergence at {case}."
    elif kind == "prohibition_breach":
        # existing prohibition gates on the breached field, else the submit region
        affected = [n["node_id"] for n in workflow.get("nodes", [])
                    if (n.get("implementation", {}) or {}).get("kind") == "prohibition_gate"]
        ops = ["ADD_NODE", "ADD_GATE", "CHANGE_CONDITION"]
        expl = (f"Prohibition {key!r} holds at {case} but the procedure does not block it. "
                f"Earliest divergence: enforcement gate ({affected or 'missing'}).")
    else:  # wrong_journey — resolve the constrained nodes via the model
        affected = []
        if model is not None:
            from services.workflow.interpreter import _ordered_nodes, _find_node
            order = _ordered_nodes(workflow)
            for o in (model.ordering or []):
                for tok in (o.get("before"), o.get("after")):
                    hit = _find_node(order, tok)
                    if hit and hit["node_id"] not in affected:
                        affected.append(hit["node_id"])
        if not affected:
            affected = [n["node_id"] for n in workflow.get("nodes", [])
                        if (n.get("implementation", {}) or {}).get("approver") or
                        (n.get("implementation", {}) or {}).get("action") == "submit"]
        ops = ["ADD_PREREQUISITE", "MOVE_NODE", "ADD_NODE"]
        expl = "Ordering violation: prerequisite not enforced before target."
    return {"witness_id": witness.get("witness_id"), "kind": kind, "key": key,
            "affected_nodes": affected, "permitted_operations": ops,
            "explanation": expl, "expected_trace": witness.get("trace_expected", []),
            "actual_trace": witness.get("trace_actual", [])}


def localize_all(witnesses: list[dict], workflow: dict, model=None) -> list[dict]:
    return [localize(w, workflow, model) for w in witnesses]
