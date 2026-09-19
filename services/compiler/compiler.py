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


def _threshold_domain(conds: list[dict]) -> bool:
    """Interval satisfiability for one field: lower/upper bounds, equality,
    enum membership. Compatible ranges (e.g. >= 7.5 AND <= 10) are NOT
    conflicts — only an empty domain is."""
    import math
    lo, lo_inc = -math.inf, True
    hi, hi_inc = math.inf, True
    eq = None
    allowed = None
    for c in conds:
        op, v = c.get("operator"), c.get("value")
        if op in ("IN", "NOT_IN"):
            vals = set(v if isinstance(v, (list, tuple, set)) else [v])
            if op == "IN":
                allowed = vals if allowed is None else (allowed & vals)
            continue
        if op == "==":
            eq = v if eq is None else (eq if str(eq) == str(v) else "!!conflict!!")
            continue
        if op == "!=":
            continue
        try:
            f = float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            continue  # dates handled lexicographically below
        if op == ">":
            if f > lo or (f == lo and lo_inc):
                lo, lo_inc = f, False
        elif op == ">=":
            if f > lo or (f == lo and not lo_inc):
                lo, lo_inc = f, True
        elif op == "<":
            if f < hi or (f == hi and hi_inc):
                hi, hi_inc = f, False
        elif op == "<=":
            if f < hi or (f == hi and not hi_inc):
                hi, hi_inc = f, True
    if eq == "!!conflict!!":
        return False
    if eq is not None:
        try:
            f = float(str(eq).replace(",", ""))
            ok = (f > lo or (f == lo and lo_inc)) and (f < hi or (f == hi and hi_inc))
        except (TypeError, ValueError):
            ok = True
        if allowed is not None:
            ok = ok and eq in allowed
        return ok
    if lo > hi or (lo == hi and not (lo_inc and hi_inc)):
        # date strings compare lexicographically and never hit the float path
        return True if isinstance(lo, str) or isinstance(hi, str) else False
    if allowed is not None and not allowed:
        return False
    return True


def compile_rules(rules: list[dict]) -> ConstraintModel:
    active = [r for r in rules if r.get("status", "active") == "active"]
    model = ConstraintModel(source_rules=[r.get("rule_id") for r in active])

    # fail-closed: per-field constraint analysis.
    #  - one lower + one upper bound = an interval, NOT a conflict;
    #  - two DISTINCT lower bounds (or uppers, or equalities) with no
    #    precedence = ambiguous authority -> BLOCK;
    #  - an empty domain (e.g. >= 8 AND < 7.5) -> BLOCK.
    by_field: dict = {}
    for r in active:
        if r.get("kind") == "threshold" and (r.get("condition") or {}).get("field"):
            by_field.setdefault((r.get("condition") or {})["field"], []).append(r.get("condition"))
    for field, conds in by_field.items():
        lowers = {(c.get("operator"), str(c.get("value"))) for c in conds if c.get("operator") in (">", ">=")}
        uppers = {(c.get("operator"), str(c.get("value"))) for c in conds if c.get("operator") in ("<", "<=")}
        if len(lowers) > 1 or len(uppers) > 1:
            raise ValueError(
                "CONFLICT / COMPILATION BLOCKED: ambiguous authority for "
                f"{field!r} (multiple bounds, no precedence).")
        if not _threshold_domain(conds):
            raise ValueError(
                "CONFLICT / COMPILATION BLOCKED: unsatisfiable constraints for "
                f"{field!r} with no explicit precedence.")

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
