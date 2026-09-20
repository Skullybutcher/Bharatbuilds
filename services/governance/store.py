"""HITL governance (Spec 57B): three trust states, three review gates, hash-bound
approvals, activation, audit timeline.

  AI_EXTRACTED != MACHINE_VERIFIED != HUMAN_APPROVED

Gate 1 (rule review): ACCEPT | EDIT (keeps machine value) | REJECT | ESCALATE
Gate 2 (patch review): APPROVE_CANDIDATE | REJECT_PATCH | REQUEST_REVISION
Gate 3 (activation): FINAL_APPROVAL -> active_procedure = candidate

APPROVE is disabled while: unresolved reviews / conflicts, validation != PASS,
preservation != PASS, provenance below threshold, or candidate hash changed
since the reviewer opened it (APPROVAL INVALIDATED).
"""
from __future__ import annotations
import hashlib
import json
import time
from services.storage import (_load, _save, get_item, put_item, ConcurrencyError)
from services.registry.store import audit, sha

ROLES = {"POLICY_REVIEWER", "PROCEDURE_OWNER", "FINAL_APPROVER"}
PROVENANCE_THRESHOLD = 1.0


def _patched(build: dict) -> dict:
    """Single source of truth for the validated repaired graph: the top-level
    build field the pipeline emits. Never build.patch.patched_workflow."""
    return build.get("patched_workflow", {}) or {}


def _workflow_semantic(graph: dict) -> dict:
    """Approval-relevant content: nodes + edges. Envelope fields
    (version id/label/status) are registry bookkeeping and are excluded so a
    candidate minted from the validated graph hashes identically."""
    return {"nodes": (graph or {}).get("nodes", []), "edges": (graph or {}).get("edges", [])}


# ---- Gate 1: rule reviews ---------------------------------------------------
def _review_id(build_id: str, rule_id: str) -> str:
    # Deterministic + unique per (build, rule): opening reviews is idempotent
    # and DynamoDB-safe (no millisecond collisions).
    safe = lambda s: "".join(c if c.isalnum() or c in "-_" else "-" for c in str(s))
    return f"REV#{safe(build_id)}#{safe(rule_id)}"


def open_rule_reviews(build_id: str, rules: list[dict]) -> list[dict]:
    """One review record per (build, rule), written per record. The review id is
    deterministic (REV#build#rule), so concurrent openers converge on one record
    instead of duplicating: the loser of the create race adopts the winner."""
    out = []
    for r in rules:
        rid = _review_id(build_id, r.get("rule_id"))
        rec, ver = get_item("rule_reviews.json", rid)
        if rec:
            out.append(rec)
            continue
        new = {"review_id": rid, "build_id": build_id,
               "rule_id": r.get("rule_id"),
               "decision": "PENDING", "machine_value": r,
               "human_value": None, "reason": None, "timestamp": None}
        try:
            put_item("rule_reviews.json", rid, new, expect=ver)
        except ConcurrencyError:
            rec, _ = get_item("rule_reviews.json", rid)  # another opener won
            out.append(rec)
            continue
        out.append(new)
    audit("RULE_REVIEW_PENDING", {"build_id": build_id, "count": len(out)})
    return out


def rule_reviews(build_id: str) -> list[dict]:
    return [r for r in _load("rule_reviews.json", []) if r.get("build_id") == build_id]


def review_rule(build_id: str, rule_id: str, decision: str, human_value: dict | None = None,
                reason: str | None = None, reviewer: str = "USR-001") -> dict:
    if decision not in ("ACCEPT", "EDIT", "REJECT", "ESCALATE"):
        raise ValueError(f"unknown review decision {decision!r}")
    rid = _review_id(build_id, rule_id)
    rec, ver = get_item("rule_reviews.json", rid)
    if not rec:
        raise KeyError(f"no review for {rule_id} in {build_id}")
    rec.update({"decision": decision,
                "human_value": human_value if decision == "EDIT" else None,
                "reason": reason, "reviewer": reviewer, "timestamp": time.time()})
    try:
        # Optimistic: two reviewers deciding the same rule cannot both win; the
        # loser reloads instead of silently overwriting the winner's decision.
        put_item("rule_reviews.json", rid, rec, expect=ver)
    except ConcurrencyError as e:
        raise ValueError("this review changed while you were deciding — reload and retry") from e
    audit(f"RULE_{decision}", {"build_id": build_id, "rule_id": rule_id, "reviewer": reviewer})
    return rec


def unresolved_rule_reviews(build_id: str) -> int:
    return sum(1 for r in rule_reviews(build_id) if r.get("decision") in ("PENDING", "ESCALATE"))


def accepted_rules(build_id: str) -> list[dict]:
    out = []
    for r in rule_reviews(build_id):
        if r.get("decision") == "ACCEPT":
            out.append(r["machine_value"])
        elif r.get("decision") == "EDIT" and r.get("human_value"):
            out.append(r["human_value"])
    return out


# ---- Gate 2/3: patch approval + activation ----------------------------------
def _artifact_hashes(build: dict) -> dict:
    # Explicit names: each hash says exactly what it covers.
    return {"accepted_rule_ir_sha256": sha(build.get("new_rules", [])),
            "procedure_before_sha256": sha(build.get("procedure", {})),
            "procedure_after_sha256": sha(_workflow_semantic(_patched(build))),
            "patch_operations_sha256": sha((build.get("patch", {}) or {}).get("operations", [])),
            "certificate_sha256": sha(build.get("certificate", {}))}


def approval_guardrails(build: dict) -> dict:
    bid = build.get("build_id")
    v = build.get("validation", {}) or {}
    suites = {}
    for r in v.get("results", []):
        suites.setdefault(r.get("suite"), []).append(r.get("pass"))
    preservation_ok = all(suites.get("unchanged", [True]))
    prov = (build.get("impact") or {}).get("verification", {}).get("provenance_coverage", 0)
    checks = {
        "unresolved_rule_review": unresolved_rule_reviews(bid),
        "unresolved_conflicts": len(build.get("conflicts", [])),
        "patch_validation": v.get("status"),
        "preservation": "PASS" if preservation_ok else "FAIL",
        "provenance_coverage": prov,
    }
    blockers = []
    if checks["unresolved_rule_review"] > 0:
        blockers.append("unresolved_rule_review > 0")
    if checks["unresolved_conflicts"] > 0:
        blockers.append("unresolved_conflicts > 0")
    if checks["patch_validation"] != "VALIDATED_WITHIN_TESTED_MODEL":
        blockers.append("patch_validation != PASS")
    if checks["preservation"] != "PASS":
        blockers.append("preservation_test != PASS")
    if (prov or 0) < PROVENANCE_THRESHOLD:
        blockers.append("provenance_coverage < required_threshold")
    return {"checks": checks, "blockers": blockers, "approvable": not blockers}


def request_patch_review(build_id: str, reviewer_opened_hash: str | None = None) -> dict:
    # One pending-review row per build (SK = build_id): a fresh request
    # replaces only its own record, not the whole collection.
    rec = {"build_id": build_id, "status": "PATCH_REVIEW_PENDING",
           "opened_hash": reviewer_opened_hash, "timestamp": time.time()}
    put_item("patch_reviews.json", build_id, rec)
    return rec


def _record_approval(base: dict) -> dict:
    """Mint a unique approval id and persist the record — the ONLY writer of
    approvals.json rows. The id is sequence-derived, so two concurrent approvers
    can compute the same one; the create-only version check turns that into a
    retry with the next sequence instead of a duplicate id (an id collision here
    would silently merge two different decisions into one evidence row)."""
    date = time.strftime("%Y%m%d")
    approvals = _load("approvals.json", [])
    seq = 1 + max([int(str(a["approval_id"]).rsplit("-", 1)[-1])
                   for a in approvals
                   if str(a.get("approval_id", "")).startswith(f"APR-{date}-")] or [0])
    from services.schemas import check as _scheck
    for attempt in range(8):
        candidate = {**base, "approval_id": f"APR-{date}-{seq + attempt:04d}"}
        _scheck("approval", candidate, f"approval/{candidate.get('build_id')}")
        try:
            put_item("approvals.json", candidate["approval_id"], candidate, expect=0)
            return candidate
        except ConcurrencyError:
            continue
    raise RuntimeError("could not mint a unique approval id under contention")


def decide_patch(build_id: str, build: dict, decision: str, reviewer: dict,
                 reason: str, role: str = "PROCEDURE_OWNER") -> dict:
    if decision not in ("APPROVE_CANDIDATE", "REJECT_PATCH", "REQUEST_REVISION"):
        raise ValueError(f"unknown patch decision {decision!r}")
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    approvals = _load("approvals.json", [])
    current_hash = sha((build.get("patch", {}) or {}).get("operations", []))
    opened = next((r for r in _load("patch_reviews.json", [])
                   if r.get("build_id") == build_id), {}).get("opened_hash")
    if decision == "APPROVE_CANDIDATE":
        if opened and opened != current_hash:
            audit("APPROVAL_INVALIDATED", {"build_id": build_id})
            raise ValueError("APPROVAL INVALIDATED: Artifact changed since review. Reload required.")
        gates = approval_guardrails(build)
        if not gates["approvable"]:
            raise ValueError(f"APPROVE disabled: {gates['blockers']}")
    base = {"build_id": build_id, "approval_type": "PATCH_REVIEW",
            "reviewer": reviewer, "role": role, "decision": decision, "reason": reason,
            "timestamp": time.time(), "artifacts": _artifact_hashes(build)}
    if decision == "REJECT_PATCH":
        _mark_candidate(build, "inactive")
    if decision == "APPROVE_CANDIDATE":
        # Mint BEFORE persisting so the stored approval carries the id.
        base["candidate_version_id"] = create_candidate_version(build)["procedure_version_id"]
    rec = _record_approval(base)
    audit(f"PATCH_{decision}", {"build_id": build_id, "approval_id": rec["approval_id"]})
    return rec


def create_candidate_version(build: dict) -> dict:
    """Gate-2 side effect: persist the validated patch as an IMMUTABLE
    candidate procedure version. Returns the version record; the UI must
    activate THIS id — no hardcoded version names, no re-creation."""
    from services.registry.store import save_procedure_version
    candidate = _patched(build)
    if not candidate:
        raise ValueError("cannot mint candidate: build has no validated patched_workflow")
    tag = sha(build.get("compile_key", build.get("build_id", "")))[:8].upper()
    base = (candidate.get("procedure_version_id") or "WF").replace("-PATCHED", "")
    candidate = {**candidate, "procedure_version_id": f"{base}-PATCH-{tag}",
                 "version_label": f"{candidate.get('version_label', '')} (candidate {tag})"}
    from services.registry.store import list_procedure_versions
    existing = next((v for v in list_procedure_versions()
                     if v.get("procedure_version_id") == candidate["procedure_version_id"]), None)
    if existing:
        return existing
    try:
        saved = save_procedure_version({**candidate, "status": "candidate"}, status="candidate")
    except ValueError:
        # Lost the create race: two workers passed the pre-check and the
        # create-only write enforced immutability. The winner's record IS this
        # candidate — adopt it (idempotent re-mint) instead of failing the
        # execution with 'already exists'.
        saved = next((v for v in list_procedure_versions()
                      if v.get("procedure_version_id") == candidate["procedure_version_id"]), None)
        if saved is None:
            raise
    cand_row = {"record_id": f"{build.get('build_id')}#{saved.get('procedure_version_id')}",
                "build_id": build.get("build_id"),
                "procedure_version_id": saved.get("procedure_version_id"),
                "status": "candidate", "ts": time.time()}
    put_item("candidates.json", cand_row["record_id"], cand_row)
    audit("CANDIDATE_CREATED", {"build_id": build.get("build_id"),
                                "procedure_version_id": saved.get("procedure_version_id")})
    return saved


def activate_procedure(build_id: str, build: dict, reviewer: dict, reason: str,
                       candidate_version_id: str | None = None) -> dict:
    """Gate 3: activate the EXACT immutable candidate minted at approval time.

    Loads the candidate version by id and requires
    hash(candidate.graph) == approved procedure_after_sha256 before flipping
    the active pointer. Never re-saves or re-derives the graph.
    """
    approvals = [a for a in _load("approvals.json", []) if a.get("build_id") == build_id]
    approves = [a for a in approvals if a.get("decision") == "APPROVE_CANDIDATE"]
    if not approves:
        raise ValueError("Activation blocked: no APPROVE_CANDIDATE on record.")
    approved_hashes = approves[-1]["artifacts"]
    if approved_hashes != _artifact_hashes(build):
        audit("APPROVAL_INVALIDATED", {"build_id": build_id})
        raise ValueError("APPROVAL INVALIDATED: Artifact changed since review. Reload required.")
    cid = candidate_version_id or approves[-1].get("candidate_version_id")
    if not cid:
        raise ValueError("Activation blocked: no candidate_version_id on the approval.")
    from services.registry.store import sha
    vers = _load("procedure_versions.json", [])
    cand = next((v for v in vers if v.get("procedure_version_id") == cid), None)
    if not cand or cand.get("status") not in ("candidate", "active"):
        raise ValueError(f"Activation blocked: candidate {cid} not found or not activatable.")
    if sha(_workflow_semantic(cand.get("graph_json", {}))) != approved_hashes["procedure_after_sha256"]:
        audit("APPROVAL_INVALIDATED", {"build_id": build_id})
        raise ValueError("APPROVAL INVALIDATED: candidate graph differs from approved hash.")
    for v in vers:
        if v.get("workflow_id") == cand.get("workflow_id"):
            want = "active" if v.get("procedure_version_id") == cid else "superseded"
            if v.get("status") != want:
                # Per-record status flip: a candidate minted concurrently for
                # this workflow can no longer be deleted by this rewrite, and
                # each record's write is independent (no partial-state window).
                put_item("procedure_versions.json", v["procedure_version_id"],
                         {**v, "status": want})
    saved = {**cand, "status": "active"}
    rec = {"approval_id": f"APR-{time.strftime('%Y%m%d')}-{len(approvals) + 1:04d}",
           "build_id": build_id, "approval_type": "PROCEDURE_ACTIVATION",
           "reviewer": reviewer, "role": "FINAL_APPROVER", "decision": "APPROVE",
           "reason": reason, "timestamp": time.time(), "artifacts": _artifact_hashes(build)}
    rec = _record_approval(rec)
    audit("PROCEDURE_ACTIVATED", {"build_id": build_id,
                                 "procedure_version_id": saved.get("procedure_version_id")})
    return {"approval": rec, "procedure_version": saved}


def _mark_candidate(build: dict, status: str) -> None:
    # One status row per (build, status), keyed by record_id: a repeated mark
    # replaces its own row instead of colliding on SK=build_id (the T50 shape,
    # one collection over).
    rec = {"record_id": f"{build.get('build_id')}#{status}",
           "build_id": build.get("build_id"), "status": status, "ts": time.time()}
    put_item("candidates.json", rec["record_id"], rec)


def approvals_for(build_id: str) -> list:
    return [a for a in _load("approvals.json", []) if a.get("build_id") == build_id]


def get_candidate(build_id: str) -> dict | None:
    """Read-only lookup of the candidate minted at APPROVE_CANDIDATE time.
    The Step Functions path uses this (FETCH) instead of creating a second
    candidate — exactly one owner per side effect."""
    cands = [c for c in _load("candidates.json", [])
             if c.get("build_id") == build_id and c.get("status") == "candidate"]
    return cands[-1] if cands else None


def mark_build_status(build_id: str, status: str) -> dict | None:
    from services.registry.store import get_build, save_build
    b = get_build(build_id)
    if not b:
        return None
    b["status"] = status
    save_build(b)
    audit("BUILD_STATUS", {"build_id": build_id, "status": status})
    return b


# ---- demo purge (hard delete) ------------------------------------------------
PURGEABLE_COLLECTIONS = ("callbacks.json", "rule_reviews.json", "patch_reviews.json",
                         "approvals.json", "candidates.json")


def purge_build_records(build_id: str) -> dict:
    """Remove every governance row belonging to one build. HARD DELETE — used
    only by the flagged demo purge path (PP_DEMO_PURGE).

    `procedure_versions.json` is deliberately NOT touched: procedure versions
    are the shared registry, not per-build evidence. Returning counts (not a
    bool) keeps the purge report honest about what actually disappeared."""
    removed = {}
    for name in PURGEABLE_COLLECTIONS:
        rows = _load(name, [])
        keep = [r for r in rows if r.get("build_id") != build_id]
        if len(keep) != len(rows):
            _save(name, keep)
            removed[name] = len(rows) - len(keep)
    return removed


# ---- Step Functions human-gate callbacks ------------------------------------
CLAIM_STALE_S = 60  # a DECIDING claim older than this is reclaimable


def _cb_key(build_id: str, gate: str) -> str:
    return f"{build_id}#{gate}"


def save_callback(build_id: str, gate: str, task_token: str | None,
                  execution_arn: str | None = None) -> dict:
    """Persist the taskToken at WAIT time so a later human action can resume
    the execution WITHOUT the client ever holding the token. One record per
    (build, gate)."""
    rec = {"build_id": build_id, "gate": gate, "task_token": task_token,
           "execution_arn": execution_arn, "status": "WAITING", "timestamp": time.time()}
    _, ver = get_item("callbacks.json", _cb_key(build_id, gate))
    put_item("callbacks.json", _cb_key(build_id, gate), rec, expect=ver)
    audit("GATE_WAITING", {"build_id": build_id, "gate": gate})
    return rec


def get_callback(build_id: str, gate: str) -> dict | None:
    return get_item("callbacks.json", _cb_key(build_id, gate))[0]


def _apply_gate_decision(build_id: str, gate: str, body: dict) -> dict:
    """The domain side effect of one gate decision. Runs at most ONCE per gate:
    resume_callback claims the gate before calling this."""
    if gate == "rule_review":
        for rid, dec in (body.get("decisions") or {}).items():
            review_rule(build_id, rid, dec, body.get("human_value"),
                        body.get("reason"), (body.get("reviewer") or {}).get("reviewer_id", "USR-001"))
        acc = accepted_rules(build_id)
        output = {"accepted": bool(acc) and not unresolved_rule_reviews(build_id),
                  "accepted_rules": acc}
    elif gate == "patch_approval":
        from services.registry.store import get_build
        build = get_build(build_id) or {}
        rec = decide_patch(build_id, build, body.get("decision", "REJECT_PATCH"),
                           body.get("reviewer", {}), body.get("reason", ""),
                           body.get("role", "PROCEDURE_OWNER"))
        output = {"decision": body.get("decision"), "approval_id": rec["approval_id"],
                  "candidate_version_id": rec.get("candidate_version_id")}
    elif gate == "activation":
        # Single owner of the side effect is the ACTIVATE state (cloud) or the
        # direct /procedures/{v}/activate call (local). Resume only verifies
        # preconditions so nothing activates twice.
        from services.registry.store import get_build
        build = get_build(build_id) or {}
        _ = build  # loaded to confirm the build exists for the decision below
        approvals = [a for a in _load("approvals.json", []) if a.get("build_id") == build_id]
        reviewer = body.get("reviewer") or {}
        if body.get("decision") == "APPROVE":
            if not any(a.get("decision") == "APPROVE_CANDIDATE" for a in approvals):
                raise ValueError("Activation blocked: no APPROVE_CANDIDATE on record.")
            # The ASL's ACTIVATE state resolves $.activation_decision.reviewer and
            # .reason — this output IS that task payload. A decision without an
            # identified reviewer must fail AT THE GATE (400 to the human), never
            # as a States.Runtime one state later with the approval half-applied.
            if not reviewer.get("reviewer_id"):
                raise ValueError("Activation blocked: reviewer.reviewer_id is required "
                                 "(ACTIVATE resolves $.activation_decision.reviewer).")
            output = {"decision": "APPROVE", "reviewer": reviewer,
                      "reason": body.get("reason", "")}
        else:
            output = {"decision": "REJECT", "reviewer": reviewer,
                      "reason": body.get("reason", "")}
    else:
        raise ValueError(f"unknown gate {gate}")
    return output


def resume_callback(build_id: str, gate: str, body: dict) -> dict:
    """Apply the human decision through the normal domain path, then resume
    the waiting execution server-side. Works locally (records RESUMED) and on
    AWS (SendTaskSuccess).

    Concurrency: the gate is CLAIMED first (WAITING -> DECIDING, enforced by the
    record version), so two reviewers acting on the same gate cannot both
    consume it — the loser gets an explicit 'already in progress' instead of a
    double-spent decision. A claim older than CLAIM_STALE_S is reclaimable so a
    crashed decider cannot brick a gate, and a decided gate that is re-fired
    (crash recovery) re-signals Step Functions with the RECORDED output and
    repeats no side effect."""
    import json as _json
    key = _cb_key(build_id, gate)
    cb, ver = get_item("callbacks.json", key)
    if not cb:
        raise KeyError(f"no waiting callback for {build_id}/{gate}")

    claimed_ver = ver
    if cb.get("status") in ("DECIDED_LOCALLY", "RESUMED"):
        output = dict(cb.get("output") or {})
    else:
        if (cb.get("status") == "DECIDING"
                and time.time() - cb.get("claimed_at", 0) < CLAIM_STALE_S):
            raise ValueError("gate decision already in progress — reload and retry")
        claim = {**cb, "status": "DECIDING", "claimed_at": time.time()}
        try:
            claimed_ver = put_item("callbacks.json", key, claim, expect=ver)
        except ConcurrencyError as e:
            raise ValueError("gate decision already in progress — reload and retry") from e
        try:
            output = _apply_gate_decision(build_id, gate, body)
        except Exception:
            # give the gate back so the reviewer can retry without waiting out
            # the stale-claim window
            try:
                put_item("callbacks.json", key,
                         {**claim, "status": "WAITING"}, expect=claimed_ver)
            except ConcurrencyError:
                pass
            raise

    sent = False
    if cb.get("task_token"):
        try:
            import boto3  # lazy
            boto3.client("stepfunctions").send_task_success(
                taskToken=cb["task_token"], output=_json.dumps(output, default=str))
            sent = True
        except Exception as e:  # noqa: BLE001
            output = {**output, "resume_error": f"{type(e).__name__}: {e}"[:200]}
    final = {**cb, "status": "RESUMED" if sent else "DECIDED_LOCALLY", "output": output}
    try:
        put_item("callbacks.json", key, final, expect=claimed_ver)
    except ConcurrencyError:
        pass  # finalize is best-effort; the decision is already durably recorded
    audit("GATE_RESUMED", {"build_id": build_id, "gate": gate, "sent_to_sfn": sent})
    return output
