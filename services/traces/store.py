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


def validate_trace(body: dict) -> tuple:
    """Validate one trace body without storing anything. Returns the
    normalized (case, outcome); raises ValueError on any problem. Shared by
    single ingestion and CSV bulk ingestion (which validates every row BEFORE
    storing any, so a bad row cannot leave a half-ingested batch)."""
    if not isinstance(body, dict) or not isinstance(body.get("case"), dict) or not body["case"]:
        raise ValueError("trace.case must be a non-empty object (the applicant/approval case fields)")
    case = body["case"]
    for k, v in case.items():
        if not isinstance(k, str) or not k:
            raise ValueError("trace.case keys must be non-empty strings")
        if v is not None and not isinstance(v, (str, int, float, bool)):
            raise ValueError(f"trace.case[{k!r}] must be a scalar (got {type(v).__name__})")
    outcome = _normalize_outcome(body.get("outcome") or {})
    return case, outcome


def ingest_trace(body: dict) -> dict:
    """Validate + store one runtime trace. Raises ValueError on bad input."""
    case, outcome = validate_trace(body)
    now = time.time()
    tid = "TRC-" + sha({"case": case, "outcome": outcome,
                        "workflow_id": body.get("workflow_id"),
                        "occurred_at": body.get("occurred_at")})[:8].upper()
    traces = [t for t in _load(_TRACES, []) if t.get("trace_id") != tid]
    rec = {
        "trace_id": tid,
        "workflow_id": body.get("workflow_id"),
        "procedure_version_id": body.get("procedure_version_id"),
        "workspace_id": body.get("workspace_id") or "default",
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


def _outcome_mismatches(actual: dict, outcome: dict) -> list:
    """Dimensions where the engine's execution of a case disagrees with the
    recorded real-world outcome. Shared by compare_traces (build-scoped) and
    drift_report (active-procedure-scoped) so the two can never drift apart."""
    dims = []
    for dim in ("eligible", "on_time", "prohibited"):
        if dim in outcome and actual.get(dim) != outcome[dim]:
            dims.append(dim)
    eng_req = actual.get("required") or {}
    for act, done in (outcome.get("required") or {}).items():
        if act in eng_req and eng_req[act] != done:
            dims.append(f"required:{act}")
    for act in outcome.get("completed_actions", []):
        if act not in eng_req:
            dims.append(f"unmodeled_action:{act}")
    return dims


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
        dims_stale = _outcome_mismatches(actual_stale, outcome)
        dims_new = _outcome_mismatches(actual_new, outcome)
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


def drift_report(workflow_id: str, workspace_id: str | None = None,
                 since: float | None = None) -> dict:
    """Post-activation drift monitor (T70): replay recent runtime traces
    against the CURRENTLY ACTIVE procedure and report the disagreement rate.

    compare_traces is build-scoped — it answers "did this patch fix what the
    traces flagged?". This is the missing half of the CI loop: AFTER a patch
    activates, do new traces keep agreeing with the ACTIVE graph? A rising
    disagreement rate is the signal that reality has moved and a new
    amendment should be compiled — found by evidence, not by anecdote.

    Read-only. Traces are evidence, never auto-accepted: a DISAGREE becomes a
    candidate witness only through the build pipeline (same as compare_traces).
    """
    from services.registry.store import get_active_procedure
    from services.compiler.compiler import compile_rules
    from services.workflow.interpreter import execute
    version = get_active_procedure(workflow_id)
    if not version:
        raise KeyError(f"no active procedure for workflow {workflow_id}")
    graph = version.get("graph_json") or {}
    # The standing policy's ACTIVE rules are the model the active graph runs
    # under — the same lookup the machine's build_context performs.
    from services.storage import _load
    pvers = sorted([v for v in _load("policy_versions.json", [])
                    if v.get("workspace_id") == (workspace_id or "default")
                    and v.get("status") == "active"],
                   key=lambda v: v.get("created_at", 0))
    model = compile_rules(pvers[-1].get("rules", []) if pvers else [])
    traces = [t for t in list_traces(workflow_id)
              if t.get("workspace_id", "default") == (workspace_id or "default")
              and (since is None or (t.get("occurred_at") or 0) >= since)]
    results = []
    for t in traces:
        try:
            actual = execute(graph, t["case"], model.ordering)
        except ValueError as e:  # invalid workflow/case: skipped, never swallowed
            results.append({"trace_id": t["trace_id"], "status": "SKIPPED", "detail": str(e)[:120]})
            continue
        mismatches = _outcome_mismatches(actual, t["outcome"])
        results.append({"trace_id": t["trace_id"], "source": t.get("source"),
                        "case": t["case"], "occurred_at": t.get("occurred_at"),
                        "status": "AGREE" if not mismatches else "DISAGREE",
                        "mismatches": mismatches})
    evaluated = [r for r in results if r["status"] != "SKIPPED"]
    disagree = [r["trace_id"] for r in evaluated if r["status"] == "DISAGREE"]
    rate = (len(disagree) / len(evaluated)) if evaluated else None
    return {
        "kind": "processpatch-drift-report",
        "workflow_id": workflow_id,
        "procedure_version_id": version.get("procedure_version_id"),
        "workspace_id": workspace_id or "default",
        "window": {"since": since},
        "checked": len(results),
        "evaluated": len(evaluated),
        "agree": len(evaluated) - len(disagree),
        "disagree": len(disagree),
        "disagreement_rate": rate,
        "disagree_trace_ids": disagree,
        "results": results,
        "honesty_note": ("traces are evidence only — disagreement is a signal to "
                         "compile an amendment, not an automated change; witness "
                         "status requires the verified build pipeline"),
    }
