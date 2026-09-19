"""Shared API actions — the single implementation behind BOTH the local
stdlib server (services/api/server.py) and the Lambda entry point
(services.aws_handlers.api_handler). Adding a route in one place adds it
to both surfaces; they cannot drift apart."""
from __future__ import annotations
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
MEMO: dict = {}


def _demo(domain: str = "research_grant"):
    import json
    d = ROOT / "demo" / domain
    return (json.loads((d / "rules_v1.json").read_text()),
            json.loads((d / "rules_v2.json").read_text()),
            json.loads((d / "workflow_v1.json").read_text()))


def _demo_text(domain: str, which: str = "policy_v2.md") -> str:
    p = ROOT / "demo" / domain / which
    return p.read_text() if p.exists() else ""


def _get_build(bid: str):
    if bid in MEMO:
        return MEMO[bid]
    from services.registry.store import get_build
    b = get_build(bid)
    if b:
        MEMO[bid] = b
    return b


def _store(build: dict):
    MEMO[build["build_id"]] = build
    try:
        from services.registry.store import save_build, audit
        save_build(build)
        audit("BUILD_READY", {"build_id": build["build_id"], "status": build.get("status")})
    except Exception:
        pass
    return build


def health():
    return {"service": "processpatch-api", "status": "ok"}


def auth_config():
    """Public auth bootstrap for the UI — non-secret hosted-UI params only.
    Local dev (auth off) returns enabled=False and the UI stays in demo mode.
    The browser derives redirect_uri from its own origin (see docs/auth.md)."""
    import os as _os
    enabled = (_os.environ.get("PROCESSPATCH_AUTH") or "off").strip().lower() != "off"
    if not enabled:
        return {"enabled": False}
    return {"enabled": True,
            "client_id": _os.environ.get("PP_CLIENT_ID", ""),
            "domain": _os.environ.get("PP_AUTH_DOMAIN", "")}


def canonical(domain: str = "research_grant"):
    from services.api.pipeline import run_build
    from services.governance.store import open_rule_reviews, review_rule
    old, new, proc = _demo(domain)
    build = run_build("POLICY-V2", old, new, proc)
    build["policy_text"] = _demo_text(domain)
    build["extraction_backend"] = "fixture"
    try:
        open_rule_reviews(build["build_id"], build.get("new_rules", []))
        for r in build.get("new_rules", []):
            review_rule(build["build_id"], r["rule_id"], "ACCEPT", reviewer="USR-001")
        build["review_state"] = "REVIEWED_VIA_API"
    except Exception:
        pass
    return _store(build)


def create_build(body: dict):
    from services.api.pipeline import run_build
    from services.registry.store import (find_build_by_key, compile_key,
                                         list_procedure_versions)
    domain = body.get("domain", "research_grant")
    old, new, proc = _demo(domain)
    old = body.get("old_rules", old)
    new = body.get("new_rules", new)
    # Multi-procedure workspaces: procedure_version_id targets ANY registered
    # procedure version (docs/workspaces.md); demo domains stay the default.
    if body.get("procedure_version_id"):
        vers = [v for v in list_procedure_versions()
                if v.get("procedure_version_id") == body["procedure_version_id"]]
        if not vers:
            raise KeyError(f"unknown procedure_version_id {body['procedure_version_id']}")
        proc = vers[-1].get("graph_json", {})
    else:
        proc = body.get("procedure", proc)
    policy_text = body.get("policy_text")
    backend = "fixture"
    if policy_text:
        # Real policy input surface: extract (parser, Bedrock fallback when
        # enabled), then Gate-1 rules apply — deterministic-clean results may
        # auto-accept with audit; anything else stays PENDING (mandatory review).
        from services.extractor.model_fallback import extract_with_fallback
        ext = extract_with_fallback(policy_text, body.get("policy_version_id", "POLICY-UPLOAD"))
        backend = ext.get("backend", "deterministic-parser/0.1.0")
        if not ext["rules"] or ext["status"] in ("NEEDS_REVIEW", "CONFLICT", "EXTRACTION_UNAVAILABLE"):
            from services.governance.store import open_rule_reviews as _open
            import time as _t
            bid = f"BUILD-EXTRACT-{int(_t.time()) % 1000000:06d}"
            try:
                _open(bid, ext["rules"])
            except Exception:
                pass
            return _store({"build_id": bid, "status": ext["status"], "extraction": ext,
                           "extraction_backend": backend, "new_rules": ext["rules"],
                           "review_state": "REVIEW_PENDING", "created_at": _t.time()})
        new = ext["rules"]
        auto = body.get("auto_accept", backend == "deterministic-parser/0.1.0" and ext["status"] == "EXTRACTED")
    else:
        policy_text = _demo_text(domain)
        auto = body.get("auto_accept", True)
    key = compile_key(new, proc)
    hit = find_build_by_key(key) or MEMO.get(key)
    if hit and not body.get("force"):
        return {**hit, "idempotent_reuse": True}
    if body.get("defer"):
        # DRAFT registration only: Step Functions (or a later local execute)
        # owns compilation. The synchronous pipeline does NOT run here.
        from services.registry.store import sha
        import time as _t
        draft = {"build_id": f"DRAFT-{sha({'rules': new, 'proc': proc})[:8].upper()}",
                 "status": "DRAFT", "compile_key": key,
                 "policy_version_id": body.get("policy_version_id", "POLICY-V2"),
                 "policy_text": policy_text, "old_rules": old, "new_rules": new,
                 "procedure": proc, "extraction_backend": backend,
                 "review_state": "REVIEW_PENDING", "created_at": _t.time()}
        return _store(draft)
    build = run_build(body.get("policy_version_id", "POLICY-V2"), old, new, proc)
    build["policy_text"] = policy_text
    build["extraction_backend"] = backend
    if build.get("status") not in ("NEEDS_REVIEW", "CONFLICT"):
        try:
            from services.governance.store import open_rule_reviews, review_rule
            open_rule_reviews(build["build_id"], build.get("new_rules", []))
            if body.get("auto_accept", auto):
                for r in build.get("new_rules", []):
                    review_rule(build["build_id"], r["rule_id"], "ACCEPT")
        except Exception:
            pass
    return _store(build)


def list_builds():
    from services.registry.store import list_builds as _lb
    local = [{"build_id": b["build_id"], "status": b.get("status")} for b in MEMO.values()]
    return {"builds": local + _lb()}


def get_build_view(bid: str):
    b = _get_build(bid)
    if not b:
        return None
    return {k: v for k, v in b.items() if k != "patched_workflow"}


def _need(bid: str):
    b = _get_build(bid)
    if not b:
        raise KeyError(bid)
    return b


def diff(bid: str):
    return _need(bid).get("semantic_delta", {})


def witnesses(bid: str):
    return {"witnesses": _need(bid).get("witnesses", [])}


def patch(bid: str):
    return _need(bid).get("patch", {})


def certificate(bid: str):
    return _need(bid).get("certificate") or {"status": "no certificate"}


def impact(bid: str):
    return _need(bid).get("impact", {})


def impact_artifacts(bid: str):
    return _need(bid).get("impact", {}).get("artifacts", {})


def rule_reviews(bid: str):
    from services.governance.store import rule_reviews as _rr
    return {"reviews": _rr(_need(bid)["build_id"])}


def approvals(bid: str):
    from services.governance.store import approvals_for
    return {"approvals": approvals_for(_need(bid)["build_id"])}


def guardrails(bid: str):
    from services.governance.store import approval_guardrails
    return approval_guardrails(_need(bid))


def audit(bid: str):
    from services.registry.store import audit_for
    return {"audit": audit_for(_need(bid)["build_id"])}


def review_action(bid: str, rid: str, action: str, body: dict):
    from services.governance.store import review_rule
    _need(bid)
    verbs = {"accept": "ACCEPT", "edit": "EDIT", "reject": "REJECT", "escalate": "ESCALATE"}
    return review_rule(bid, rid, verbs[action], body.get("human_value"),
                       body.get("reason"), body.get("reviewer", "USR-001"))


def validate_patch(bid: str):
    return _need(bid).get("validation", {})


def patch_review_request(bid: str, body: dict):
    from services.governance.store import request_patch_review
    return request_patch_review(_need(bid)["build_id"], body.get("opened_hash"))


def _decide(bid: str, decision: str, body: dict):
    from services.governance.store import decide_patch
    b = _need(bid)
    rec = decide_patch(bid, b, decision, body.get("reviewer", {}),
                       body.get("reason", ""), body.get("role", "PROCEDURE_OWNER"))
    if decision == "APPROVE_CANDIDATE":
        b["status"] = "PATCH_APPROVED"
    _store(b)
    return rec


def approve(bid: str, body: dict):
    return _decide(bid, "APPROVE_CANDIDATE", body)


def reject(bid: str, body: dict):
    return _decide(bid, "REJECT_PATCH", body)


def request_revision(bid: str, body: dict):
    return _decide(bid, "REQUEST_REVISION", body)


def replay(bid: str, wid: str):
    from services.compiler.compiler import compile_rules, evaluate_expected
    from services.workflow.interpreter import execute
    b = _need(bid)
    w = next((x for x in b.get("witnesses", []) if x.get("witness_id") == wid), None)
    if not w:
        raise KeyError(wid)
    model = compile_rules(b.get("new_rules", []))
    case = w["case"]
    return {"witness": w, "expected": evaluate_expected(model, case),
            "actual_before": execute(b.get("procedure", {}), case, model.ordering),
            "actual_after": execute(b.get("patched_workflow", b.get("procedure", {})),
                                    case, model.ordering)}


def activate(version: str, body: dict):
    from services.registry.store import list_procedure_versions
    cand = next((v for v in list_procedure_versions()
                 if v.get("procedure_version_id") == version), None)
    if not cand:
        raise KeyError(version)
    bid = body.get("build_id")
    b = _get_build(bid) if bid else None
    if not b:
        raise ValueError("build_id required")
    from services.governance.store import activate_procedure
    return activate_procedure(bid, b, body.get("reviewer", {}), body.get("reason", ""))


def portal(params: dict):
    from services.api.pipeline import run_build
    from services.compiler.compiler import compile_rules, evaluate_expected
    from services.workflow.interpreter import execute
    domain = params.get("domain", "research_grant")
    old, new, proc = _demo(domain)
    wf = proc
    if params.get("patched") == "1":
        wf = run_build("POLICY-V2", old, new, proc)["patched_workflow"]
    model = compile_rules(new)
    case = {"cgpa": float(params.get("cgpa", 7.8)), "amount": float(params.get("amount", 40000)),
            "year": 3, "backlogs": 0, "category": "general", "submission_date": "2026-09-28"}
    return {"case": case, "expected": evaluate_expected(model, case),
            "actual": execute(wf, case, model.ordering)}


def procedure_versions(workflow_id=None):
    from services.registry.store import list_procedure_versions as _lpv
    return {"versions": _lpv(workflow_id)}


# ---- multi-procedure workspaces (any registered procedure can be built)
def list_workspaces():
    from services.registry.store import _load
    return {"workspaces": _load("workspaces.json", [])}


def create_workspace(body: dict):
    from services.registry.store import create_workspace as _cw, audit
    name = (body or {}).get("name", "").strip()
    if not name:
        raise ValueError("workspace name required")
    rec = _cw(name)
    audit("WORKSPACE_CREATED", {"workspace_id": rec["workspace_id"], "name": name})
    return rec


def register_procedure(body: dict):
    """Register a procedure graph as an immutable active version. The graph is
    validated (INVALID_WORKFLOW fails closed) before it can be built against."""
    from services.registry.store import save_procedure_version, audit
    from services.workflow.interpreter import validate_dag
    wf = (body or {}).get("procedure")
    if not isinstance(wf, dict) or not (wf.get("procedure_version_id") or body.get("procedure_version_id")):
        raise ValueError("procedure (with procedure_version_id) required")
    if body.get("procedure_version_id"):
        wf = {**wf, "procedure_version_id": body["procedure_version_id"]}
    if body.get("workflow_id"):
        wf = {**wf, "workflow_id": body["workflow_id"]}
    validate_dag(wf)  # raises INVALID_WORKFLOW -> 409 fail-closed
    rec = save_procedure_version(wf, status="active")
    audit("PROCEDURE_REGISTERED", {"procedure_version_id": rec["procedure_version_id"],
                                   "workflow_id": rec.get("workflow_id")})
    return rec


def ingest_trace(body: dict):
    from services.traces.store import ingest_trace as _ingest
    return _ingest(body or {})


def list_traces(workflow_id=None):
    from services.traces.store import list_traces as _lt
    return {"traces": _lt(workflow_id)}


def get_trace(trace_id: str):
    from services.traces.store import get_trace as _gt
    t = _gt(trace_id)
    if not t:
        raise KeyError(trace_id)
    return t


def compare_traces(bid: str):
    """Read-only comparison: replay trace cases vs the build's graphs."""
    from services.traces.store import compare_traces as _cmp
    return _cmp(_need(bid))


def start_execution(body: dict):
    """API-driven cloud execution (primary demo path).

    The build is a DRAFT (or any stored build); Step Functions owns
    compilation from here. Local (no STATEMACHINE_ARN): run the synchronous
    pipeline now and record READY_LOCAL. On AWS: upload the policy text to
    the versioned source bucket for evidence, then StartExecution with a
    complete inline envelope (LOAD_BUILD_CONTEXT passes it through).
    """
    import os as _os
    import time as _t
    from services.registry.store import _load, _save
    bid = body.get("build_id")
    b = _get_build(bid) if bid else None
    if not b:
        raise KeyError(bid or "missing build_id")
    arn = _os.environ.get("STATEMACHINE_ARN", "")
    if arn:
        import boto3  # lazy
        bucket = _os.environ.get("SOURCE_BUCKET", "")
        policy_key = f"builds/{bid}/policy.md"
        if bucket and b.get("policy_text"):
            boto3.client("s3").put_object(Bucket=bucket, Key=policy_key,
                                          Body=b["policy_text"].encode())
        ex = boto3.client("stepfunctions").start_execution(
            stateMachineArn=arn, name=f"{bid}-{int(_t.time())}",
            input=_json_dumps({"policy_s3_key": policy_key,
                               "policy_text": b.get("policy_text", ""),
                               "procedure": b.get("procedure", {}),
                               "old_rules": b.get("old_rules", []),
                               "policy_version_id": b.get("policy_version_id", "POLICY-V2"),
                               "workflow_id": b.get("procedure", {}).get("workflow_id", "WF-RESEARCH-GRANT"),
                               "workspace_id": b.get("workspace_id", "default"),
                               "procedure_version_id": b.get("procedure", {}).get("procedure_version_id") or
                               b.get("procedure_version_id", "WF-V3")}))
        rec = {"executionArn": ex["executionArn"], "build_id": bid,
               "status": "RUNNING", "started": _t.time()}
    else:
        from services.api.pipeline import run_build as _run
        full = _run(b.get("policy_version_id", "POLICY-V2"), b.get("old_rules", []),
                    b.get("new_rules", []), b.get("procedure", {}))
        full["policy_text"] = b.get("policy_text", "")
        full["extraction_backend"] = b.get("extraction_backend", "fixture")
        _store(full)
        try:
            from services.governance.store import open_rule_reviews as _open, review_rule as _rr
            _open(full["build_id"], full.get("new_rules", []))
            for r in full.get("new_rules", []):
                _rr(full["build_id"], r["rule_id"], "ACCEPT", reviewer="USR-001")
            full["review_state"] = "REVIEWED_VIA_API"
            _store(full)
        except Exception:
            pass
        rec = {"executionArn": f"local:{full['build_id']}", "build_id": full["build_id"],
               "status": "READY_LOCAL", "started": _t.time(),
               "note": "local synchronous pipeline executed for this DRAFT"}
    execs = [e for e in _load("executions.json", []) if e.get("executionArn") != rec["executionArn"]] + [rec]
    _save("executions.json", execs)
    return rec


def describe_execution(arn: str):
    import os as _os
    from services.registry.store import _load
    if arn.startswith("local:"):
        rec = next((e for e in _load("executions.json", [])
                    if e.get("executionArn") == arn), None)
        if not rec:
            raise KeyError(arn)
        return rec
    import boto3  # lazy
    d = boto3.client("stepfunctions").describe_execution(executionArn=arn)
    return {"executionArn": arn, "status": d.get("status"), "started": str(d.get("startDate")),
            "output": (d.get("output") or "")[:2000]}


def _json_dumps(obj) -> str:
    import json as _j
    return _j.dumps(obj, default=str)


def bench_manifest():
    import json
    p = ROOT / "benchmark" / "processpatchbench" / "manifest.json"
    return {"benchmarks": [{"version": "v0.1.0", "cases": json.loads(p.read_text()).get("total")}]}


def bench_run(run_id: str):
    for base in (ROOT / "benchmark_runs" / run_id / "results.json",):
        if base.exists():
            import json
            return json.loads(base.read_text())
    if run_id == "latest":
        d = ROOT / "benchmark_runs"
        if d.exists():
            runs = sorted([x for x in d.iterdir() if x.is_dir()])
            if runs:
                return bench_run(runs[-1].name)
    return None
