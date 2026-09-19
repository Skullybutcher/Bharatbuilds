"""End-to-end build pipeline with governance states (mirrors Step Functions).

INGEST -> HASH_ARTIFACT -> EXTRACT_TEXT -> EXTRACT_RULES -> VALIDATE_RULE_IR
-> RESOLVE_AUTHORITY -> RULE_REVIEW? -> COMPILE_CONSTRAINTS -> SEMANTIC_DIFF
-> FIND_WITNESSES -> COMPUTE_IMPACT -> LOCALIZE_FAULTS -> GENERATE_PATCH
-> RUN_REGRESSION -> GENERATE_CERTIFICATE -> WAIT_FOR_PATCH_APPROVAL -> READY
"""
from __future__ import annotations
import time
from services.compiler.compiler import compile_rules
from services.normalizer.normalizer import semantic_rule_delta, normalize
from services.witness.generator import find_witnesses
from services.localizer.localizer import localize_all
from services.patcher.patcher import propose
from services.regression.validator import validate
from services.certificate.certificate import build_certificate, sha
from services.impact.engine import compute_impact_summary
from services.registry.store import compile_key, COMPILER_VERSION

STATES = ["INGEST", "HASH_ARTIFACT", "EXTRACT_TEXT", "EXTRACT_RULES", "VALIDATE_RULE_IR",
          "RESOLVE_AUTHORITY", "RULE_REVIEW", "COMPILE_CONSTRAINTS", "SEMANTIC_DIFF",
          "FIND_WITNESSES", "COMPUTE_IMPACT", "LOCALIZE_FAULTS", "GENERATE_PATCH",
          "RUN_REGRESSION", "GENERATE_CERTIFICATE", "WAIT_FOR_PATCH_APPROVAL", "READY"]


def run_build(policy_version_id: str, old_rules: list[dict], new_rules: list[dict],
              procedure: dict, workflows_registry: list | None = None,
              extraction: dict | None = None, auto_accept_reviews: bool = True) -> dict:
    t0 = time.time()
    log = list(STATES)
    key = compile_key(new_rules, procedure)
    build_id = key

    ok, bad = normalize(new_rules)
    if bad:
        return {"build_id": build_id, "compile_key": key, "status": "NEEDS_REVIEW",
                "states": log, "error": {"code": "EXTRACTION_FAILURE", "details": bad},
                "duration_s": round(time.time() - t0, 3)}

    delta = semantic_rule_delta(old_rules, new_rules)
    # Old model: the superseded generation is the "before" semantics, so force
    # it active for compilation (compile_rules only accepts active rules).
    old_model = compile_rules([{**r, "status": "active"} for r in old_rules])
    try:
        model = compile_rules(new_rules)
    except ValueError as e:
        code = "CONFLICT" if "CONFLICT" in str(e) else "NEEDS_REVIEW"
        return {"build_id": build_id, "compile_key": key, "status": code, "states": log,
                "error": {"code": code, "details": str(e)}, "duration_s": round(time.time() - t0, 3)}

    witnesses = find_witnesses(model, procedure)
    faults = localize_all(witnesses, procedure, model)
    patch = propose(model, procedure, faults)
    patched = patch["patched_workflow"]
    validation = validate(patch, witnesses, model, old_model, patched, procedure, delta, faults)
    impact = compute_impact_summary(
        build_id=build_id, policy_version=policy_version_id,
        procedure_version=procedure.get("procedure_version_id"), delta=delta,
        witnesses=witnesses, faults=faults, validation=validation,
        procedure_before=procedure, procedure_after=patched, model=model,
        old_model=old_model, workflows_registry=workflows_registry)

    status = "COMPILED" if not witnesses else (
        "PATCH_VALIDATED" if validation["status"] == "VALIDATED_WITHIN_TESTED_MODEL" else "NO_VALIDATED_PATCH")
    operational_status = "DRIFT_CONFIRMED" if witnesses and validation["status"] != "VALIDATED_WITHIN_TESTED_MODEL" else status
    cert = None
    if witnesses and validation["status"] == "VALIDATED_WITHIN_TESTED_MODEL":
        changed = [r.get("rule_id") for r in delta.get("added", [])] or delta.get("affected_rule_ids", [])
        sources = [r.get("provenance", {}) for r in new_rules if r.get("rule_id") in changed]
        cert = build_certificate(
            build_id=build_id, policy_version=policy_version_id, procedure_before=procedure,
            procedure_after=patched, changed_rules=changed, sources=sources,
            semantic_delta=delta, witnesses=witnesses[:4], impact=impact,
            tests_before={"failed": len(witnesses), "total": len(witnesses)},
            tests_after={"passed": validation["passed"], "total": validation["total"]},
            compiler_version=COMPILER_VERSION)

    return {"build_id": build_id, "compile_key": key, "policy_version_id": policy_version_id,
            "compiler_version": COMPILER_VERSION, "status": operational_status,
            "states": log, "semantic_delta": delta, "witnesses": witnesses, "faults": faults,
            "patch": {k: v for k, v in patch.items() if k != "patched_workflow"},
            "patched_workflow": patched, "validation": validation, "impact": impact,
            "certificate": cert, "new_rules": new_rules, "old_rules": old_rules,
            "procedure": procedure, "conflicts": [], "extraction": extraction or {"status": "fixture"},
            "policy_sha256": sha(new_rules), "procedure_sha256": sha(procedure),
            "review_state": "REVIEW_PENDING",
            "created_at": time.time(), "duration_s": round(time.time() - t0, 3)}
