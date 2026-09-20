"""T64 — re-verify a build from its evidence (D4).

The trust claim this pins: the deterministic pipeline (everything downstream
of the human-frozen Rule IR) reproduces a build's artifacts byte-identically.
Anyone holding the evidence can re-derive build_id, compile_key, the patched
workflow's semantic hash, patch operations, certificate, validation outcome and
witness set — and the hashes a human actually signed at Gate 2 still match.

The failure modes are pinned too: tampered stored evidence is NAMED (not
silently accepted), and a compiler version bump reports an explicit mismatch
instead of faking a pass.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services import storage  # noqa: E402
from services.api import actions  # noqa: E402
from services.governance import store as gov  # noqa: E402
from services.registry import store as reg  # noqa: E402


@pytest.fixture()
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    storage._FILE_VERSIONS.clear()
    actions.MEMO.clear()


@pytest.fixture()
def build(files):
    b = actions.canonical("research_grant")
    assert b.get("patched_workflow"), "canonical build should carry a validated patch"
    return b


def _audit_events(bid):
    from services.registry.store import audit_for
    return [e["event"] for e in audit_for(bid)]


def test_fresh_build_reverifies_clean(build):
    out = actions.reverify_build(build["build_id"])
    assert out["verified"] is True, out["mismatches"]
    assert out["mismatches"] == []
    assert all(c["match"] for c in out["checks"])
    assert out["basis"] == "accepted rule IR (deterministic — extractor excluded)"
    assert "REVERIFY_PASS" in _audit_events(build["build_id"])


def test_tampered_stored_evidence_is_named_not_accepted(build):
    bid = build["build_id"]
    tampered = {**build, "patch": {**build.get("patch", {}),
                                   "operations": [{"op": "SET", "node": "n1", "value": 0}]}}
    actions._store(tampered)
    out = actions.reverify_build(bid)
    assert out["verified"] is False
    assert "patch_operations_sha256" in out["mismatches"]
    assert "REVERIFY_FAIL" in _audit_events(bid)
    bad = next(c for c in out["checks"] if not c["match"])
    assert bad["check"] == "patch_operations_sha256"


def test_compiler_drift_reports_honest_mismatch(build, monkeypatch):
    """A compiler upgrade changes compile_key/build_id by design — re-verify
    must report the drift explicitly, never paper over it as a pass."""
    monkeypatch.setattr(reg, "COMPILER_VERSION", "9.9.9-drift")
    out = actions.reverify_build(build["build_id"])
    assert out["verified"] is False
    assert "build_id" in out["mismatches"] and "compile_key" in out["mismatches"]
    assert out["compiler_version"] == "9.9.9-drift"  # the report names what ran
    assert "REVERIFY_FAIL" in _audit_events(build["build_id"])


def test_gate2_signed_hashes_are_checked(build):
    """When an approval exists, its artifact hashes are part of the verdict."""
    bid = build["build_id"]
    art = gov._artifact_hashes(build)
    from services.storage import put_item
    put_item("approvals.json", "APR-T64-0001",
             {"approval_id": "APR-T64-0001", "build_id": bid,
              "approval_type": "PATCH_REVIEW", "decision": "APPROVE_CANDIDATE",
              "reviewer": {"reviewer_id": "USR-T64"}, "role": "PROCEDURE_OWNER",
              "reason": "test", "timestamp": 0.0, "artifacts": art}, expect=0)
    out = actions.reverify_build(bid)
    names = {c["check"] for c in out["checks"]}
    assert "approval.accepted_rule_ir_sha256" in names
    assert "approval.procedure_after_sha256" in names
    assert out["verified"] is True


def test_gate2_signed_hashes_catch_a_tamper(build):
    """The signed hash is the anchor: alter the stored IR after signing and the
    approval comparison fails even though a recompile from the (altered) IR is
    self-consistent."""
    bid = build["build_id"]
    art = gov._artifact_hashes(build)
    from services.storage import put_item
    put_item("approvals.json", "APR-T64-0002",
             {"approval_id": "APR-T64-0002", "build_id": bid,
              "approval_type": "PATCH_REVIEW", "decision": "APPROVE_CANDIDATE",
              "reviewer": {"reviewer_id": "USR-T64"}, "role": "PROCEDURE_OWNER",
              "reason": "test", "timestamp": 0.0, "artifacts": art}, expect=0)
    # alter accepted IR after signing
    altered_ir = [dict(r, _tampered=True) for r in build["new_rules"]]
    actions._store({**build, "new_rules": altered_ir})
    out = actions.reverify_build(bid)
    assert out["verified"] is False
    assert "approval.accepted_rule_ir_sha256" in out["mismatches"]


def test_refusals_fail_closed(files):
    with pytest.raises(KeyError):
        actions.reverify_build("BUILD-DOES-NOT-EXIST")
    b = actions.canonical("research_grant")
    draft = {**b, "build_id": "BUILD-DRAFT-T64", "status": "DRAFT",
             "new_rules": [], "procedure": {}}
    actions._store(draft)
    with pytest.raises(ValueError, match="no accepted rule IR"):
        actions.reverify_build("BUILD-DRAFT-T64")
