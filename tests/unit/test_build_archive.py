"""T54 — archival: a build can leave the working list without its evidence
being destroyed.

Archival is the console's answer to "this build is debug noise / retired", and
it must NOT be deletion: governance evidence stays readable, resumable and
auditable, and the operation is reversible. These tests pin that contract.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services import storage  # noqa: E402
from services.api import actions  # noqa: E402
from services.registry import store as reg  # noqa: E402


@pytest.fixture()
def two_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    reg.save_build({"build_id": "BUILD-KEEP", "created_at": 2, "compile_key": "keep",
                    "status": "PATCH_ACTIVE"})
    reg.save_build({"build_id": "BUILD-DEBUG", "created_at": 1, "compile_key": "debug",
                    "status": "PATCH_VALIDATED"})
    return "BUILD-DEBUG"


def _ids(payload):
    return [b["build_id"] for b in payload["builds"]]


def test_archived_build_leaves_the_default_listing(two_builds):
    bid = two_builds
    assert set(_ids(actions.list_builds())) == {"BUILD-KEEP", "BUILD-DEBUG"}
    actions.archive_build(bid)
    assert _ids(actions.list_builds()) == ["BUILD-KEEP"]
    # ...and comes back when explicitly asked for
    assert set(_ids(actions.list_builds(include_archived=True))) == {"BUILD-KEEP", "BUILD-DEBUG"}


def test_archive_is_reversible_and_audited(two_builds):
    bid = two_builds
    actions.archive_build(bid)
    actions.unarchive_build(bid)
    assert set(_ids(actions.list_builds())) == {"BUILD-KEEP", "BUILD-DEBUG"}
    events = [r.get("event") for r in reg._load("audit.json", [])]
    assert "BUILD_ARCHIVED" in events and "BUILD_UNARCHIVED" in events


def test_archived_build_stays_readable_as_evidence(two_builds):
    bid = two_builds
    actions.archive_build(bid)
    view = actions.get_build_view(bid)  # by id: still fully addressable
    assert view is not None and view["build_id"] == bid
    assert view.get("archived") is True


def test_archiving_does_not_un_happen_idempotency(two_builds):
    """Documented semantics: archiving hides a build from the console list; it
    does not pretend the compile never happened."""
    bid = two_builds
    actions.archive_build(bid)
    assert reg.find_build_by_key("debug") is not None


def test_archiving_an_unknown_build_is_a_lookup_failure(two_builds):
    with pytest.raises(KeyError):
        actions.archive_build("BUILD-NOPE")
