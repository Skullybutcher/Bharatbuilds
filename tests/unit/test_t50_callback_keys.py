"""T50 — callback records must not collide in the DynamoDB single-table design.

The live failure: save_callback keyed items on build_id alone, so the second
gate a build arms produced two items with the same SK. BatchWriteItem rejects
duplicate keys ("Provided list of item keys contains duplicates"), the wait
state's Lambda invocation died, and the execution FAILED between Gate 2 and
Gate 3 — with the human approval already recorded.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services import storage  # noqa: E402


def _cb(bid, gate, token="tok"):
    return {"build_id": bid, "gate": gate, "task_token": token,
            "status": "WAITING", "timestamp": 0.0}


def test_two_gates_one_build_get_distinct_sks():
    """The exact live shape: DECIDED record + WAITING record for one build."""
    cbs = [_cb("BUILD-X", "patch_approval"), _cb("BUILD-X", "activation")]
    sks = [sk for sk, _ in storage._sks("callbacks.json", cbs)]
    assert len(sks) == 2, f"gate records collapsed into one SK: {sks}"
    assert len(set(sks)) == 2, f"duplicate SKs would 400 BatchWriteItem: {sks}"


def test_same_gate_rearm_is_last_wins():
    """save_callback replaces in-list; SK assignment must agree (last-wins)."""
    cbs = [_cb("BUILD-X", "patch_approval", "old-token"),
           _cb("BUILD-X", "patch_approval", "new-token")]
    items = storage._sks("callbacks.json", cbs)
    assert len(items) == 1
    assert items[0][1]["task_token"] == "new-token"


def test_other_collections_keep_their_id_derivation():
    """The composite rule is scoped to callbacks; nothing else may shift SKs."""
    rec = {"build_id": "BUILD-Y"}  # e.g. a registry record without its own id
    assert storage._item_id("builds.json", rec, 0) == "BUILD-Y"
    # review records still key on their own id, not the composite
    rev = {"review_id": "REV-1", "build_id": "BUILD-Y", "gate": "rule_review"}
    assert storage._item_id("reviews.json", rev, 0) == "REV-1"


def test_gateless_record_with_build_id_unchanged():
    assert storage._item_id("anything.json", {"build_id": "BUILD-Z"}, 0) == "BUILD-Z"
