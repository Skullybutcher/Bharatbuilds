"""T58 — per-record storage with optimistic concurrency.

Before this, every save rewrote a whole collection (batch delete + batch put)
and callers did read-modify-write. Under concurrent Lambda workers that means:
two saves of different records can lose one another, a failed batch leaves a
partially deleted collection, and a build registry that is one META item hits
DynamoDB's 400 KB ceiling. These tests pin the replacement:

  * one record per write item (put_item / delete_item),
  * an `expect=` version that the DATABASE enforces, so a writer holding a stale
    read fails loudly (ConcurrencyError) instead of clobbering the other writer,
  * dict collections stored per record, with the legacy META blob still readable
    and retired by the next write.

The DynamoDB path is covered with a fake table that implements the condition
semantics — that is where the race is actually won or lost.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services import storage  # noqa: E402
from services.registry import store as reg  # noqa: E402


class _CondFailed(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _FakeTable:
    """Minimal DynamoDB table: enough to exercise our own logic, including the
    ConditionExpression we rely on for the version check."""

    def __init__(self):
        self.rows = {}

    def get_item(self, Key, ConsistentRead=False):  # noqa: N803
        row = self.rows.get((Key["PK"], Key["SK"]))
        return {"Item": dict(row)} if row else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeValues=None):  # noqa: N803
        key = (Item["PK"], Item["SK"])
        cur = self.rows.get(key)
        if ConditionExpression:
            expect = ExpressionAttributeValues[":e"]
            ok = (not cur) if expect == 0 else bool(cur and cur.get("ver") == expect)
            if not ok:
                raise _CondFailed()
        self.rows[key] = dict(Item)

    def delete_item(self, Key):  # noqa: N803
        self.rows.pop((Key["PK"], Key["SK"]), None)

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ConsistentRead=False, **kw):
        pk = ExpressionAttributeValues[":pk"]
        return {"Items": [dict(r) for (p, _), r in self.rows.items() if p == pk]}

    def batch_writer(self):
        table = self

        class _Batch:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def delete_item(self, Key):  # noqa: N803
                table.delete_item(Key)

            def put_item(self, Item):  # noqa: N803
                table.put_item(Item)

        return _Batch()


@pytest.fixture()
def files_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    storage._FILE_VERSIONS.clear()
    return tmp_path


@pytest.fixture()
def ddb_backend(monkeypatch):
    table = _FakeTable()
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "dynamodb")
    monkeypatch.setattr(storage, "_dd", lambda: table)
    return table


# ---- versioning semantics (both backends) ------------------------------------

@pytest.mark.parametrize("backend", ["files", "ddb"])
def test_create_only_then_versioned_update(backend, request):
    request.getfixturevalue("files_backend" if backend == "files" else "ddb_backend")
    assert storage.get_item("builds.json", "BUILD-1") == (None, 0)
    v1 = storage.put_item("builds.json", "BUILD-1", {"build_id": "BUILD-1", "n": 1}, expect=0)
    assert v1 == 1
    # a second create-only write must fail: something is already there
    with pytest.raises(storage.ConcurrencyError):
        storage.put_item("builds.json", "BUILD-1", {"build_id": "BUILD-1", "n": 2}, expect=0)
    payload, ver = storage.get_item("builds.json", "BUILD-1")
    assert payload["n"] == 1 and ver == 1
    assert storage.put_item("builds.json", "BUILD-1", {"build_id": "BUILD-1", "n": 3}, expect=ver) == 2


@pytest.mark.parametrize("backend", ["files", "ddb"])
def test_stale_writer_cannot_clobber(backend, request):
    """The lost-update case: two readers, one write each, second must fail."""
    request.getfixturevalue("files_backend" if backend == "files" else "ddb_backend")
    storage.put_item("builds.json", "BUILD-2", {"build_id": "BUILD-2", "status": "A"}, expect=0)
    reader, ver = storage.get_item("builds.json", "BUILD-2")   # both workers read v1
    storage.put_item("builds.json", "BUILD-2", {**reader, "status": "B"}, expect=ver)
    with pytest.raises(storage.ConcurrencyError):
        storage.put_item("builds.json", "BUILD-2", {**reader, "status": "C"}, expect=ver)
    assert storage.get_item("builds.json", "BUILD-2")[0]["status"] == "B"


@pytest.mark.parametrize("backend", ["files", "ddb"])
def test_delete_item_reports_whether_anything_was_there(backend, request):
    request.getfixturevalue("files_backend" if backend == "files" else "ddb_backend")
    storage.put_item("builds.json", "BUILD-3", {"build_id": "BUILD-3"}, expect=0)
    assert storage.delete_item("builds.json", "BUILD-3") is True
    assert storage.delete_item("builds.json", "BUILD-3") is False
    assert storage.get_item("builds.json", "BUILD-3") == (None, 0)


# ---- dict collections: per record, legacy blob still readable ----------------

def test_builds_are_stored_per_record_not_one_blob(ddb_backend):
    reg.save_build({"build_id": "BUILD-A", "status": "X"})
    reg.save_build({"build_id": "BUILD-B", "status": "Y"})
    keys = [sk for (_, sk) in ddb_backend.rows if sk != storage.META_SK]
    assert sorted(keys) == ["BUILD-A", "BUILD-B"]
    assert not any(sk == storage.META_SK for (_, sk) in ddb_backend.rows), \
        "a new write must not recreate the single-item blob"


def test_saving_one_build_leaves_the_others_alone(ddb_backend):
    reg.save_build({"build_id": "BUILD-A", "status": "X"})
    before = dict(ddb_backend.rows[("COLL#builds.json", "BUILD-A")])
    reg.save_build({"build_id": "BUILD-B", "status": "Y"})
    assert ddb_backend.rows[("COLL#builds.json", "BUILD-A")] == before


def test_legacy_meta_blob_still_reads_and_is_retired_by_the_next_bulk_write(ddb_backend):
    # a stack written by the old single-item design
    ddb_backend.put_item(Item={"PK": "COLL#builds.json", "SK": storage.META_SK,
                               "data_json": json.dumps({"BUILD-OLD": {"build_id": "BUILD-OLD",
                                                                     "status": "LEGACY"}}),
                               "GSI_PK": "COLL", "GSI_SK": "builds.json"})
    assert reg.get_build("BUILD-OLD")["status"] == "LEGACY"
    # per-record rows win over the legacy blob for the same key
    reg.save_build({"build_id": "BUILD-OLD", "status": "NEW"})
    assert reg.get_build("BUILD-OLD")["status"] == "NEW"
    assert [b["build_id"] for b in reg.list_builds()] == ["BUILD-OLD"]
    # a bulk save (seed/migration path) migrates everything and drops the blob
    storage._save("builds.json", {"BUILD-OLD": {"build_id": "BUILD-OLD", "status": "MIGRATED"}})
    assert not any(sk == storage.META_SK for (_, sk) in ddb_backend.rows)
    assert reg.get_build("BUILD-OLD")["status"] == "MIGRATED"


# ---- registry paths that used to rewrite everything --------------------------

def test_archive_is_optimistic(files_backend, monkeypatch):
    reg.save_build({"build_id": "BUILD-Z", "status": "PATCH_VALIDATED"})
    payload, ver = storage.get_item("builds.json", "BUILD-Z")
    # a concurrent writer changes the record behind our back
    monkeypatch.setattr(storage, "get_item", lambda n, i: (payload, ver))
    reg.set_build_archived("BUILD-Z")  # archive proceeds against what it read
    assert reg.get_build("BUILD-Z")["archived"] is True


def test_delete_build_removes_only_that_record(files_backend):
    reg.save_build({"build_id": "BUILD-K1", "status": "A"})
    reg.save_build({"build_id": "BUILD-K2", "status": "B"})
    assert reg.delete_build("BUILD-K1") is True
    assert reg.get_build("BUILD-K1") is None
    assert reg.get_build("BUILD-K2")["status"] == "B"
