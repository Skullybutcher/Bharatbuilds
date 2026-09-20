"""T62 — the last bulk-write paths become per-record (D1 slice 3).

What changed and why the tests exist:

* procedure/policy versions, candidate rows, and patch-review pings were still
  read-modify-write over whole collections. Two workers minting the same
  procedure version could both "win" (last-writer clobbers the first graph);
  a bulk save could resurrect or drop another worker's row.
* bulk _save was delete-all-then-put-all: a crash between the two batches left
  the collection EMPTY (fail-closed reads then see zero reviews/approvals), and
  every surviving record was re-put WITHOUT version bookkeeping, silently
  downgrading it to "legacy" so later optimistic writes lost their guard.

Pinned here: create-only immutability enforced by the database (race included),
idempotent candidate re-mint adopting the winner, per-build patch-review rows,
record_id keying for candidate rows, and bulk saves that leave untouched
records — including their version bookkeeping — alone.
"""
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # share the fake table

from services import storage  # noqa: E402
from services.governance import store as gov  # noqa: E402
from services.registry import store as reg  # noqa: E402

from test_storage_atomics import _FakeTable  # noqa: E402  (shared fake table)


@pytest.fixture()
def ddb(monkeypatch):
    table = _FakeTable()
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "dynamodb")
    monkeypatch.setattr(storage, "_dd", lambda: table)
    return table


@pytest.fixture()
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    storage._FILE_VERSIONS.clear()


def _wf(pid, node_value=1):
    return {"procedure_version_id": pid, "workflow_id": "WF-1", "version_label": "v",
            "nodes": [{"id": "n1", "value": node_value}], "edges": []}


# ---- bulk save semantics ------------------------------------------------------

def test_bulk_save_leaves_untouched_records_and_their_versions_alone(ddb):
    """Old behaviour: delete everything, re-put everything without a version —
    surviving records silently became 'legacy' and lost optimistic-concurrency
    protection. Diff behaviour: unchanged records are not rewritten."""
    storage.put_item("things.json", "a", {"record_id": "a", "v": 1}, expect=0)
    storage.put_item("things.json", "b", {"record_id": "b", "v": 1}, expect=0)
    # bulk save rewrites only a; b is in the collection but unchanged
    storage._save("things.json", [{"record_id": "a", "v": 2}, {"record_id": "b", "v": 1}])
    # b's version bookkeeping survived: an optimistic write against v1 is still
    # enforced (and a stale writer is still rejected)
    _, ver_b = storage.get_item("things.json", "b")
    assert ver_b == 1
    storage.put_item("things.json", "b", {"record_id": "b", "v": 9}, expect=ver_b)
    assert storage.get_item("things.json", "b")[0]["v"] == 9
    # and a stale writer against b is still refused
    with pytest.raises(storage.ConcurrencyError):
        storage.put_item("things.json", "b", {"record_id": "b", "v": 10}, expect=ver_b)


def test_bulk_save_deletes_exactly_the_disappeared_keys(ddb):
    for rid in ("a", "b", "c"):
        storage.put_item("things.json", rid, {"record_id": rid}, expect=0)
    storage._save("things.json", [{"record_id": "a"}, {"record_id": "b"}])
    remaining = {r["record_id"] for r in storage._load("things.json", [])}
    assert remaining == {"a", "b"}  # c is gone, a and b never flickered


# ---- procedure versions: create-only immutability -----------------------------

def test_double_mint_is_refused(files):
    reg.save_procedure_version(_wf("WF-IMMUT-1"))
    with pytest.raises(ValueError, match="already exists and is immutable"):
        reg.save_procedure_version(_wf("WF-IMMUT-1", node_value=999))
    # the first graph is intact — no clobber
    saved = next(v for v in reg.list_procedure_versions()
                 if v["procedure_version_id"] == "WF-IMMUT-1")
    assert saved["graph_json"]["nodes"][0]["value"] == 1


def test_procedure_version_race_has_exactly_one_winner(ddb):
    """Eight workers mint the same id concurrently; the database condition
    decides — one winner, seven ValueErrors, one stored graph."""
    ok, refused = [], []

    def worker():
        try:
            reg.save_procedure_version(_wf("WF-RACE-1", node_value=7))
            ok.append(1)
        except ValueError:
            refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 1 and len(refused) == 7
    versions = reg.list_procedure_versions("WF-1")
    assert len(versions) == 1 and versions[0]["graph_json"]["nodes"][0]["value"] == 7


def test_missing_id_fails_closed(files):
    with pytest.raises(ValueError, match="requires procedure_version_id"):
        reg.save_procedure_version({"workflow_id": "WF-1", "nodes": []})


# ---- candidate re-mint: adopt the winner --------------------------------------

def test_remint_adopts_existing_candidate(files):
    b = {"build_id": "BUILD-M", "compile_key": "BUILD-M", "patched_workflow": _wf("WF-2-PATCHED")}
    first = gov.create_candidate_version(b)
    again = gov.create_candidate_version(b)
    assert again["procedure_version_id"] == first["procedure_version_id"]
    assert len([v for v in reg.list_procedure_versions()
                if v["status"] == "candidate"]) == 1


def test_remint_race_adopts_the_winner(ddb, monkeypatch):
    """Pre-check miss + lost create race must converge on the winner's record,
    not 500 the execution with 'already exists'."""
    b = {"build_id": "BUILD-R", "compile_key": "BUILD-R", "patched_workflow": _wf("WF-3-PATCHED")}
    tag = reg.sha("BUILD-R")[:8].upper()  # the id create_candidate_version will derive
    winner = {**_wf(f"WF-3-PATCH-{tag}"), "status": "candidate"}
    calls = {"list": 0, "save": 0}

    def fake_list(workflow_id=None):
        calls["list"] += 1
        return [winner] if calls["list"] >= 2 else []  # winner lands after the pre-check

    def fake_save(workflow, status="active"):
        calls["save"] += 1
        raise ValueError(f"procedure version {winner['procedure_version_id']} already exists and is immutable")

    monkeypatch.setattr(reg, "list_procedure_versions", fake_list)
    monkeypatch.setattr(reg, "save_procedure_version", fake_save)
    out = gov.create_candidate_version(b)
    assert out["procedure_version_id"] == winner["procedure_version_id"]
    assert calls["save"] == 1 and calls["list"] >= 2


# ---- patch reviews: one row per build ------------------------------------------

def test_patch_review_replaces_only_its_own_row(files):
    gov.request_patch_review("BUILD-A", "h1")
    gov.request_patch_review("BUILD-B", "h2")
    gov.request_patch_review("BUILD-A", "h3")  # fresh request supersedes A's row
    rows = storage._load("patch_reviews.json", [])
    assert len(rows) == 2
    a = next(r for r in rows if r["build_id"] == "BUILD-A")
    b = next(r for r in rows if r["build_id"] == "BUILD-B")
    assert a["opened_hash"] == "h3" and b["opened_hash"] == "h2"


# ---- candidates: record_id keying ----------------------------------------------

def test_candidate_rows_survive_bulk_save_and_purge_scopes_correctly(files):
    storage.put_item("candidates.json", "B1#WF-P1",
                     {"record_id": "B1#WF-P1", "build_id": "B1", "status": "candidate"}, expect=0)
    gov._mark_candidate({"build_id": "B1"}, "inactive")       # same build, other status
    storage.put_item("candidates.json", "B2#WF-P2",
                     {"record_id": "B2#WF-P2", "build_id": "B2", "status": "candidate"}, expect=0)
    # a bulk save (the purge path's writer) must not collapse B1's two rows
    rows = storage._load("candidates.json", [])
    storage._save("candidates.json", rows)
    ids = {r["record_id"] for r in storage._load("candidates.json", [])}
    assert ids == {"B1#WF-P1", "B1#inactive", "B2#WF-P2"}
    # purge B1 removes exactly B1's rows
    removed = gov.purge_build_records("B1")
    assert removed.get("candidates.json") == 2
    assert [r["record_id"] for r in storage._load("candidates.json", [])] == ["B2#WF-P2"]


# ---- activation flip: per-record, no collection rewrite ------------------------

def test_activation_flip_writes_each_record_independently(ddb):
    """The flip must not resurrect or delete sibling versions: supersede the
    old active, activate the candidate, leave other workflows untouched."""
    tag = reg.sha("BUILD-F")[:8].upper()  # candidate id derived by create_candidate_version
    cid = f"WF-9-V1-PATCH-{tag}"
    patched = {**_wf("WF-9-V1-PATCHED"), "status": "candidate"}
    # records mirror the real version-record shape (graph under graph_json)
    reg.put_item("procedure_versions.json", "WF-9-V1",
                 {"procedure_version_id": "WF-9-V1", "workflow_id": "WF-1",
                  "graph_json": _wf("WF-9-V1"), "status": "active"}, expect=0)
    reg.put_item("procedure_versions.json", cid,
                 {"procedure_version_id": cid, "workflow_id": "WF-1",
                  "graph_json": patched, "status": "candidate"}, expect=0)
    reg.put_item("procedure_versions.json", "OTHER-V1",
                 {"procedure_version_id": "OTHER-V1", "workflow_id": "WF-OTHER",
                  "graph_json": _wf("OTHER-V1"), "status": "active"}, expect=0)

    build = {"build_id": "BUILD-F", "compile_key": "BUILD-F",
             "patched_workflow": patched,
             "new_rules": [], "procedure": {}, "patch": {"operations": []},
             "certificate": {}, "validation": {"status": "VALIDATED_WITHIN_TESTED_MODEL",
                                               "results": []},
             "impact": {"verification": {"provenance_coverage": 1.0}}}
    gov.decide_patch("BUILD-F", build, "APPROVE_CANDIDATE",
                     {"reviewer_id": "USR-1"}, "ok")
    out = gov.activate_procedure("BUILD-F", build, {"reviewer_id": "USR-1"}, "go")
    assert out["procedure_version"]["status"] == "active"
    by_id = {v["procedure_version_id"]: v.get("status")
             for v in storage._load("procedure_versions.json", [])}
    assert by_id["WF-9-V1"] == "superseded"
    assert by_id[cid] == "active"
    assert by_id["OTHER-V1"] == "active"  # untouched workflow not swept up
