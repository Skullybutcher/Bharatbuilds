"""Local stdlib REST API — thin HTTP layer over services.api.actions.

The same actions back the Lambda entry point, so both surfaces stay identical.
"""
from __future__ import annotations
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from services.api import actions
from services.api import authz


def _truthy(v) -> bool:
    """Query-flag parsing: ?include_archived=1 / true / yes / on."""
    return str(v).strip().lower() in ("1", "true", "yes", "on")


class _AuthzHTTP(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj) -> None:
        try:
            body = json.dumps(obj, indent=2, default=str).encode()
        except Exception as e:  # noqa: BLE001
            body = json.dumps({"error": f"encode: {e}"}).encode()
            code = 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        origin = os.environ.get("FRONTEND_ORIGIN", "*")
        self.send_header("Access-Control-Allow-Origin", origin)
        if origin != "*":
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise _AuthzHTTP(400, "invalid Content-Length")
        if n < 0 or n > 1024 * 1024:
            raise _AuthzHTTP(413, "request body exceeds 1 MiB limit")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except (ValueError, UnicodeError):
            raise _AuthzHTTP(400, "body must be valid JSON")
        if not isinstance(body, dict):
            raise _AuthzHTTP(400, "body must be a JSON object")
        return body

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", os.environ.get("FRONTEND_ORIGIN", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _route(self, method: str, path: str, qs: dict, body: dict, identity=None):
        if method == "GET" and path in ("/", "/health"):
            return 200, actions.health()
        if method == "GET" and path == "/auth/config":
            return 200, actions.auth_config()
        if method == "GET" and path == "/demo/canonical":
            return 200, actions.canonical(qs.get("domain", ["research_grant"])[0])
        if method == "GET" and path == "/builds":
            try:
                _scope, _ws = authz.resolve_list_filter(identity, (qs.get("workspace_id") or [None])[0], path)
            except authz.AuthzError as e:
                return e.status, {"error": e.args[0]}
            return 200, actions.list_builds(_truthy(qs.get("include_archived", ["0"])[0]), _scope, _ws)
        if method == "POST" and path == "/builds":
            return 200, actions.create_build(body)
        if method == "GET" and path == "/benchmarks":
            return 200, actions.bench_manifest()
        if method == "GET" and path.startswith("/benchmark-runs/"):
            parts = path.split("/")
            if len(parts) == 3:
                r = actions.bench_run(parts[2])
                return (200, r) if r else (404, {"error": "unknown run"})
            if len(parts) == 5 and parts[3] == "cases":
                run = actions.bench_run(parts[2]) or {}
                case = next((c for c in run.get("cases", []) if c.get("case_id") == parts[4]), None)
                return (200, case) if case else (404, {"error": "unknown case"})
            if len(parts) == 4 and parts[3] == "cases":
                return 200, {"cases": (actions.bench_run(parts[2]) or {}).get("cases", [])}
            return 404, {"error": "not found"}
        if method == "GET" and path.startswith("/procedures"):
            return 200, actions.procedure_versions(qs.get("workflow_id", [None])[0])
        if method == "GET" and path == "/workspaces":
            return 200, actions.list_workspaces()
        if method == "POST" and path == "/workspaces":
            return 200, actions.create_workspace(body)
        if method == "POST" and path == "/procedures":
            return 200, actions.register_procedure(body)
        if method == "GET" and path == "/traces":
            try:
                _scope, _ws = authz.resolve_list_filter(identity, (qs.get("workspace_id") or [None])[0], path)
            except authz.AuthzError as e:
                return e.status, {"error": e.args[0]}
            return 200, actions.list_traces(qs.get("workflow_id", [None])[0], _scope, _ws)
        if method == "POST" and path == "/traces":
            return 200, actions.ingest_trace(body)
        if method == "POST" and path == "/traces/csv":
            return 200, actions.bulk_ingest_traces_csv(body)
        if method == "GET" and path.startswith("/traces/"):
            try:
                return 200, actions.get_trace(path.split("/")[2])
            except KeyError:
                return 404, {"error": "unknown trace"}
        if method == "GET" and path == "/drift":
            try:
                _scope, _ws = authz.resolve_list_filter(identity, (qs.get("workspace_id") or [None])[0], path)
            except authz.AuthzError as e:
                return e.status, {"error": e.args[0]}
            try:
                return 200, actions.drift_report(qs.get("workflow_id", [None])[0], _scope, _ws)
            except KeyError:
                return 404, {"error": "no active procedure for this workflow — activate a build first"}
            except PermissionError as e:
                return 403, {"error": str(e)}
        if method == "GET" and path.startswith("/portal"):
            flat = {k: v[0] for k, v in qs.items()}
            return 200, actions.portal(flat)
        seg = path.split("/")
        if len(seg) >= 3 and seg[1] == "builds":
            bid, tail = seg[2], "/".join(seg[3:])
            if identity is not None:
                # Workspace gate for the whole /builds/{id} subtree (reads and
                # writes alike): unknown ids fall through to the normal 404s.
                _known = actions.peek_build(bid)
                if _known is not None:
                    try:
                        authz.require_build_member(identity, _known, path)
                    except authz.AuthzError as e:
                        return e.status, {"error": e.args[0]}
            simple = {"": actions.get_build_view, "diff": actions.diff,
                      "patch": actions.patch, "certificate": actions.certificate,
                      "impact": actions.impact, "rule-reviews": actions.rule_reviews,
                      "approvals": actions.approvals, "guardrails": actions.guardrails,
                      "audit": actions.audit,
                      "coverage": actions.coverage,
                      "governance-bundle": actions.governance_bundle}
            if method == "GET" and tail in simple:
                try:
                    return 200, simple[tail](bid)
                except KeyError:
                    return 404, {"error": "unknown build"}
                except ValueError as e:  # e.g. governance-bundle refusal
                    return 409, {"error": str(e)}
            if method == "GET" and tail == "witnesses":
                try:
                    return 200, actions.witnesses(bid)
                except KeyError:
                    return 404, {"error": "unknown build"}
            if method == "GET" and tail == "impact/witnesses":
                try:
                    return 200, actions.witnesses(bid)
                except KeyError:
                    return 404, {"error": "unknown build"}
            if method == "GET" and tail == "impact/artifacts":
                try:
                    return 200, actions.impact_artifacts(bid)
                except KeyError:
                    return 404, {"error": "unknown build"}
            if method == "GET" and tail == "trace-compare":
                try:
                    return 200, actions.compare_traces(bid)
                except KeyError:
                    return 404, {"error": "unknown build"}
            if method == "GET" and tail == "governance-bundle":
                try:
                    return 200, actions.governance_bundle(bid)
                except KeyError:
                    return 404, {"error": "unknown build"}
                except ValueError as e:
                    return 409, {"error": str(e)}
            if method == "POST" and tail == "nominate-witness":
                try:
                    return 200, actions.nominate_witness(bid, body)
                except KeyError:
                    return 404, {"error": "unknown build/trace"}
                except ValueError as e:
                    return 409, {"error": str(e)}
            if method == "POST" and tail.startswith("rules/"):
                rid, verb = tail.split("/")[1], tail.split("/")[2]
                if verb in ("accept", "edit", "reject", "escalate"):
                    try:
                        return 200, actions.review_action(bid, rid, verb, body)
                    except KeyError:
                        return 404, {"error": "unknown build/rule"}
            if method == "POST" and tail == "patch/validate":
                try:
                    return 200, actions.validate_patch(bid)
                except KeyError:
                    return 404, {"error": "unknown build"}
            if method == "POST" and tail == "patch/review-request":
                try:
                    return 200, actions.patch_review_request(bid, body)
                except KeyError:
                    return 404, {"error": "unknown build"}
            for verb, fn in (("patch/approve", actions.approve), ("patch/reject", actions.reject),
                             ("patch/request-revision", actions.request_revision)):
                if method == "POST" and tail == verb:
                    try:
                        return 200, fn(bid, body)
                    except KeyError:
                        return 404, {"error": "unknown build"}
                    except ValueError as e:
                        return 409, {"error": str(e)}
            if method == "POST" and tail.startswith("witnesses/") and tail.endswith("/replay"):
                try:
                    return 200, actions.replay(bid, tail.split("/")[1])
                except KeyError:
                    return 404, {"error": "unknown witness"}
            if method == "POST" and tail == "resume":
                try:
                    from services.governance.store import resume_callback
                    return 200, resume_callback(bid, body.get("gate", "patch_approval"), body)
                except (KeyError, ValueError) as e:
                    return 404 if isinstance(e, KeyError) else 409, {"error": str(e)}
            if method == "POST" and tail == "execute":
                try:
                    return 200, actions.start_execution({"build_id": bid, **body})
                except KeyError:
                    return 404, {"error": "unknown build"}
            if method == "POST" and tail in ("archive", "unarchive"):
                try:
                    fn = actions.archive_build if tail == "archive" else actions.unarchive_build
                    return 200, fn(bid, body)
                except KeyError:
                    return 404, {"error": "unknown build"}
            if method == "POST" and tail == "purge":
                try:
                    return 200, actions.purge_build(bid, body)
                except KeyError:
                    return 404, {"error": "unknown build"}
                except PermissionError as e:
                    return 403, {"error": str(e)}
            if method == "POST" and tail == "reverify":
                try:
                    return 200, actions.reverify_build(bid, body)
                except KeyError:
                    return 404, {"error": "unknown build"}
                except ValueError as e:
                    return 409, {"error": str(e)}
            return 404, {"error": "not found", "path": path}
        if method == "GET" and path.startswith("/executions/"):
            try:
                return 200, actions.describe_execution(urllib.parse.unquote(path[len("/executions/"):]))
            except KeyError:
                return 404, {"error": "unknown execution"}
        if method == "POST" and path.startswith("/procedures/") and path.endswith("/activate"):
            try:
                return 200, actions.activate(path.split("/")[2], body)
            except KeyError:
                return 404, {"error": "unknown procedure version"}
            except ValueError as e:
                return 409 if "blocked" in str(e).lower() or "invalidated" in str(e).lower() else 400, {"error": str(e)}
        return 404, {"error": "not found", "path": path}

    def _guard(self, method: str, path: str, body: dict):
        """Enforce auth when enabled; returns (code, body, identity) to route
        with. `off` mode (default) keeps the legacy credential-free behavior."""
        if authz.mode() == "off":
            return 200, body, None
        try:
            if authz.is_public(method, path):
                return 200, body, None
            identity = authz.authenticate(dict(self.headers))
            return 200, authz.authorize(method, path, identity, body), identity
        except authz.AuthzError as e:
            raise _AuthzHTTP(e.status, e.args[0])

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            _, _, _ident = self._guard("GET", parsed.path, {})
        except _AuthzHTTP as e:
            self._send(e.status, {"error": e.message})
            return
        try:
            code, obj = self._route("GET", parsed.path, urllib.parse.parse_qs(parsed.query), {}, _ident)
        except RuntimeError:
            code, obj = 503, {"error": "service temporarily unavailable"}
        self._send(code, obj)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            body = self._body()
            _, body, _ident = self._guard("POST", path, body)
        except _AuthzHTTP as e:
            self._send(e.status, {"error": e.message})
            return
        try:
            code, obj = self._route("POST", path, {}, body, _ident)
        except KeyError as e:  # same mapping as the Lambda surface (aws_handlers.call)
            code, obj = 404, {"error": f"unknown: {e}"}
        except ValueError as e:
            code, obj = 409, {"error": str(e)}
        except RuntimeError:
            code, obj = 503, {"error": "service temporarily unavailable"}
        self._send(code, obj)

    def log_message(self, *a):
        pass


def main(port: int = 8000):
    # Strict bind (no SO_REUSEADDR): on Windows reuse lets a second server
    # silently share an occupied port and randomly steal connections
    # ("empty reply" errors). Failing loudly beats serving garbage.
    class _StrictServer(HTTPServer):
        allow_reuse_address = False

    print(f"ProcessPatch API on http://localhost:{port}")
    print("GET /demo/canonical  -> full governed build (Gate-1 reviews via real path)")
    if authz.mode() != "off":
        print(f"auth: {authz.mode()} (writes need pp-reviewers, activation pp-admins)")
    _StrictServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
