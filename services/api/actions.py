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


def canonical(domain: str = "research_grant"):
    from services.api.pipeline import run_build
    from services.governance.store import open_rule_reviews, review_rule
    old, new, proc = _demo(domain)
    build = run_build("POLICY-V2", old, new, proc)
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
    from services.registry.store import find_build_by_key, compile_key
    domain = body.get("domain", "research_grant")
    old, new, proc = _demo(domain)
    old = body.get("old_rules", old)
    new = body.get("new_rules", new)
    proc = body.get("procedure", proc)
    key = compile_key(new, proc)
    hit = find_build_by_key(key) or MEMO.get(key)
    if hit and not body.get("force"):
        return {**hit, "idempotent_reuse": True}
    build = run_build(body.get("policy_version_id", "POLICY-V2"), old, new, proc)
    if build.get("status") not in ("NEEDS_REVIEW", "CONFLICT"):
        try:
            from services.governance.store import open_rule_reviews, review_rule
            open_rule_reviews(build["build_id"], build.get("new_rules", []))
            if body.get("auto_accept", True):
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
