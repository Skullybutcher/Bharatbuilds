"""Lambda entry points — one handler per pipeline stage (SAM CodeUri: repo root).

Each handler does deterministic work only; the model runtime is invoked solely
by extractor.handler for semantic extraction. boto3 is touched only inside
services.aws_kit (lazy), so local imports stay credential-free.
"""
from __future__ import annotations


def _out(event, obj, code: int = 200) -> dict:
    """API Gateway calls get an HTTP envelope; Step Functions / local calls
    get the raw payload (SAM ${FnArn} substitution = request/response)."""
    if event.get("routeKey") or event.get("httpMethod"):
        import json
        return {"statusCode": code, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(obj, default=str)}
    return obj


def extractor_handler(event, context):
    """INGEST/EXTRACT_TEXT/EXTRACT_RULES: policy text -> candidate Rule IR."""
    from services.extractor.extractor import extract
    from services.normalizer.normalizer import normalize
    text = (event.get("policy_text") or "")
    out = extract(text, event.get("policy_version_id", "POLICY-VX"),
                  event.get("effective_from", "2026-09-18"))
    ok, bad = normalize(out["rules"])
    out["schema_valid"] = not bad
    out["schema_errors"] = bad
    if not out["schema_valid"]:
        out["next"] = "NEEDS_REVIEW"
    from services.aws_kit import emit_metric
    emit_metric("CompileRuns", 1, build_id=event.get("build_id", "n/a"))
    if out["status"] in ("NEEDS_REVIEW", "CONFLICT"):
        emit_metric("NeedsReviewCount", 1)
    if not out["schema_valid"]:
        emit_metric("ExtractionFailures", 1)
    return _out(event, out)


def compiler_handler(event, context):
    """COMPILE_CONSTRAINTS/SEMANTIC_DIFF/LOCALIZE/GENERATE_PATCH (no witness search)."""
    from services.compiler.compiler import compile_rules, model_to_dict
    from services.normalizer.normalizer import semantic_rule_delta
    from services.localizer.localizer import localize_all
    from services.patcher.patcher import propose
    try:
        model = compile_rules(event["new_rules"])
    except ValueError as e:
        return _out(event, {"error": str(e), "next": "NEEDS_REVIEW"}, 409)
    delta = semantic_rule_delta(event.get("old_rules", []), event["new_rules"])
    if event.get("op", "compile") == "compile":
        return _out(event, {"constraint_model": model_to_dict(model), "semantic_delta": delta})
    witnesses = event.get("witnesses", [])
    faults = localize_all(witnesses, event["procedure"])
    patch = propose(model, event["procedure"], faults)
    return _out(event, {"constraint_model": model_to_dict(model), "semantic_delta": delta,
                  "faults": faults,
                  "patch": {k: v for k, v in patch.items() if k != "patched_workflow"},
                  "patched_workflow": patch["patched_workflow"]})


def witness_handler(event, context):
    """FIND_WITNESSES: E(x) XOR A(x) search (Z3 container if needed later)."""
    from services.compiler.compiler import compile_rules
    from services.witness.generator import find_witnesses
    model = compile_rules(event["new_rules"])
    witnesses = find_witnesses(model, event["procedure"])
    from services.aws_kit import emit_metric
    emit_metric("WitnessesFound", len(witnesses))
    return _out(event, {"witnesses": witnesses, "witnesses_found": bool(witnesses)})


def validator_handler(event, context):
    """RUN_REGRESSION/GENERATE_CERTIFICATE."""
    from services.compiler.compiler import compile_rules
    from services.regression.validator import validate
    from services.certificate.certificate import build_certificate
    model = compile_rules(event["new_rules"])
    old_model = compile_rules([{**r, "status": "active"} for r in event.get("old_rules", [])])
    validation = validate(event.get("patch"), event.get("witnesses", []), model, old_model,
                          event["patched_workflow"], event["procedure"],
                          event.get("semantic_delta", {}), event.get("faults", []))
    out = {"validation": validation, "patch_valid": validation["status"] == "VALIDATED_WITHIN_TESTED_MODEL"}
    from services.aws_kit import emit_metric
    if not out["patch_valid"]:
        emit_metric("PatchValidationFailures", 1)
    if out["patch_valid"] and event.get("with_certificate"):
        out["certificate"] = build_certificate(
            build_id=event.get("build_id", "BUILD-?"),
            policy_version=event.get("policy_version_id", "?"),
            procedure_before=event["procedure"], procedure_after=event["patched_workflow"],
            changed_rules=(event.get("semantic_delta") or {}).get("affected_rule_ids", []),
            sources=[], semantic_delta=event.get("semantic_delta", {}),
            witnesses=event.get("witnesses", [])[:4], impact=event.get("impact", {}),
            tests_before={"failed": len(event.get("witnesses", []))},
            tests_after={"passed": validation["passed"], "total": validation["total"]})
    return _out(event, out)


def impact_handler(event, context):
    """COMPUTE_IMPACT: evidence-backed impact_summary."""
    from services.compiler.compiler import compile_rules
    from services.impact.engine import compute_impact_summary
    model = compile_rules(event["new_rules"])
    old_model = compile_rules([{**r, "status": "active"} for r in event.get("old_rules", [])])
    return _out(event, compute_impact_summary(
        build_id=event.get("build_id", "BUILD-?"),
        policy_version=event.get("policy_version_id", "?"),
        procedure_version=event.get("procedure", {}).get("procedure_version_id"),
        delta=event.get("semantic_delta", {}), witnesses=event.get("witnesses", []),
        faults=event.get("faults", []), validation=event.get("validation", {}),
        procedure_before=event.get("procedure", {}),
        procedure_after=event.get("patched_workflow", event.get("procedure", {})),
        model=model, old_model=old_model))


def govern_handler(event, context):
    """Rule-review and approval gates (server-side guardrails + hash binding)."""
    from services.governance.store import (open_rule_reviews, review_rule, decide_patch,
                                           request_patch_review, approval_guardrails, activate_procedure,
                                           approvals_for)
    op = event.get("op")
    if op == "hash":
        from services.registry.store import sha
        return _out(event, {"sha256": sha({"policy_text": event.get("policy_text", ""),
                                           "procedure": event.get("procedure", {})})})
    if op == "create_procedure_version":
        from services.registry.store import save_procedure_version
        return _out(event, {"procedure_version": save_procedure_version(
            event.get("patched_workflow", {}), status="candidate")})
    if op == "open_reviews":
        return _out(event, {"reviews": open_rule_reviews(event["build_id"], event["rules"])})
    if op == "review_rule":
        return _out(event, review_rule(event["build_id"], event["rule_id"], event["decision"],
                                 event.get("human_value"), event.get("reason"),
                                 event.get("reviewer", "USR-001")))
    if op == "guardrails":
        return _out(event, approval_guardrails(event["build"]))
    if op == "request_review":
        return _out(event, request_patch_review(event["build_id"], event.get("opened_hash")))
    if op == "decide_patch":
        try:
            return _out(event, decide_patch(event["build_id"], event["build"], event["decision"],
                                      event.get("reviewer", {}), event.get("reason", ""),
                                      event.get("role", "PROCEDURE_OWNER")))
        except ValueError as e:
            return _out(event, {"error": str(e)}, 409)
    if op == "activate":
        try:
            return _out(event, activate_procedure(event["build_id"], event["build"],
                                            event.get("reviewer", {}), event.get("reason", "")))
        except ValueError as e:
            return _out(event, {"error": str(e)}, 409)
    if op == "approvals":
        return _out(event, {"approvals": approvals_for(event["build_id"])})
    return _out(event, {"error": f"unknown op {op}"}, 400)


def api_handler(event, context):
    """API Gateway proxy: minimal dispatch for demo reads."""
    route = event.get("routeKey", "")
    if "health" in route or route.endswith("/"):
        return _out(event, {"service": "processpatch-api", "status": "ok"})
    if event.get("op") == "resume" or "resume" in route:
        # Human-gate callback: frontend POSTs the stored taskToken after a
        # review decision; Step Functions resumes via SendTaskSuccess.
        import boto3  # lazy
        boto3.client("stepfunctions").send_task_success(
            taskToken=event["taskToken"], taskOutput=event.get("taskOutput", "{}"))
        return _out(event, {"resumed": True})
    return _out(event, {"note": "Use the full REST surface via the documented routes.", "route": route})
