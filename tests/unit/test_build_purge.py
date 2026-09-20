"""T55 — the flagged hard-purge path.

Archival is the supported way to retire a build. A demo stack sometimes needs a
true reset, so there is exactly one hard-delete route, and it is:
  * REFUSED unless PP_DEMO_PURGE is set on the stack (never one env var away
    from production behaviour),
  * admin-only via authz (`_needs_admin`),
  * audited BEFORE the evidence disappears, so the act stays on record,
  * scoped: procedure versions (the shared registry) are never touched.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services import storage  # noqa: E402
from services.api import actions, authz  # noqa: E402
from services.governance import store as gov  # noqa: E402
from services.registry import store as reg  # noqa: E402


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    monkeypatch.delenv("PP_DEMO_PURGE", raising=False)
    bid = "BUILD-PURGE"
    reg.save_build({"build_id": bid, "created_at": 1, "status": "PATCH_VALIDATED",
                    "compile_key": "purge-me"})
    gov._save("approvals.json", [{"build_id": bid, "approval_id": "APR-1",
                                  "decision": "APPROVE_CANDIDATE"}])
    gov._save("callbacks.json", [{"build_id": bid, "gate": "activation",
                                  "task_token": "t", "status": "WAITING"}])
    gov._save("procedure_versions.json", [{"procedure_version_id": "WF-V3", "status": "active"}])
    return bid


def test_purge_is_refused_unless_the_flag_is_set(seeded):
    with pytest.raises(PermissionError) as e:
        actions.purge_build(seeded)
    assert "PP_DEMO_PURGE" in str(e.value)
    assert reg.get_build(seeded) is not None  # nothing happened


def test_purge_removes_the_build_and_its_governance_rows(seeded, monkeypatch):
    monkeypatch.setenv("PP_DEMO_PURGE", "1")
    out = actions.purge_build(seeded)
    assert out["deleted"] is True
    assert reg.get_build(seeded) is None
    assert out["records_removed"].get("approvals.json") == 1
    assert out["records_removed"].get("callbacks.json") == 1
    # the shared registry is never part of a build purge
    assert gov._load("procedure_versions.json", []) != []


def test_purge_is_audited_before_the_evidence_goes(seeded, monkeypatch):
    monkeypatch.setenv("PP_DEMO_PURGE", "1")
    actions.purge_build(seeded, {"reviewer_id": "aman"})
    events = [r for r in reg._load("audit.json", []) if r.get("event") == "BUILD_PURGED"]
    assert events and events[0]["build_id"] == seeded and events[0]["by"] == "aman"


def test_partial_purge_keeps_governance_rows(seeded, monkeypatch):
    monkeypatch.setenv("PP_DEMO_PURGE", "1")
    out = actions.purge_build(seeded, {"full": False})
    assert out["deleted"] is True
    assert out["records_removed"] == {}
    assert [a for a in gov._load("approvals.json", []) if a["build_id"] == seeded]


def test_purging_an_unknown_build_is_a_lookup_failure(seeded, monkeypatch):
    monkeypatch.setenv("PP_DEMO_PURGE", "1")
    with pytest.raises(KeyError):
        actions.purge_build("BUILD-NOPE")


def test_authorization_shape_of_the_maintenance_routes():
    # retiring a build: reviewers and admins
    assert authz._writable("POST", "/builds/BUILD-X/archive") is True
    assert authz._writable("POST", "/builds/BUILD-X/unarchive") is True
    # destroying one: admins only, regardless of the runtime flag
    assert authz._needs_admin("POST", "/builds/BUILD-X/purge", {}) is True
    assert authz._writable("POST", "/builds/BUILD-X/purge") is False
