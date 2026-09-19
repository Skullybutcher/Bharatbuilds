"""Constraint compiler: Rule IR -> ConstraintModel (deterministic, no LLM).

Model (generic across domains):
  eligibility:  list[condition]      all must hold  (AND)
  obligations:  {action: {mode, condition, rule_id}}
                mode: always_true | always_false | conditional
  exceptions:   [{action, condition, rule_id}]   waive matching obligation
  prohibitions: [{condition, rule_id, expr}]
  ordering:     [{before, after, rule_id}]
  deadlines:    [{field, operator, value, rule_id}]  on_time check
  source_rules: [rule_id]
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
from services.workflow.expr import eval_condition


@dataclass
class ConstraintModel:
    eligibility: list = field(default_factory=list)
    obligations: dict = field(default_factory=dict)
    exceptions: list = field(default_factory=list)
    prohibitions: list = field(default_factory=list)
    ordering: list = field(default_factory=list)
    deadlines: list = field(default_factory=list)
    source_rules: list = field(default_factory=list)


def compile_rules(rules: list[dict]) -> ConstraintModel:
    active = [r for r in rules if r.get("status", "active") == "active"]
    model = ConstraintModel(source_rules=[r.get("rule_id") for r in active])

    # fail-closed: contradictory active thresholds, same field, no precedence
    seen: dict = {}
    for r in active:
        if r.get("kind") == "threshold":
            c = r.get("condition") or {}
            key = c.get("field")
            sig = (c.get("operator"), c.get("value"))
            if key in seen and seen[key] != sig:
                raise ValueError(
                    "CONFLICT / COMPILATION BLOCKED: contradictory thresholds for "
                    f"{key!r} with no explicit precedence.")
            seen[key] = sig

    for r in active:
        kind, rid = r.get("kind"), r.get("rule_id")
        cond = r.get("condition")
        if kind == "threshold":
            if r.get("action") == "eligible" or not r.get("action"):
                model.eligibility.append({**cond, "_rule": rid})
            else:
                model.eligibility.append({**cond, "_rule": rid})
        elif kind == "obligation":
            model.obligations[r.get("action")] = {"mode": "always_true", "condition": None, "rule_id": rid}
        elif kind == "conditional_obligation":
            if not cond:
                raise ValueError(f"UNCOMPILABLE / NEEDS_REVIEW: {rid} missing condition")
            model.obligations[r.get("action")] = {"mode": "conditional", "condition": dict(cond), "rule_id": rid}
        elif kind == "exception":
            model.exceptions.append({"action": r.get("action"), "condition": cond, "rule_id": rid})
        elif kind == "prohibition":
            model.prohibitions.append({"condition": cond, "rule_id": rid, "expr": r.get("normalized_expression")})
        elif kind == "prerequisite":
            c = cond or {}
            model.ordering.append({"before": c.get("prerequisite"), "after": c.get("target"),
                                   "rule_id": rid, "relation": c.get("relation", "BEFORE")})
        elif kind == "deadline":
            c = cond or {}
            model.deadlines.append({"field": c.get("field", "submission_date"),
                                    "operator": c.get("operator", "<="),
                                    "value": c.get("value"), "rule_id": rid})
    return model


def model_to_dict(m: ConstraintModel) -> dict:
    return asdict(m)


def required_for(oblig: dict | None, exceptions: list, action: str, case: dict) -> bool:
    if oblig is None:
        return False
    mode = oblig.get("mode", "always_false")
    need = mode == "always_true" or (mode == "conditional" and eval_condition(oblig.get("condition"), case))
    if need:
        for e in exceptions:
            if e.get("action") in (action, "*", None) and eval_condition(e.get("condition"), case):
                return False
    return bool(need)


def evaluate_expected(model: ConstraintModel, case: dict) -> dict:
    eligible = all(eval_condition({k: v for k, v in c.items() if not k.startswith("_")}, case)
                   for c in model.eligibility)
    required = {a: required_for(o, model.exceptions, a, case) for a, o in model.obligations.items()}
    on_time = all(eval_condition(d, case) for d in
                  [{"field": d["field"], "operator": d["operator"], "value": d["value"]} for d in model.deadlines])
    violated = [p["rule_id"] for p in model.prohibitions
                if eval_condition(p.get("condition"), case)]
    trace = [f"eligibility -> {eligible}",
             f"required -> {required}",
             f"on_time -> {on_time}"]
    return {"eligible": bool(eligible), "required": required, "order_ok": True,
            "on_time": bool(on_time), "prohibitions_violated": violated, "trace": trace}
