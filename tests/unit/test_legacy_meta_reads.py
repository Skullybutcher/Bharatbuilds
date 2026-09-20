"""T69 — per-record primitives see pre-T58 legacy META records.

N2 finding: every live build predates T58 and exists ONLY inside the legacy
single-item META blob. `get_item`/`put_item`/`delete_item` read per-record rows
exclusively, so `set_build_archived` got None for every real build and the
console's Archive button 500'd on all 13 (reversible cleanup was impossible).
`_load` already merged META; the per-record primitives now do too:

- get_item: falls back to the blob, reporting version -1 (legacy, no guard)
- put_item: expect=0 refuses against a legacy record; the first write migrates
  the record to a real per-record row (from then on it shadows the blob)
- delete_item: removes a legacy-only record from the blob so admin purge of a
  pre-T58 build cannot silently no-op
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services import storage  # noqa: E402


class _CondFailed(Exception):
    pass


class _FakeTable:
    """Minimal DynamoDB table (mirrors test_storage_atomics)."""

    def __init__(self):
        self.rows = {}

    def get_item(self, Key, ConsistentRead=False):  # noqa: N803
        row = self.rows.get((Key["PK"], Key["SK"]))
        return {"Item": dict(row)} if row else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeValues=None):  # noqa: N803
        key = (Item["PK"], Item["SK"])
        cur = self.rows.get(key)
        if ConditionExpression:
            expect = (ExpressionAttributeValues or {}).get(":e")
            ok = ((not cur) if "attribute_not_exists" in ConditionExpression
                  else bool(cur and cur.get("ver") == expect))
            if not ok:
                raise _CondFailed()
        self.rows[key] = dict(Item)

    def delete_item(self, Key):  # noqa: N803
        self.rows.pop((Key["PK"], Key["SK"]), None)

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None,
              ConsistentRead=False, **kw):
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
def ddb(monkeypatch):
    table = _FakeTable()
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "dynamodb")
    monkeypatch.setattr(storage, "_dd", lambda: table)
    return table


def _seed_legacy(table, builds: dict):
    table.rows[("COLL#builds.json", "META")] = {
        "PK": "COLL#builds.json", "SK": "META",
        "data_json": json.dumps(builds)}
    return table


def test_get_item_falls_back_to_legacy_meta(ddb):
    _seed_legacy(ddb, {"BUILD-OLD1": {"build_id": "BUILD-OLD1", "status": "PATCH_VALIDATED"}})
    b, ver = storage.get_item("builds.json", "BUILD-OLD1")
    assert b["build_id"] == "BUILD-OLD1"
    assert ver == -1  # legacy: no version guard available
    assert storage.get_item("builds.json", "BUILD-MISSING") == (None, 0)


def test_put_item_migrates_legacy_record_and_shadows_blob(ddb):
    _seed_legacy(ddb, {"BUILD-OLD1": {"build_id": "BUILD-OLD1", "status": "DRAFT"}})
    # expect=0 must refuse: a legacy record EXISTS (create-only is honest)
    with pytest.raises(storage.ConcurrencyError):
        storage.put_item("builds.json", "BUILD-OLD1", {"build_id": "BUILD-OLD1"}, expect=0)
    # unconditional write migrates it
    storage.put_item("builds.json", "BUILD-OLD1",
                     {"build_id": "BUILD-OLD1", "status": "PATCH_VALIDATED", "archived": True})
    row = ddb.rows[("COLL#builds.json", "BUILD-OLD1")]
    assert json.loads(row["data_json"])["archived"] is True
    # and the per-record row now shadows the blob
    b, ver = storage.get_item("builds.json", "BUILD-OLD1")
    assert b["status"] == "PATCH_VALIDATED" and ver == 1


def test_set_build_archived_works_for_legacy_builds(ddb):
    """The exact live failure: archive a build that exists only in META."""
    _seed_legacy(ddb, {"BUILD-OLD1": {"build_id": "BUILD-OLD1", "status": "PATCH_VALIDATED"}})
    from services.registry.store import set_build_archived
    rec = set_build_archived("BUILD-OLD1", True)
    assert rec["archived"] is True
    b, _ = storage.get_item("builds.json", "BUILD-OLD1")
    assert b["archived"] is True


def test_delete_item_removes_legacy_only_record_from_blob(ddb):
    _seed_legacy(ddb, {"BUILD-OLD1": {"build_id": "BUILD-OLD1"},
                       "BUILD-KEEP": {"build_id": "BUILD-KEEP"}})
    assert storage.delete_item("builds.json", "BUILD-OLD1") is True
    assert storage.delete_item("builds.json", "BUILD-OLD1") is False  # idempotent
    assert storage.delete_item("builds.json", "BUILD-NEVER") is False
    remaining = json.loads(ddb.rows[("COLL#builds.json", "META")]["data_json"])
    assert "BUILD-OLD1" not in remaining and "BUILD-KEEP" in remaining
