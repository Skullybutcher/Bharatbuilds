"""Stdlib REST API implementing Spec §45 + §57E (impact, rule review, patch
approval, activation, benchmarks). Persists via services.registry.store."""
from __future__ import annotations
import json
import os
import pathlib
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILDS: dict = {}


def _demo(domain: str = "research_grant"):
    d = ROOT / "demo" / domain
    old = json.loads((d / "rules_v1.json").read_text())
    new = json.loads((d / "rules_v2.json").read_text())
    proc = json.loads((d / "workflow_v1.json").read_text())
    return old, new, proc


def _get_build(bid: str) -> dict | None:
    if bid in BUILDS:
        return BUILDS[bid]
    from services.registry.store import get_build
    b = get_build(bid)
    if b:
        BUILDS[bid] = b
    return b


def _store(build: dict) -> dict:
    BUILDS[build["build_id"]] = build
    try:
        from services.registry.store import save_build, audit
        save_build({k: v for k, v in build.items()})
        audit("BUILD_READY", {"build_id": build["build_id"], "status": build.get("status")})
    except Exception:
        pass
    return build


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj, indent=2, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode() or "{}")
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ---------------- GET ----------------
    def do_GET(self):
        from services.api.pipeline import run_build
        from services.compiler.compiler import compile_rules, evaluate_expected
        from services.workflow.interpreter import execute
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/health"):
            return self._send(200, {"service": "processpatch-api", "status": "ok"})
        if path == "/demo/canonical":
            old, new, proc = _demo(qs.get("domain", ["research_grant"])[0])
            return self._send(200, _store(run_build("POLICY-V2", old, new, proc)))
        if path == "/builds":
            from services.registry.store import list_builds
            local = [{"build_id": b["build_id"], "status": b.get("status")} for b in BUILDS.values()]
            return self._send(200, {"builds": local + list_builds()})
        if path == "/benchmarks":
            return self._send(200, {"benchmarks": [{"version": "v0.1.0", "cases": _bench_manifest().get("total")}]})
        if path.startswith("/benchmark-runs/"):
            parts = path.split("/")
            if len(parts) == 3:
                return self._send(200, _bench_run(parts[2]) or {"error": "unknown run"})
            if len(parts) == 5 and parts[3] == "cases":
                run = _bench_run(parts[2]) or {}
                case = next((c for c in run.get("cases", []) if c.get("case_id") == parts[4]), None)
                return self._send(200, case or {"error": "unknown case"})
            if len(parts) == 4 and parts[3] == "cases":
                return self._send(200, {"cases": (_bench_run(parts[2]) or {}).get("cases", [])})
            return self._send(404, {"error": "not found"})

        seg = path.split("/")
        # /builds/{id}[...]
        if len(seg) >= 3 and seg[1] == "builds":
            bid = seg[2]
            b = _get_build(bid)
            if not b:
                return self._send(404, {"error": "unknown build"})
            tail = "/".join(seg[3:])
            if tail == "":
                return self._send(200, {k: v for k, v in b.items() if k not in ("patched_workflow",)})
            if tail == "diff":
                return self._send(200, b.get("semantic_delta", {}))
            if tail == "witnesses":
                return self._send(200, {"witnesses": b.get("witnesses", [])})
            if tail == "patch":
                return self._send(200, b.get("patch", {}))
            if tail == "certificate":
                return self._send(200, b.get("certificate") or {"status": "no certificate"})
            if tail == "impact":
                return self._send(200, b.get("impact", {}))
            if tail == "impact/witnesses":
                return self._send(200, {"witnesses": b.get("witnesses", [])})
            if tail == "impact/artifacts":
                return self._send(200, b.get("impact", {}).get("artifacts", {}))
            if tail == "rule-reviews":
                from services.governance.store import rule_reviews
                return self._send(200, {"reviews": rule_reviews(bid)})
            if tail == "approvals":
                from services.governance.store import approvals_for
                return self._send(200, {"approvals": approvals_for(bid)})
            if tail == "guardrails":
                from services.governance.store import approval_guardrails
                return self._send(200, approval_guardrails(b))
            if tail == "audit":
                from services.registry.store import audit_for
                return self._send(200, {"audit": audit_for(bid)})
            return self._send(404, {"error": "not found", "path": path})

        if path.startswith("/procedures"):
            from services.registry.store import list_procedure_versions
            wf = qs.get("workflow_id", [None])[0]
            return self._send(200, {"versions": list_procedure_versions(wf)})

        if path.startswith("/portal"):
            cgpa = qs.get("cgpa", [None])[0]
            patched = qs.get("patched", ["0"])[0] == "1"
            domain = qs.get("domain", ["research_grant"])[0]
            old, new, proc = _demo(domain)
            wf = proc
            if patched:
                wf = run_build("POLICY-V2", old, new, proc)["patched_workflow"]
            model = compile_rules(new)
            case = {"cgpa": float(cgpa) if cgpa else 7.8, "amount": float(qs.get("amount", [40000])[0]),
                    "year": 3, "backlogs": 0, "category": "general", "submission_date": "2026-09-28"}
            return self._send(200, {"case": case, "expected": evaluate_expected(model, case),
                                    "actual": execute(wf, case, model.ordering)})
        return self._send(404, {"error": "not found", "path": path})

    # ---------------- POST ----------------
    def do_POST(self):
        from services.api.pipeline import run_build
        body = self._body()
        path = urllib.parse.urlparse(self.path).path

        if path == "/builds":
            domain = body.get("domain", "research_grant")
            old, new, proc = _demo(domain)
            old = body.get("old_rules", old)
            new = body.get("new_rules", new)
            proc = body.get("procedure", proc)
            from services.registry.store import find_build_by_key, compile_key
            key = compile_key(new, proc)
            hit = find_build_by_key(key) or BUILDS.get(key)
            if hit and not body.get("force"):
                return self._send(200, {**hit, "idempotent_reuse": True})
            build = run_build(body.get("policy_version_id", "POLICY-V2"), old, new, proc)
            if build.get("status") not in ("NEEDS_REVIEW", "CONFLICT"):
                from services.governance.store import open_rule_reviews
                try:
                    open_rule_reviews(build["build_id"], build.get("new_rules", []))
                    if body.get("auto_accept", True):
                        from services.governance.store import review_rule
                        for r in build.get("new_rules", []):
                            review_rule(build["build_id"], r["rule_id"], "ACCEPT")
                except Exception:
                    pass
            return self._send(200, _store(build))

        seg = path.split("/")
        if len(seg) >= 4 and seg[1] == "builds":
            bid, tail = seg[2], "/".join(seg[3:])
            b = _get_build(bid)
            if not b:
                return self._send(404, {"error": "unknown build"})
            from services.governance.store import (review_rule, decide_patch, request_patch_review,
                                                   activate_procedure)
            if tail.startswith("rules/") and tail.endswith("/accept"):
                rid = tail.split("/")[1]
                return self._send(200, review_rule(bid, rid, "ACCEPT", reviewer=body.get("reviewer", "USR-001")))
            if tail.startswith("rules/") and tail.endswith("/edit"):
                rid = tail.split("/")[1]
                return self._send(200, review_rule(bid, rid, "EDIT", body.get("human_value"),
                                                   body.get("reason"), body.get("reviewer", "USR-001")))
            if tail.startswith("rules/") and tail.endswith("/reject"):
                rid = tail.split("/")[1]
                return self._send(200, review_rule(bid, rid, "REJECT", reason=body.get("reason")))
            if tail.startswith("rules/") and tail.endswith("/escalate"):
                rid = tail.split("/")[1]
                return self._send(200, review_rule(bid, rid, "ESCALATE", reason=body.get("reason")))
            if tail == "patch/validate":
                return self._send(200, b.get("validation", {}))
            if tail == "patch/review-request":
                return self._send(200, request_patch_review(bid, body.get("opened_hash")))
            if tail == "patch/approve":
                try:
                    rec = decide_patch(bid, b, "APPROVE_CANDIDATE",
                                       body.get("reviewer", {"reviewer_id": "USR-001", "display_name": "Demo Reviewer"}),
                                       body.get("reason", "Patch matches policy and all checks pass."),
                                       body.get("role", "PROCEDURE_OWNER"))
                except ValueError as e:
                    return self._send(409, {"error": str(e)})
                b["status"] = "PATCH_APPROVED"
                _store(b)
                return self._send(200, {**rec, "procedure_version_candidate": "WF-V4"})
            if tail == "patch/reject":
                rec = decide_patch(bid, b, "REJECT_PATCH", body.get("reviewer", {}),
                                   body.get("reason", ""), body.get("role", "PROCEDURE_OWNER"))
                _store(b)
                return self._send(200, rec)
            if tail == "patch/request-revision":
                rec = decide_patch(bid, b, "REQUEST_REVISION", body.get("reviewer", {}),
                                   body.get("reason", ""), body.get("role", "PROCEDURE_OWNER"))
                _store(b)
                return self._send(200, rec)
            if tail.startswith("witnesses/") and tail.endswith("/replay"):
                wid = tail.split("/")[1]
                from services.compiler.compiler import evaluate_expected
                from services.workflow.interpreter import execute
                from services.compiler.compiler import compile_rules
                w = next((x for x in b.get("witnesses", []) if x.get("witness_id") == wid), None)
                if not w:
                    return self._send(404, {"error": "unknown witness"})
                model = compile_rules(b.get("new_rules", []))
                case = w["case"]
                return self._send(200, {"witness": w, "expected": evaluate_expected(model, case),
                                        "actual_before": execute(b.get("procedure", {}), case, model.ordering),
                                        "actual_after": execute(b.get("patched_workflow", b.get("procedure", {})),
                                                                case, model.ordering)})

        if path.startswith("/procedures/") and path.endswith("/activate"):
            version = path.split("/")[2]
            from services.registry.store import list_procedure_versions
            cand = next((v for v in list_procedure_versions() if v.get("procedure_version_id") == version), None)
            if not cand:
                return self._send(404, {"error": "unknown procedure version"})
            bid = body.get("build_id")
            b = _get_build(bid) if bid else None
            if not b:
                return self._send(400, {"error": "build_id required"})
            try:
                from services.governance.store import activate_procedure
                return self._send(200, activate_procedure(bid, b, body.get("reviewer", {}), body.get("reason", "")))
            except ValueError as e:
                return self._send(409, {"error": str(e)})

        if path.startswith("/benchmarks/") and path.endswith("/runs"):
            import subprocess, sys
            version = path.split("/")[2]
            return self._send(200, {"note": "run `make benchmark` or POST handled locally",
                                    "version": version, "latest": _bench_run("latest")})
        return self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


def _bench_manifest() -> dict:
    p = ROOT / "benchmark" / "processpatchbench" / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else {"total": 0}


def _bench_run(run_id: str) -> dict | None:
    if run_id == "latest":
        d = ROOT / "benchmark_runs"
        if not d.exists():
            return None
        runs = sorted([x for x in d.iterdir() if x.is_dir()])
        if not runs:
            return None
        run_id = runs[-1].name
    for base in (ROOT / "benchmark_runs" / run_id / "results.json",
                 ROOT / "benchmark" / "processpatchbench" / "reports" / run_id / "results.json"):
        if base.exists():
            return json.loads(base.read_text())
    return None


def main(port: int = 8000):
    print(f"ProcessPatch API on http://localhost:{port}")
    print("GET /demo/canonical  -> full governed build (witnesses, impact, patch, validation)")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
