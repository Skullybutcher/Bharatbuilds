"""Impact engine (Spec 57A): evidence-backed `impact_summary` per build.

Every number derives from build artifacts (rule delta, witnesses, workflow
nodes, validation results, cohort replay) — never from model estimation.
Metric provenance is documented in docs/impact-dashboard.md.
"""
from __future__ import annotations
from services.compiler.compiler import evaluate_expected
from services.workflow.interpreter import execute
from services.semantic_diff.differ import diff_case
from services.provenance.provenance import coverage as prov_coverage


GRID_DEFAULTS = {
    "cgpa": [5.0, 6.0, 7.0, 7.4, 7.6, 7.8, 8.0, 8.5, 9.0, 10.0],
    "score": [70, 74, 75, 78, 80, 85, 90],
    "amount": [10000, 25000, 40000, 50000, 60000, 75000, 100000, 150000],
    "income": [30000, 40000, 50000, 60000, 80000],
    "year": [2, 3, 4],
    "backlogs": [0, 1, 2],
    "category": ["general", "X", "STAFF"],
    "submission_date": ["2026-09-20", "2026-09-25", "2026-09-28", "2026-09-30", "2026-10-01"],
}


def synthetic_cohort(model, workflow, size: int = 100) -> list[dict]:
    """Deterministic scenario cohort (labeled as generated — never population).

    Boundary candidates first (witness-adjacent), then a fixed domain grid.
    """
    from services.witness.generator import candidate_cases
    import itertools
    boundary = candidate_cases(model, workflow, cap=size)
    seen = {str(sorted(c.items())) for c in boundary}
    lits: dict[str, set] = {}
    fields = set()
    for c in boundary:
        fields.update(c.keys())
    grid_lists = []
    for f in sorted(fields):
        vals = list(GRID_DEFAULTS.get(f, []))
        grid_lists.append(vals or [None])
    extra = []
    for combo in itertools.product(*grid_lists):
        case = {f: v for f, v in zip(sorted(fields), combo) if v is not None}
        key = str(sorted(case.items()))
        if key not in seen:
            seen.add(key)
            extra.append(case)
        if len(boundary) + len(extra) >= size:
            break
    base = {"year": 3, "backlogs": 0, "category": "general"}
    return [{**base, **c} for c in (boundary + extra)[:size]]


def _journey_length(trace: list[str]) -> int:
    return len(trace)


def compute_impact_summary(*, build_id: str, policy_version: str, procedure_version: str,
                           delta: dict, witnesses: list[dict], faults: list[dict],
                           validation: dict, procedure_before: dict, procedure_after: dict,
                           model, old_model, workflows_registry: list[dict] | None = None,
                           cohort_size: int = 100) -> dict:
    verified = [w for w in witnesses if w.get("verified")]
    behavioral = {"wrong_rejections": 0, "wrong_acceptances": 0, "unnecessary_burdens": 0,
                  "missing_safeguards": 0, "wrong_orderings": 0, "deadline_mismatches": 0,
                  "prohibition_breaches": 0}
    for w in verified:
        k = w.get("kind")
        if k == "wrong_rejection":
            behavioral["wrong_rejections"] += 1
        elif k == "wrong_acceptance":
            behavioral["wrong_acceptances"] += 1
        elif k == "unnecessary_burden":
            behavioral["unnecessary_burdens"] += 1
        elif k == "missing_safeguard":
            behavioral["missing_safeguards"] += 1
        elif k == "wrong_journey":
            behavioral["wrong_orderings"] += 1
        elif k == "deadline_mismatch":
            behavioral["deadline_mismatches"] += 1
        elif k == "prohibition_breach":
            behavioral["prohibition_breaches"] += 1

    affected_nodes = sorted({n for f in faults for n in f.get("affected_nodes", [])})
    affected_rules = (delta or {}).get("affected_rule_ids", [])
    # blast radius across registered workflows via provenance links
    wf_affected, forms, fields = 1, set(), set()
    for n in procedure_before.get("nodes", []):
        impl = n.get("implementation", {}) or {}
        if n["node_id"] in affected_nodes:
            if impl.get("form_field"):
                forms.add(impl.get("form_field"))
                fields.add(impl.get("form_field"))
    if workflows_registry:
        for wf in workflows_registry:
            if wf.get("workflow_id") == procedure_before.get("workflow_id"):
                continue
            for n in wf.get("nodes", []):
                if any((L.get("target") in affected_rules) for L in n.get("provenance_links", [])):
                    wf_affected += 1
                    break

    cohort = synthetic_cohort(model, procedure_before, cohort_size)
    tc = {"cohort_size": len(cohort), "newly_eligible": 0, "newly_ineligible": 0,
          "shorter_journeys": 0, "longer_journeys": 0, "unchanged": 0}
    for c in cohort:
        old_exp = {**evaluate_expected(old_model, c), "order_ok": True}
        new_exp = {**evaluate_expected(model, c), "order_ok": True}
        before = execute(procedure_before, c, model.ordering)
        after = execute(procedure_after or procedure_before, c, model.ordering)
        if not old_exp["eligible"] and new_exp["eligible"]:
            tc["newly_eligible"] += 1
        elif old_exp["eligible"] and not new_exp["eligible"]:
            tc["newly_ineligible"] += 1
        lb, la = _journey_length(before["trace"]), _journey_length(after["trace"])
        if diff_case(new_exp, after, c) is None and diff_case(new_exp, before, c) is None:
            tc["unchanged"] += 1
        elif la < lb:
            tc["shorter_journeys"] += 1
        elif la > lb:
            tc["longer_journeys"] += 1
        else:
            tc["unchanged"] += 1

    vres = (validation or {}).get("results", [])
    by_suite: dict = {}
    for r in vres:
        by_suite.setdefault(r.get("suite"), {"passed": 0, "failed": 0})
        by_suite[r.get("suite")]["passed" if r.get("pass") else "failed"] += 1
    cov = prov_coverage((procedure_after or procedure_before).get("nodes", []))

    summary = {
        "build_id": build_id, "policy_version": policy_version, "procedure_version": procedure_version,
        "semantic_changes": len(affected_rules),
        "semantic_breakdown": {"behavioral": bool((delta or {}).get("behavioral")),
                               "delta_type": (delta or {}).get("type"),
                               "notes": (delta or {}).get("notes", [])},
        "artifacts": {"workflows_affected": wf_affected, "nodes_affected": len(affected_nodes),
                      "affected_nodes": affected_nodes, "affected_rules": affected_rules,
                      "forms_affected": len(forms), "fields_affected": sorted(fields),
                      "unaffected_workflows": max(len(workflows_registry or []) - wf_affected, 0)},
        "behavioral": behavioral,
        "test_cohort": {"label": "Generated test cohort (synthetic — not population prevalence)", **tc},
        "verification": {"tests_before": {"failed": len(witnesses)},
                         "tests_after": {"passed": (validation or {}).get("passed", 0),
                                        "failed": (validation or {}).get("failed", 0),
                                        "total": (validation or {}).get("total", 0),
                                        "by_suite": by_suite},
                         "witnesses_verified": len(verified),
                         "provenance_coverage": cov["coverage"]},
        "approval": {"machine_status": (validation or {}).get("status", "UNKNOWN"),
                     "human_status": "AWAITING_APPROVAL"},
    }
    from services.schemas import check as _scheck
    _scheck("impact_summary", summary, f"impact/{build_id}")
    return summary


def before_after_table(impact: dict) -> list[dict]:
    b = impact.get("behavioral", {})
    v = impact.get("verification", {}).get("tests_after", {})
    return [
        {"metric": "Wrong rejections", "before": b.get("wrong_rejections", 0),
         "after": 0 if v.get("failed", 1) == 0 else "unknown"},
        {"metric": "Unnecessary burdens", "before": b.get("unnecessary_burdens", 0),
         "after": 0 if v.get("failed", 1) == 0 else "unknown"},
        {"metric": "Missing safeguards", "before": b.get("missing_safeguards", 0),
         "after": 0 if v.get("failed", 1) == 0 else "unknown"},
        {"metric": "Failing regression cases",
         "before": impact.get("verification", {}).get("tests_before", {}).get("failed", 0),
         "after": v.get("failed", "?")},
    ]


def witness_detail(witness_id: str, build: dict) -> dict | None:
    w = next((x for x in build.get("witnesses", []) if x.get("witness_id") == witness_id), None)
    if not w:
        return None
    rules = {r["rule_id"]: r for r in build.get("new_rules", [])}
    faults = {f.get("witness_id"): f for f in build.get("faults", [])}
    f = faults.get(witness_id, {})
    gov = " ".join(f.get("affected_nodes", []))
    rule_id = None
    for rid, r in rules.items():
        prov = r.get("provenance", {}) or {}
        if prov.get("section") and any(prov.get("section") in str(x) for x in [gov, w.get("kind")]):
            rule_id = rid
            break
    return {"persona": w.get("case"), "expected": w.get("expected"), "actual": w.get("actual"),
            "trace_expected": w.get("trace_expected"), "trace_actual": w.get("trace_actual"),
            "governing_rule": rule_id, "affected_nodes": f.get("affected_nodes", []),
            "patch_operations": [o for o in build.get("patch", {}).get("operations", [])
                                 if o.get("node_id") in f.get("affected_nodes", [])]}
