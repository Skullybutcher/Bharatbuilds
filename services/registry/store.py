"""Registry: workspaces, policy/procedure versions, builds (file-backed locally,
DynamoDB-backed on AWS via the same interface — see services/aws_kit.py).

Idempotency: compile_key = SHA256(policy_hash + procedure_hash + compiler_version).
"""
from __future__ import annotations
import hashlib
import json
import time

from services.storage import _load, _save

COMPILER_VERSION = "0.1.0"
EXTRACTOR_VERSION = "processpatch-extractor/0.1.0"
SCHEMA_VERSION = "1"

# Build identity (documented in one place):
#   build_id     = HASH(source text + procedure + compiler/extractor/schema versions)
#   compile_key  = HASH(accepted Rule IR + procedure + compiler version)
# Upgrading the compiler therefore yields a NEW build_id for the same source.


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def compile_key(policy_rules: list, procedure: dict) -> str:
    h = sha({"rules": policy_rules, "proc": procedure, "compiler": COMPILER_VERSION})[:12]
    return f"BUILD-{h.upper()}"


# ---- workspaces / versions -------------------------------------------------
def create_workspace(name: str) -> dict:
    ws = _load("workspaces.json", [])
    wid = f"WS-{len(ws) + 1:03d}"
    rec = {"workspace_id": wid, "name": name, "created_at": time.time()}
    ws.append(rec)
    _save("workspaces.json", ws)
    return rec


def save_policy_version(workspace_id: str, label: str, text: str, rules: list) -> dict:
    vers = _load("policy_versions.json", [])
    rec = {"policy_version_id": label, "workspace_id": workspace_id, "version_label": label,
           "sha256": sha(text), "rules": rules, "status": "active", "created_at": time.time()}
    vers = [v for v in vers if v.get("policy_version_id") != label] + [rec]
    _save("policy_versions.json", vers)
    return rec


SCHEMA_VERSION = "1"


def save_procedure_version(workflow: dict, status: str = "active") -> dict:
    # Immutable: an existing id is never overwritten. Callers mint unique ids
    # (patched versions embed the build hash).
    vers = _load("procedure_versions.json", [])
    pid = workflow.get("procedure_version_id", f"WF-V{len(vers) + 1}")
    if any(v.get("procedure_version_id") == pid for v in vers):
        raise ValueError(f"procedure version {pid} already exists and is immutable")
    rec = {"procedure_version_id": pid, "workflow_id": workflow.get("workflow_id"),
           "version_label": workflow.get("version_label"), "graph_json": workflow,
           "sha256": sha(workflow), "status": status, "created_at": time.time()}
    vers = vers + [rec]
    _save("procedure_versions.json", vers)
    return rec


def get_active_procedure(workflow_id: str) -> dict | None:
    vers = _load("procedure_versions.json", [])
    cands = [v for v in vers if v.get("workflow_id") == workflow_id and v.get("status") == "active"]
    return sorted(cands, key=lambda v: v.get("created_at", 0))[-1] if cands else None


def list_procedure_versions(workflow_id: str | None = None) -> list:
    vers = _load("procedure_versions.json", [])
    return [v for v in vers if workflow_id is None or v.get("workflow_id") == workflow_id]


# ---- builds ----------------------------------------------------------------
def get_build(build_id: str) -> dict | None:
    return _load("builds.json", {}).get(build_id)


def save_build(build: dict) -> dict:
    """Write ONE build record (per-record, not a whole-collection rewrite).

    This was a read-modify-write of every build in the table: two workers saving
    different builds could lose one another's writes, and each save rewrote the
    entire registry. Now a save touches only its own record (versioned by
    storage, so a lost update is detectable).
    """
    from services.storage import put_item
    put_item("builds.json", build["build_id"], build)
    return build


def find_build_by_key(key: str) -> dict | None:
    for b in _load("builds.json", {}).values():
        if b.get("compile_key") == key:
            return b
    return None


def set_build_archived(build_id: str, archived: bool = True) -> dict | None:
    """Console-level archival: the build leaves the default listing but stays
    fully readable, resumable and auditable — governance evidence is never
    destroyed. Idempotency is deliberately unaffected: an archived build still
    counts as compiled for `find_build_by_key`, because archiving hides a build
    from the working list, it does not un-happen the compile."""
    from services.storage import get_item, put_item, ConcurrencyError
    b, ver = get_item("builds.json", build_id)
    if not b:
        return None
    b["archived"] = bool(archived)
    if archived:
        b["archived_at"] = time.time()
    else:
        b.pop("archived_at", None)
    try:
        # Optimistic: only succeeds if the record is still the version we read,
        # so an archive cannot clobber a concurrent status change.
        put_item("builds.json", build_id, b, expect=ver)
    except ConcurrencyError:
        b, ver = get_item("builds.json", build_id)
        if not b:
            return None
        b["archived"] = bool(archived)
        b["archived_at"] = time.time() if archived else None
        if not archived:
            b.pop("archived_at", None)
        put_item("builds.json", build_id, b, expect=ver)
    audit("BUILD_ARCHIVED" if archived else "BUILD_UNARCHIVED", {"build_id": build_id})
    return b


def delete_build(build_id: str) -> bool:
    """HARD DELETE of a build record. Demo-operations only: the caller is the
    flagged purge path (PP_DEMO_PURGE), never a normal lifecycle operation.
    Archival (`set_build_archived`) is the supported way to retire a build;
    this exists so a demo stack can be reset, not so evidence can be erased in
    production. The caller audits the act BEFORE calling this."""
    from services.storage import delete_item
    return delete_item("builds.json", build_id)


def list_builds(include_archived: bool = False) -> list:
    builds = _load("builds.json", {})
    rows = [b for b in builds.values() if include_archived or not b.get("archived")]
    return sorted(rows, key=lambda b: b.get("created_at", 0), reverse=True)


def audit(event: str, payload: dict) -> dict:
    """Append ONE ledger record.

    This used to rewrite the whole audit file per event — under concurrent
    workers the audit trail (the one thing that must never drop a row) was the
    most race-prone write in the system: two simultaneous operations could
    silently lose one of their events. One record per event now, keyed by a
    zero-padded timestamp so list reads stay chronological."""
    import uuid
    from services.storage import put_item
    rec = {"ts": time.time(), "event": event, **payload}
    put_item("audit.json", f"{rec['ts']:.9f}-{uuid.uuid4().hex[:8]}", rec)
    return rec


def audit_for(build_id: str | None = None) -> list:
    log = _load("audit.json", [])
    return [e for e in log if build_id is None or e.get("build_id") == build_id]
