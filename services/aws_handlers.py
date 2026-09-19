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
        return {"statusCode": code, "headers": {"Content-Type": "application/json",
                               "Access-Control-Allow-Origin": "*",
                               "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                               "Access-Control-Allow-Headers": "Content-Type"},
                "body": json.dumps(obj, default=str)}
    return obj


def extractor_handler(event, context):
    """INGEST/EXTRACT_TEXT/EXTRACT_RULES: policy text -> candidate Rule IR."""
    from services.extractor.model_fallback import extract_with_fallback
    from services.normalizer.normalizer import normalize
    text = (event.get("policy_text") or "")
    out = extract_with_fallback(text, event.get("policy_version_id", "POLICY-VX"),
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
        changed = (event.get("semantic_delta") or {}).get("affected_rule_ids", [])
        rules_by_id = {r.get("rule_id"): r for r in event.get("new_rules", [])}
        sources = [rules_by_id[r].get("provenance", {}) for r in changed if r in rules_by_id]
        out["certificate"] = build_certificate(
            build_id=event.get("build_id", "BUILD-?"),
            policy_version=event.get("policy_version_id", "?"),
            procedure_before=event["procedure"], procedure_after=event["patched_workflow"],
            changed_rules=changed, sources=sources,
            semantic_delta=event.get("semantic_delta", {}),
            witnesses=event.get("witnesses", [])[:4], impact=event.get("impact", {}),
            tests_before={"failed": len(event.get("witnesses", []))},
            tests_after={"passed": validation["passed"], "total": validation["total"]},
            policy_text=event.get("policy_text"), accepted_rule_ir=event.get("new_rules", []))
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
                                           approvals_for, save_callback, get_candidate,
                                           mark_build_status)
    op = event.get("op")
    if op == "load_context":
        # Two entry shapes: (a) inline materialized context from an API-driven
        # start (demo/hackathon path); (b) S3 key + registry ids (event path).
        if event.get("policy_text") and event.get("procedure"):
            return _out(event, {"policy_text": event["policy_text"],
                                "procedure": event["procedure"],
                                "old_rules": event.get("old_rules", []),
                                "policy_version_id": event.get("policy_version_id", "POLICY-VX")})
        import os as _os
        import boto3  # lazy: Lambda only
        bucket = _os.environ.get("SOURCE_BUCKET", "")
        text = boto3.client("s3").get_object(
            Bucket=bucket, Key=event["policy_s3_key"])["Body"].read().decode()
        from services.registry.store import list_procedure_versions
        proc = next((v for v in list_procedure_versions(event.get("workflow_id"))
                     if v.get("procedure_version_id") == event.get("procedure_version_id")),
                    None) if event.get("procedure_version_id") else None
        if proc is None:
            from services.registry.store import get_active_procedure
            proc = get_active_procedure(event.get("workflow_id", "WF-RESEARCH-GRANT"))
        from services.storage import _load
        pvers = sorted([v for v in _load("policy_versions.json", [])
                        if v.get("workspace_id") == event.get("workspace_id")],
                       key=lambda v: v.get("created_at", 0))
        old_rules = pvers[-1].get("rules", []) if pvers else []
        return _out(event, {"policy_text": text, "procedure": (proc or {}).get("graph_json", {}),
                            "old_rules": old_rules,
                            "policy_version_id": event.get("policy_version_id", "POLICY-VX")})
    if op == "find_by_key":
        from services.registry.store import compile_key, find_build_by_key
        key = compile_key(event.get("new_rules", []), event.get("procedure", {}))
        hit = find_build_by_key(key)
        return _out(event, {"compile_key": key, "idempotent_reuse": bool(hit),
                            "build": hit})
    if op == "hash":
        from services.registry.store import sha, COMPILER_VERSION, SCHEMA_VERSION
        from services.extractor.model_fallback import EXTRACTOR_VERSION
        digest = sha({"policy_text": event.get("policy_text", ""),
                      "procedure": event.get("procedure", {}),
                      "compiler_version": COMPILER_VERSION,
                      "extractor_version": EXTRACTOR_VERSION,
                      "schema_version": SCHEMA_VERSION})
        return _out(event, {"sha256": digest, "build_id": f"BUILD-{digest[:12].upper()}"})
    if op == "resume" and event.get("taskToken"):
        gate = {"activation": "activation"}.get(event.get("kind", ""), "patch_approval")
        save_callback(event.get("build_id", ""), gate, event.get("taskToken"))
        return _out(event, {"waiting": True, "gate": gate})
    if op == "create_procedure_version":
        from services.registry.store import save_procedure_version
        return _out(event, {"procedure_version": save_procedure_version(
            event.get("patched_workflow", {}), status="candidate")})
    if op == "open_reviews":
        if event.get("taskToken"):
            save_callback(event["build_id"], "rule_review", event.get("taskToken"))
        return _out(event, {"reviews": open_rule_reviews(event["build_id"], event["rules"])})
    if op == "review_rule":
        return _out(event, review_rule(event["build_id"], event["rule_id"], event["decision"],
                                 event.get("human_value"), event.get("reason"),
                                 event.get("reviewer", "USR-001")))
    if op == "guardrails":
        return _out(event, approval_guardrails(event["build"]))
    if op == "request_review":
        if event.get("taskToken"):
            save_callback(event["build_id"], "patch_approval", event.get("taskToken"))
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
            from services.registry.store import get_build as _gb
            build = event.get("build") or _gb(event.get("build_id", "")) or {}
            return _out(event, activate_procedure(event["build_id"], build,
                                            event.get("reviewer", {}), event.get("reason", "")))
        except ValueError as e:
            return _out(event, {"error": str(e)}, 409)
    if op == "approvals":
        return _out(event, {"approvals": approvals_for(event["build_id"])})
    if op == "persist_build":
        from services.registry.store import save_build
        doc = {k: event.get(k) for k in ("build_id", "compile_key", "policy_version_id",
                                         "compiler_version", "status", "semantic_delta",
                                         "witnesses", "faults", "patch", "patched_workflow",
                                         "validation", "impact", "certificate", "new_rules",
                                         "old_rules", "procedure", "review_state",
                                         "policy_sha256", "procedure_sha256")}
        doc = {k: v for k, v in doc.items() if v is not None}
        return _out(event, {"persisted": bool(save_build(doc))})
    if op == "get_candidate":
        return _out(event, {"candidate": get_candidate(event["build_id"])})
    if op == "mark_status":
        return _out(event, {"build": mark_build_status(event["build_id"], event.get("status", ""))})
    return _out(event, {"error": f"unknown op {op}"}, 400)


def api_handler(event, context):
    """API Gateway proxy over services.api.actions — the SAME implementation
    as the local server, so both surfaces stay identical."""
    from services.api import actions as A
    if event.get("op") == "resume" and event.get("taskToken"):
        # Step Functions human-gate wait: persist the token server-side; the
        # human resumes via POST /builds/{id}/resume (never holds the token).
        from services.governance.store import save_callback
        gate = {"activation": "activation"}.get(event.get("kind", ""), "patch_approval")
        save_callback(event.get("build_id", ""), gate, event.get("taskToken"))
        return _out(event, {"waiting": True, "gate": gate})
    request_http = (event.get("requestContext") or {}).get("http") or {}
    method = (request_http.get("method") or event.get("method") or
              event.get("httpMethod"))
    raw_path = event.get("rawPath") or request_http.get("path")
    if not method or not raw_path:
        route = event.get("routeKey", "") or f"{method or 'GET'} {event.get('path', '/') }"
        parts = route.split(" ", 1)
        method = method or (parts[0] if len(parts) > 1 else "GET")
        raw_path = raw_path or (parts[1] if len(parts) > 1 else "/")
    route = f"{method} {raw_path}"
    # substitute {proxy+} / {id} templates with actuals when present
    params = event.get("pathParameters") or {}
    for k, v in params.items():
        raw_path = raw_path.replace("{" + k + "}", v or "")
    stage = (event.get("requestContext") or {}).get("stage")
    if stage and raw_path == f"/{stage}":
        raw_path = "/"
    elif stage and raw_path.startswith(f"/{stage}/"):
        raw_path = raw_path[len(stage) + 1:]
    if method == "OPTIONS":
        return _out(event, {}, 204)
    qs = event.get("queryStringParameters") or {}
    qs = {k: [v] for k, v in qs.items()}
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode()
    try:
        import json as _json
        body = _json.loads(body) if isinstance(body, str) else body
    except Exception:
        body = {}

    # --- auth: Cognito authorizer claims (or self-verified bearer token).
    # `off` mode (default) keeps the legacy credential-free behavior.
    from services.api import authz as _authz
    if _authz.mode() != "off" and not _authz.is_public(method, raw_path):
        # T41c DEBUG: log the authorizer context ONCE per request so claim-shape
        # questions are answered from evidence, not hypothesis. Remove after the
        # auth loop is closed.
        import os as _dbgOS
        if _dbgOS.environ.get("PP_AUTH_DEBUG"):
            _ctx = (event.get("requestContext") or {}).get("authorizer") or {}
            import json as _dbgjson
            print("AUTHDEBUG", _dbgjson.dumps({
                "mode": _authz.mode(), "path": raw_path, "method": method,
                "authz_keys": sorted(_ctx.keys()),
                "jwt_claims_keys": sorted((_ctx.get("jwt") or {}).get("claims", {}).keys()),
                "claims_keys": sorted(_ctx.get("claims", {}).keys()),
                "groups_raw": _dbgjson.dumps((_ctx.get("jwt") or {}).get("claims", {}).get("cognito:groups")
                                           if _ctx.get("jwt") else _ctx.get("claims", {}).get("cognito:groups")),
                "pp_user_pool": _dbgOS.environ.get("PP_USER_POOL_ID", ""),
            })[:1000])
        identity = _authz.claims_from_event(event)
        if not identity:
            try:
                identity = _authz.authenticate({(k or "").lower(): v for k, v in (event.get("headers") or {}).items()})
            except _authz.AuthzError as e:
                return _out(event, {"error": e.args[0]}, e.status)
        try:
            body = _authz.authorize(method, raw_path, identity, body)
        except _authz.AuthzError as e:
            return _out(event, {"error": e.args[0]}, e.status)

    def call(fn, *a):
        try:
            return _out(event, fn(*a))
        except KeyError as e:
            return _out(event, {"error": f"unknown: {e}"}, 404)
        except ValueError as e:
            return _out(event, {"error": str(e)}, 409)

    if method == "GET" and raw_path in ("/", "/health"):
        return _out(event, A.health())
    if method == "GET" and raw_path == "/auth/config":
        return _out(event, A.auth_config())
    if method == "GET" and raw_path == "/demo/canonical":
        return _out(event, A.canonical((qs.get("domain") or ["research_grant"])[0]))
    if method == "GET" and raw_path == "/builds":
        return _out(event, A.list_builds())
    if method == "POST" and raw_path == "/builds":
        return _out(event, A.create_build(body))
    if method == "GET" and raw_path == "/benchmarks":
        return _out(event, A.bench_manifest())
    if method == "GET" and raw_path.startswith("/benchmark-runs/"):
        seg = raw_path.split("/")
        if len(seg) == 3:
            return call(A.bench_run, seg[2]) if A.bench_run(seg[2]) else _out(event, {"error": "unknown run"}, 404)
        return _out(event, {"error": "use the local API for nested benchmark drill-downs"}, 400)
    if method == "GET" and raw_path.startswith("/procedures") and not raw_path.endswith("/activate"):
        return _out(event, A.procedure_versions((qs.get("workflow_id") or [None])[0]))
    if method == "GET" and raw_path == "/workspaces":
        return _out(event, A.list_workspaces())
    if method == "POST" and raw_path == "/workspaces":
        return _out(event, A.create_workspace(body))
    if method == "POST" and raw_path == "/procedures":
        return _out(event, A.register_procedure(body))
    if method == "GET" and raw_path == "/traces":
        return _out(event, A.list_traces((qs.get("workflow_id") or [None])[0]))
    if method == "POST" and raw_path == "/traces/csv":
        return _out(event, A.bulk_ingest_traces_csv(body))
    if method == "POST" and raw_path == "/traces":
        return _out(event, A.ingest_trace(body))
    if method == "GET" and raw_path.startswith("/traces/"):
        return call(A.get_trace, raw_path.split("/")[2])
    if method == "GET" and raw_path.startswith("/portal"):
        return _out(event, A.portal({k: v[0] for k, v in qs.items()}))
    seg = raw_path.split("/")
    if len(seg) >= 3 and seg[1] == "builds":
        bid, tail = seg[2], "/".join(seg[3:])
        simple = {"": A.get_build_view, "diff": A.diff, "patch": A.patch,
                  "certificate": A.certificate, "impact": A.impact,
                  "witnesses": A.witnesses, "rule-reviews": A.rule_reviews,
                  "approvals": A.approvals, "guardrails": A.guardrails, "audit": A.audit,
                  "coverage": A.coverage,
                  "governance-bundle": A.governance_bundle}
        if method == "GET" and tail in ("impact/witnesses",):
            return call(A.witnesses, bid)
        if method == "GET" and tail == "impact/artifacts":
            return call(A.impact_artifacts, bid)
        if method == "GET" and tail == "trace-compare":
            return call(A.compare_traces, bid)
        if method == "GET" and tail == "governance-bundle":
            return call(A.governance_bundle, bid)
        if method == "POST" and tail == "nominate-witness":
            return call(A.nominate_witness, bid, body)
        if method == "GET" and tail in simple:
            return call(simple[tail], bid)
        if method == "POST" and tail.startswith("rules/"):
            rid, verb = tail.split("/")[1], tail.split("/")[2]
            if verb in ("accept", "edit", "reject", "escalate"):
                return call(A.review_action, bid, rid, verb, body)
        posts = {"patch/validate": A.validate_patch, "patch/review-request": A.patch_review_request,
                 "patch/approve": A.approve, "patch/reject": A.reject,
                 "patch/request-revision": A.request_revision}
        if method == "POST" and tail in posts:
            fn = posts[tail]
            if tail == "patch/validate":
                return call(fn, bid)
            return call(fn, bid, body)
        if method == "POST" and tail.startswith("witnesses/") and tail.endswith("/replay"):
            return call(A.replay, bid, tail.split("/")[1])
        if method == "POST" and tail == "resume":
            try:
                from services.governance.store import resume_callback
                return _out(event, resume_callback(bid, body.get("gate", "patch_approval"), body))
            except (KeyError, ValueError) as e:
                return _out(event, {"error": str(e)}, 404 if isinstance(e, KeyError) else 409)
        if method == "POST" and tail == "execute":
            try:
                return _out(event, A.start_execution({"build_id": bid, **body}))
            except KeyError:
                return _out(event, {"error": "unknown build"}, 404)
        return _out(event, {"error": "not found", "path": raw_path}, 404)
    if method == "GET" and raw_path.startswith("/executions/"):
        import urllib.parse as _up
        try:
            return _out(event, A.describe_execution(_up.unquote(raw_path[len("/executions/"):])))
        except KeyError:
            return _out(event, {"error": "unknown execution"}, 404)
    if method == "POST" and raw_path.startswith("/procedures/") and raw_path.endswith("/activate"):
        return call(A.activate, raw_path.split("/")[2], body)
    if "resume" in raw_path:
        return _out(event, {"error": "POST /builds/{id}/resume with {gate, decision, reviewer, reason}"}, 400)
    return _out(event, {"note": "unknown route", "route": route}, 404)
