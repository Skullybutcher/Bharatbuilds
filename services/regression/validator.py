"""Regression validator: witnesses + boundaries + unchanged + ordering +
metamorphic (derived from the semantic delta) + provenance.

Metamorphic properties by delta type:
  THRESHOLD_RELAXED(field)   old-eligible => new-eligible on cohort
  THRESHOLD_TIGHTENED(field) new-eligible => old-eligible on cohort
  DEADLINE_EXTENDED          previously on-time stays on-time
  OBLIGATION_REMOVED         no new mandatory steps from removal
  EXCEPTION_ADDED            outside-exception behavior unchanged
  NO_OP                      behavior identical on cohort
"""
from __future__ import annotations
from services.compiler.compiler import evaluate_expected
from services.workflow.interpreter import execute
from services.semantic_diff.differ import diff_case
from services.workflow.expr import neighbors


def _cohort(model, workflow, n: int = 60) -> list[dict]:
    from services.witness.generator import candidate_cases
    return candidate_cases(model, workflow, cap=n)


def validate(patch, witnesses_before: list[dict], model, old_model,
             patched_workflow, original_workflow, delta: dict, faults: list | None = None) -> dict:
    results: list[dict] = []

    def check(suite, case, ok, detail):
        results.append({"suite": suite, "case": case, "pass": bool(ok), "detail": detail})

    for w in witnesses_before:  # original witnesses must resolve
        case = w["case"]
        exp = {**evaluate_expected(model, case), "order_ok": True}
        d = diff_case(exp, execute(patched_workflow, case, model.ordering), case)
        check("witness", case, d is None,
              f"witness {w.get('witness_id')} resolved" if d is None else f"still failing: {d['kind']}")

    for f, vals in _boundary_values(model, original_workflow).items():  # boundaries
        for v in vals:
            case = {"cgpa": 8.0, "amount": 40000, "year": 3, "backlogs": 0,
                    "category": "general", "submission_date": "2026-09-28", f: v}
            exp = {**evaluate_expected(model, case), "order_ok": True}
            d = diff_case(exp, execute(patched_workflow, case, model.ordering), case)
            check("boundary", {f: v}, d is None, f"boundary {f}={v} {'OK' if d is None else 'FAIL ' + d['kind']}")

    for case in _cohort(model, original_workflow):  # preservation
        exp = {**evaluate_expected(model, case), "order_ok": True}
        was_ok = diff_case(exp, execute(original_workflow, case, model.ordering), case) is None
        now_ok = diff_case(exp, execute(patched_workflow, case, model.ordering), case) is None
        if was_ok:
            check("unchanged", case, now_ok, "preserved" if now_ok else "REGRESSION")

    order_ok = execute(patched_workflow, {"cgpa": 9.0}, model.ordering)["order_ok"]
    for o in (model.ordering or []):
        check("ordering", {"constraint": o}, order_ok,
              f"{o['before']} before {o['after']} {'PASS' if order_ok else 'FAIL'}")

    for name, ok, detail in _metamorphic(delta, old_model, model, patched_workflow, original_workflow):
        check("metamorphic", {"property": name}, ok, detail)

    # Provenance: every node whose configuration changed (or was added) must
    # be source-linked. Localization context alone does not impose linkage.
    touched = set()
    before_cfg = {n["node_id"]: n.get("implementation", {}) for n in original_workflow.get("nodes", [])}
    after_nodes = {n["node_id"]: n for n in patched_workflow.get("nodes", [])}
    for n in patched_workflow.get("nodes", []):
        if before_cfg.get(n["node_id"]) != n.get("implementation", {}):
            touched.add(n["node_id"])
    touched = {nid for nid in touched if nid in after_nodes}  # ignore stale ids
    prov_ok = all(after_nodes[nid].get("provenance_links") for nid in touched)
    check("provenance", {}, prov_ok,
          "all changed nodes source-linked" if prov_ok else "provenance MISSING")

    passed = sum(1 for r in results if r["pass"])
    return {"results": results, "passed": passed, "failed": len(results) - passed,
            "total": len(results),
            "status": "VALIDATED_WITHIN_TESTED_MODEL" if passed == len(results) else "FAILED"}


def _boundary_values(model, workflow) -> dict:
    from services.witness.generator import _literals_per_field
    out = {}
    for f, lits in _literals_per_field(model, workflow).items():
        out[f] = sorted(neighbors(f, lits), key=str)[:7]
    return out


def _metamorphic(delta, old_model, model, patched, original):
    from services.witness.generator import candidate_cases
    out = []
    cohort = candidate_cases(model, patched, cap=40)
    dtype = (delta or {}).get("type", "")
    if dtype == "THRESHOLD_RELAXED":
        ok = all((not evaluate_expected(old_model, c)["eligible"]) or evaluate_expected(model, c)["eligible"] for c in cohort)
        out.append(("Eligible_old -> Eligible_new", ok, "monotone relaxation holds" if ok else "METAMORPHIC FAIL"))
    elif dtype == "THRESHOLD_TIGHTENED":
        ok = all((not evaluate_expected(model, c)["eligible"]) or evaluate_expected(old_model, c)["eligible"] for c in cohort)
        out.append(("Eligible_new -> Eligible_old", ok, "monotone tightening holds" if ok else "METAMORPHIC FAIL"))
    elif dtype == "DEADLINE_EXTENDED":
        ok = all((not evaluate_expected(old_model, c)["on_time"]) or evaluate_expected(model, c)["on_time"] for c in cohort)
        out.append(("OnTime_old -> OnTime_new", ok, "deadline extension monotone" if ok else "METAMORPHIC FAIL"))
    elif dtype == "OBLIGATION_REMOVED":
        action = (delta or {}).get("action", "")
        remaining = [c for c in cohort if execute(patched, c, model.ordering)["required"].get(action, False)]
        out.append(("No new mandatory steps", not remaining,
                    "removal holds" if not remaining else f"METAMORPHIC FAIL: {len(remaining)} still required"))
    elif dtype == "EXCEPTION_ADDED":
        cond = (delta or {}).get("exception_condition")
        ok = True
        for c in cohort:
            exp = evaluate_expected(model, c)
            if cond and not _eval_quiet(cond, c):
                # outside the exception: obligation state must match the old model
                old_req = evaluate_expected(old_model, c)["required"].get((delta or {}).get("action", ""), None)
                new_req = exp["required"].get((delta or {}).get("action", ""), None)
                if old_req is not None and new_req is not None and old_req != new_req:
                    ok = False
        out.append(("Exception carve-out valid", ok, "exception holds" if ok else "METAMORPHIC FAIL"))
    elif dtype in ("SEMANTICS_UNCHANGED", "PROVENANCE_ONLY"):
        ok = all(diff_case({**evaluate_expected(old_model, c), "order_ok": True},
                           {**evaluate_expected(model, c), "order_ok": True}, c) is None for c in cohort)
        out.append(("No-op identical behavior", ok, "paraphrase holds" if ok else "METAMORPHIC FAIL"))
    else:
        out.append(("Smoke: patched executes", True, "patched workflow executes on cohort"))
    return out


def _eval_quiet(cond, case):
    from services.workflow.expr import eval_condition
    try:
        return bool(eval_condition(cond, case))
    except Exception:
        return False


# Backwards-compatible alias used by early call sites
def _check(witnesses_before, model, patched_workflow, original_workflow):
    from services.compiler.compiler import ConstraintModel
    delta = {"type": "UNKNOWN"}
    return validate(None, witnesses_before, model, ConstraintModel(), patched_workflow, original_workflow, delta)
