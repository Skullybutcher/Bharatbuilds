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
from services.storage import _load, _save
from services.registry.store import audit, sha

ROLES = {"POLICY_REVIEWER", "PROCEDURE_OWNER", "FINAL_APPROVER"}
PROVENANCE_THRESHOLD = 1.0


def _rid(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000) % 100000000:08d}"


# ---- Gate 1: rule reviews ---------------------------------------------------
def open_rule_reviews(build_id: str, rules: list[dict]) -> list[dict]:
    reviews = _load("rule_reviews.json", [])
    out = []
    for r in rules:
        rec = {"review_id": _rid("REV"), "build_id": build_id, "rule_id": r.get("rule_id"),
               "decision": "PENDING", "machine_value": r,
               "human_value": None, "reason": None, "timestamp": None}
        reviews.append(rec)
        out.append(rec)
    _save("rule_reviews.json", reviews)
    audit("RULE_REVIEW_PENDING", {"build_id": build_id, "count": len(out)})
    return out


def rule_reviews(build_id: str) -> list[dict]:
    return [r for r in _load("rule_reviews.json", []) if r.get("build_id") == build_id]


def review_rule(build_id: str, rule_id: str, decision: str, human_value: dict | None = None,
                reason: str | None = None, reviewer: str = "USR-001") -> dict:
    assert decision in ("ACCEPT", "EDIT", "REJECT", "ESCALATE"), decision
    reviews = _load("rule_reviews.json", [])
    for rec in reviews:
        if rec.get("build_id") == build_id and rec.get("rule_id") == rule_id:
            rec.update({"decision": decision,
                        "human_value": human_value if decision == "EDIT" else None,
                        "reason": reason, "reviewer": reviewer, "timestamp": time.time()})
            _save("rule_reviews.json", reviews)
            audit(f"RULE_{decision}", {"build_id": build_id, "rule_id": rule_id, "reviewer": reviewer})
            return rec
    raise KeyError(f"no review for {rule_id} in {build_id}")


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
    return {"policy_hash": sha(build.get("new_rules", [])),
            "procedure_before_hash": sha(build.get("procedure", {})),
            "procedure_after_hash": sha((build.get("patch", {}) or {}).get("patched_workflow", {})),
            "patch_hash": sha((build.get("patch", {}) or {}).get("operations", [])),
            "certificate_hash": sha(build.get("certificate", {}))}


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
    reqs = _load("patch_reviews.json", [])
    rec = {"build_id": build_id, "status": "PATCH_REVIEW_PENDING",
           "opened_hash": reviewer_opened_hash, "timestamp": time.time()}
    reqs = [r for r in reqs if r.get("build_id") != build_id] + [rec]
    _save("patch_reviews.json", reqs)
    return rec


def decide_patch(build_id: str, build: dict, decision: str, reviewer: dict,
                 reason: str, role: str = "PROCEDURE_OWNER") -> dict:
    assert decision in ("APPROVE_CANDIDATE", "REJECT_PATCH", "REQUEST_REVISION"), decision
    assert role in ROLES, role
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
    rec = {"approval_id": f"APR-{time.strftime('%Y%m%d')}-{len(approvals) + 1:04d}",
           "build_id": build_id, "approval_type": "PATCH_REVIEW",
           "reviewer": reviewer, "role": role, "decision": decision, "reason": reason,
           "timestamp": time.time(), "artifacts": _artifact_hashes(build)}
    approvals.append(rec)
    _save("approvals.json", approvals)
    audit(f"PATCH_{decision}", {"build_id": build_id, "approval_id": rec["approval_id"]})
    if decision == "REJECT_PATCH":
        _mark_candidate(build, "inactive")
    if decision == "APPROVE_CANDIDATE":
        rec["candidate_version_id"] = create_candidate_version(build)["procedure_version_id"]
    return rec


def create_candidate_version(build: dict) -> dict:
    """Gate-2 side effect: persist the validated patch as a candidate procedure
    version. Returns the version record; the UI must activate THIS id — no
    hardcoded version names."""
    from services.registry.store import save_procedure_version
    candidate = (build.get("patch", {}) or {}).get("patched_workflow", {})
    saved = save_procedure_version({**candidate, "status": "candidate"}, status="candidate")
    audit("CANDIDATE_CREATED", {"build_id": build.get("build_id"),
                                "procedure_version_id": saved.get("procedure_version_id")})
    return saved


def activate_procedure(build_id: str, build: dict, reviewer: dict, reason: str) -> dict:
    """Gate 3: server-side hash verification before activation."""
    approvals = [a for a in _load("approvals.json", []) if a.get("build_id") == build_id]
    if not any(a.get("decision") == "APPROVE_CANDIDATE" for a in approvals):
        raise ValueError("Activation blocked: no APPROVE_CANDIDATE on record.")
    approved_hashes = [a["artifacts"] for a in approvals if a.get("decision") == "APPROVE_CANDIDATE"][-1]
    if approved_hashes != _artifact_hashes(build):
        audit("APPROVAL_INVALIDATED", {"build_id": build_id})
        raise ValueError("APPROVAL INVALIDATED: Artifact changed since review. Reload required.")
    from services.registry.store import save_procedure_version
    candidate = (build.get("patch", {}) or {}).get("patched_workflow", {})
    saved = save_procedure_version({**candidate, "status": "active"}, status="active")
    # deactivate superseded versions of the same workflow
    vers = _load("procedure_versions.json", [])
    for v in vers:
        if v.get("workflow_id") == saved.get("workflow_id") and \
           v.get("procedure_version_id") != saved.get("procedure_version_id"):
            v["status"] = "superseded"
    _save("procedure_versions.json", vers)
    rec = {"approval_id": f"APR-{time.strftime('%Y%m%d')}-{len(approvals) + 1:04d}",
           "build_id": build_id, "approval_type": "PROCEDURE_ACTIVATION",
           "reviewer": reviewer, "role": "FINAL_APPROVER", "decision": "APPROVE",
           "reason": reason, "timestamp": time.time(), "artifacts": _artifact_hashes(build)}
    approvals_all = _load("approvals.json", [])
    approvals_all.append(rec)
    _save("approvals.json", approvals_all)
    audit("PROCEDURE_ACTIVATED", {"build_id": build_id,
                                 "procedure_version_id": saved.get("procedure_version_id")})
    return {"approval": rec, "procedure_version": saved}


def _mark_candidate(build: dict, status: str) -> None:
    cands = _load("candidates.json", [])
    cands.append({"build_id": build.get("build_id"), "status": status, "ts": time.time()})
    _save("candidates.json", cands)


def approvals_for(build_id: str) -> list:
    return [a for a in _load("approvals.json", []) if a.get("build_id") == build_id]


# ---- Step Functions human-gate callbacks ------------------------------------
def save_callback(build_id: str, gate: str, task_token: str | None,
                  execution_arn: str | None = None) -> dict:
    """Persist the taskToken at WAIT time so a later human action can resume
    the execution WITHOUT the client ever holding the token."""
    cbs = _load("callbacks.json", [])
    rec = {"build_id": build_id, "gate": gate, "task_token": task_token,
           "execution_arn": execution_arn, "status": "WAITING", "timestamp": time.time()}
    cbs = [c for c in cbs if not (c.get("build_id") == build_id and c.get("gate") == gate)] + [rec]
    _save("callbacks.json", cbs)
    audit("GATE_WAITING", {"build_id": build_id, "gate": gate})
    return rec


def get_callback(build_id: str, gate: str) -> dict | None:
    return next((c for c in _load("callbacks.json", [])
                 if c.get("build_id") == build_id and c.get("gate") == gate), None)


def resume_callback(build_id: str, gate: str, body: dict) -> dict:
    """Apply the human decision through the normal domain path, then resume
    the waiting execution server-side. Works locally (records RESUMED) and on
    AWS (SendTaskSuccess)."""
    import json as _json
    cb = get_callback(build_id, gate)
    if not cb:
        raise KeyError(f"no waiting callback for {build_id}/{gate}")
    output: dict
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
        from services.registry.store import get_build
        build = get_build(build_id) or {}
        if body.get("decision") == "APPROVE":
            out = activate_procedure(build_id, build, body.get("reviewer", {}), body.get("reason", ""))
            output = {"decision": "APPROVE",
                      "procedure_version_id": out["procedure_version"]["procedure_version_id"]}
        else:
            output = {"decision": "REJECT"}
    else:
        raise ValueError(f"unknown gate {gate}")

    sent = False
    if cb.get("task_token"):
        try:
            import boto3  # lazy
            boto3.client("stepfunctions").send_task_success(
                taskToken=cb["task_token"], taskOutput=_json.dumps(output, default=str))
            sent = True
        except Exception as e:  # noqa: BLE001
            output["resume_error"] = f"{type(e).__name__}: {e}"[:200]
    cbs = [c for c in _load("callbacks.json", [])
           if not (c.get("build_id") == build_id and c.get("gate") == gate)]
    _save("callbacks.json", cbs + [{**cb, "status": "RESUMED" if sent else "DECIDED_LOCALLY",
                                    "output": output}])
    audit("GATE_RESUMED", {"build_id": build_id, "gate": gate, "sent_to_sfn": sent})
    return output
