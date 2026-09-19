"""Runtime trace ingestion — real-world execution evidence (read-only).

Doctrine: traces are *evidence*, never auto-accepted truth. A trace is one
recorded execution of a procedure for one case (the executed decision, the
steps actually performed). Ingestion validates + stores; comparison replays
the same case through the deterministic engine and reports per-dimension
agreement. Disagreements are surfaced as *candidate witnesses* for a build —
they only become verified witnesses through the normal build pipeline
(find_witnesses -> validate), never by ingestion alone.

Storage: same abstraction as everything else (services.storage: files locally,
DynamoDB single-table on Lambda). Shape documented in shared/schemas/trace.json.
"""
from __future__ import annotations

import time

from services.registry.store import sha
from services.storage import _load, _save

_TRACES = "traces.json"

_BOOL_STRINGS = {
    "true": True, "false": False, "yes": True, "no": False,
    "eligible": True, "ineligible": False, "approved": True, "rejected": False,
    "on_time": True, "late": False, "blocked": True, "clear": False,
}


def _as_bool(v, what: str) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str) and v.strip().lower() in _BOOL_STRINGS:
        return _BOOL_STRINGS[v.strip().lower()]
    raise ValueError(f"trace outcome.{what} must be boolean-like, got {v!r}")


def _normalize_outcome(outcome: dict) -> dict:
    if not isinstance(outcome, dict):
        raise ValueError("trace.outcome must be an object")
    out: dict = {}
    for key in ("eligible", "on_time", "prohibited"):
        if key in outcome and outcome[key] is not None:
            out[key] = _as_bool(outcome[key], key)
    req = outcome.get("required")
    if isinstance(req, dict):
        out["required"] = {str(k): _as_bool(v, f"required[{k}]") for k, v in req.items()}
    elif isinstance(req, list):
        out["required"] = {str(k): True for k in req}
    completed = outcome.get("completed_actions")
    if isinstance(completed, list):
        out["completed_actions"] = [str(a) for a in completed]
    if not out:
        raise ValueError("trace.outcome has no comparable fields "
                         "(eligible/on_time/prohibited/required/completed_actions)")
    return out


def ingest_trace(body: dict) -> dict:
    """Validate + store one runtime trace. Raises ValueError on bad input."""
    if not isinstance(body, dict) or not isinstance(body.get("case"), dict) or not body["case"]:
        raise ValueError("trace.case must be a non-empty object (the applicant/approval case fields)")
    case = body["case"]
    for k, v in case.items():
        if not isinstance(k, str) or not k:
            raise ValueError("trace.case keys must be non-empty strings")
        if v is not None and not isinstance(v, (str, int, float, bool)):
            raise ValueError(f"trace.case[{k!r}] must be a scalar (got {type(v).__name__})")
    outcome = _normalize_outcome(body.get("outcome") or {})
    now = time.time()
    tid = "TRC-" + sha({"case": case, "outcome": outcome,
                        "workflow_id": body.get("workflow_id"),
                        "occurred_at": body.get("occurred_at")})[:8].upper()
    traces = [t for t in _load(_TRACES, []) if t.get("trace_id") != tid]
    rec = {
        "trace_id": tid,
        "workflow_id": body.get("workflow_id"),
        "procedure_version_id": body.get("procedure_version_id"),
        "case": case,
        "outcome": outcome,
        "steps_done": [str(s) for s in (body.get("steps_done") or [])],
        "source": str(body.get("source") or "manual")[:64],
        "source_ref": str(body.get("source_ref") or "")[:256],
        "occurred_at": body.get("occurred_at") or now,
        "ingested_at": now,
    }
    traces.append(rec)
    _save(_TRACES, traces)
    from services.registry.store import audit
    audit("TRACE_INGESTED", {"trace_id": tid, "source": rec["source"],
                             "workflow_id": rec["workflow_id"]})
    return rec


def list_traces(workflow_id: str | None = None, source: str | None = None) -> list:
    out = _load(_TRACES, [])
    if workflow_id:
        out = [t for t in out if t.get("workflow_id") == workflow_id]
    if source:
        out = [t for t in out if t.get("source") == source]
    return sorted(out, key=lambda t: t.get("ingested_at", 0), reverse=True)


def get_trace(trace_id: str) -> dict | None:
    return next((t for t in _load(_TRACES, []) if t.get("trace_id") == trace_id), None)


def compare_traces(build: dict) -> dict:
    """Replay each trace's case through the deterministic engine against the
    build's procedure (stale) and patched preview; report agreement.

    Read-only: nothing here mutates the build, the model, or any procedure —
    and no trace ever becomes a verified witness by itself. Disagreements are
    candidate witnesses for the build pipeline to verify.
    """
    from services.compiler.compiler import compile_rules
    from services.workflow.interpreter import execute
    model = compile_rules(build.get("new_rules") or [])
    procedure = build.get("procedure") or {}
    patched = build.get("patched_workflow") or procedure
    workflow_id = build.get("procedure", {}).get("workflow_id") or build.get("workflow_id")
    # Match traces bound to this workflow (plus unbound ones); demo builds with
    # no workflow_id compare against every stored trace.
    if workflow_id:
        traces = [t for t in list_traces()
                  if t.get("workflow_id") in (None, "", workflow_id)]
    else:
        traces = list_traces()
    results = []
    for t in traces:
        case = t["case"]
        try:
            actual_stale = execute(procedure, case, model.ordering)
            actual_new = execute(patched, case, model.ordering)
        except ValueError as e:  # INVALID_WORKFLOW etc. — compare skipped, never swallowed
            results.append({"trace_id": t["trace_id"], "status": "SKIPPED", "detail": str(e)[:120]})
            continue
        outcome = t["outcome"]
        dims_stale, dims_new = [], []
        for dim in ("eligible", "on_time", "prohibited"):
            if dim in outcome:
                if actual_stale.get(dim) != outcome[dim]:
                    dims_stale.append(dim)
                if actual_new.get(dim) != outcome[dim]:
                    dims_new.append(dim)
        eng_req_stale = {k: v for k, v in (actual_stale.get("required") or {}).items()}
        eng_req_new = {k: v for k, v in (actual_new.get("required") or {}).items()}
        if "required" in outcome:
            for act, done in outcome["required"].items():
                if act in eng_req_stale and eng_req_stale[act] != done:
                    dims_stale.append(f"required:{act}")
                if act in eng_req_new and eng_req_new[act] != done:
                    dims_new.append(f"required:{act}")
        if "completed_actions" in outcome:
            for act in outcome["completed_actions"]:
                if not eng_req_stale.get(act, False) and act not in eng_req_stale:
                    dims_stale.append(f"unmodeled_action:{act}")
                if not eng_req_new.get(act, False) and act not in eng_req_new:
                    dims_new.append(f"unmodeled_action:{act}")
        rec = {
            "trace_id": t["trace_id"], "source": t.get("source"), "case": case,
            "trace_outcome": outcome,
            "vs_stale": {"status": "AGREE" if not dims_stale else "DISAGREE", "mismatches": dims_stale},
            "vs_patched": {"status": "AGREE" if not dims_new else "DISAGREE", "mismatches": dims_new},
        }
        if dims_stale and not dims_new:
            rec["note"] = "trace disagrees with the stale procedure but matches the patched preview — strong candidate witness"
        elif dims_stale and dims_new:
            rec["note"] = "trace disagrees with both graphs — model/context mismatch; needs human review"
        results.append(rec)
    disagree = [r["trace_id"] for r in results if r.get("vs_stale", {}).get("status") == "DISAGREE"]
    return {
        "checked": len(results),
        "agree": sum(1 for r in results if r.get("vs_stale", {}).get("status") == "AGREE"),
        "disagree": len(disagree),
        "disagree_trace_ids": disagree,
        "candidate_witnesses": disagree,
        "results": results,
        "honesty_note": "runtime traces are evidence only; witness status requires the verified build pipeline",
    }
