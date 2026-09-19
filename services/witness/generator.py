"""Witness generator: deterministic E(x) XOR A(x) search over the supported fragment.

Strategy: collect literals per field from the expected model AND the actual
workflow config, build boundary candidates ({lit-eps, lit, lit+eps}, dates
±1 day, enum values), then take a bounded cartesian product in sorted order.
No randomness, no LLM — mirrors SMT XOR search; deterministic given semantics.
"""
from __future__ import annotations
import itertools
from services.compiler.compiler import evaluate_expected
from services.workflow.interpreter import execute
from services.workflow.expr import iter_comparisons, neighbors, is_date_literal
from services.semantic_diff.differ import diff_case

LABELS = {
    "wrong_rejection": "Who gets the wrong outcome? Wrongfully rejected.",
    "wrong_acceptance": "Who gets the wrong outcome? Wrongfully accepted.",
    "unnecessary_burden": "Who faces an obsolete step? Unnecessary burden.",
    "missing_safeguard": "Who misses a required safeguard? Missing safeguard.",
    "wrong_journey": "Whose journey violates ordering? Wrong journey.",
    "deadline_mismatch": "Whose submission timing disagrees? Deadline mismatch.",
    "prohibition_breach": "Who bypasses a prohibition? Missing safeguard.",
}

DEFAULTS = {"cgpa": [7.8, 8.2], "amount": [40000, 60000], "year": [3],
            "backlogs": [0], "category": ["general"],
            "submission_date": ["2026-09-28"]}


def _literals_per_field(model, workflow) -> dict:
    lits: dict[str, set] = {}
    def add(field, value):
        lits.setdefault(field, set()).add(value() if callable(value) else value)
    for c in model.eligibility:
        for leaf in iter_comparisons(c):
            add(leaf["field"], leaf["value"])
    for a, o in model.obligations.items():
        for leaf in iter_comparisons(o.get("condition")):
            add(leaf["field"], leaf["value"])
    for e in model.exceptions:
        for leaf in iter_comparisons(e.get("condition")):
            add(leaf["field"], leaf["value"])
    for d in model.deadlines:
        add(d["field"], d["value"])
    for p in model.prohibitions:
        for leaf in iter_comparisons(p.get("condition")):
            add(leaf["field"], leaf["value"])
    for n in workflow.get("nodes", []):
        impl = n.get("implementation", {}) or {}
        if impl.get("field") and impl.get("value") is not None:
            add(impl["field"], impl["value"])
        for leaf in iter_comparisons(impl.get("required_condition")):
            add(leaf["field"], leaf["value"])
    return lits


def candidate_cases(model, workflow, extra_cases: list[dict] | None = None,
                    cap: int = 4000) -> list[dict]:
    lits = _literals_per_field(model, workflow)
    fields = sorted(lits)
    per_field: dict[str, list] = {}
    for f in fields:
        cands = neighbors(f, lits[f])
        for d in DEFAULTS.get(f, []):
            cands.add(d)
        per_field[f] = sorted(cands, key=str)
    if not per_field:
        per_field = {"cgpa": [7.8, 8.2]}
    combos = list(itertools.product(*[per_field[f] for f in fields]))[:cap]
    cases = [dict(zip(fields, c)) for c in combos]
    # baseline defaults merged in so unspecified fields still exist
    base = {"year": 3, "backlogs": 0, "category": "general"}
    out = [{**base, **c} for c in cases]
    if extra_cases:
        out.extend(extra_cases)
    return out


def find_witnesses(model, workflow, extra_cases=None, cap=4000) -> list[dict]:
    witnesses, seen, wid = [], set(), 0
    for case in candidate_cases(model, workflow, extra_cases, cap):
        expected = evaluate_expected(model, case)
        actual = execute(workflow, case, model.ordering)
        d = diff_case(expected, actual, case)
        if d:
            # Minimal witness set: one representative per (kind, key). Boundary
            # and cohort coverage is provided by the regression validator.
            key = (d["kind"], d.get("key"))
            if key in seen:
                continue
            seen.add(key)
            wid += 1
            d.update({"witness_id": f"W-{wid:03d}", "label": LABELS.get(d["kind"], d["kind"]),
                      "verified": True})
            witnesses.append(d)
    return witnesses
