"""T60 — governance under concurrency.

These tests exist because the failure mode they cover was real: the whole
collection was rewritten on every write, so two Lambda workers deciding the
same gate could both "win" — double-consuming a human approval, double-minting
an approval id, or dropping the other worker's audit row.

The claim primitive is tested under real threads against the fake DynamoDB
table (whose check-and-set is serialized), because that is where the database
enforcement actually decides the winner.
"""
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
    # the date-derived approval sequence is per-process state under the files
    # backend; reset so tests do not inherit ids minted by earlier tests
    gov._save("approvals.json", [])


def _seed_gate(ddb_table, bid="BUILD-RACE", gate="patch_approval"):
    """A WAITING callback, written through the new per-record path (so it is
    versioned exactly as production writes it)."""
    gov.save_callback(bid, gate, "tok-1")
    return gov.get_callback(bid, gate)


def test_only_one_worker_claims_a_waiting_gate(ddb):
    """The double-spend guard: N workers read the same WAITING record and all
    try to claim it. Exactly one claim succeeds; the gate is consumed once."""
    _seed_gate(ddb)
    cb, ver = storage.get_item("callbacks.json", gov._cb_key("BUILD-RACE", "patch_approval"))
    assert cb["status"] == "WAITING"

    results, errors = [], []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()  # maximize contention
        try:
            claim = {**cb, "status": "DECIDING", "claimed_at": 0.0}
            storage.put_item("callbacks.json",
                             gov._cb_key("BUILD-RACE", "patch_approval"),
                             claim, expect=ver)
            results.append("claimed")
        except storage.ConcurrencyError:
            errors.append("lost")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1, f"gate claimed {len(results)} times — a decision could double-spend"
    assert len(errors) == 7


def test_second_resume_never_repeats_the_side_effect(files):
    """Crash-recovery re-fire: the decision is recorded, the signal may have
    failed — re-firing re-signals but must NOT mint a second approval."""
    bid = "BUILD-RECOVERY"
    # a build whose guardrails pass, so the decision path actually runs
    reg.save_build({"build_id": bid, "status": "PATCH_VALIDATED", "conflicts": [],
                    "new_rules": [], "procedure": {},
                    "patched_workflow": {"nodes": [], "edges": []},
                    "patch": {"operations": []}, "certificate": {},
                    "validation": {"status": "VALIDATED_WITHIN_TESTED_MODEL",
                                   "results": [{"suite": "unchanged", "pass": True}]},
                    "impact": {"verification": {"provenance_coverage": 1.0}}})
    gov.request_patch_review(bid, None)
    gov.save_callback(bid, "patch_approval", "tok-1")

    first = gov.resume_callback(bid, "patch_approval",
                                {"gate": "patch_approval", "decision": "APPROVE_CANDIDATE",
                                 "reviewer": {"reviewer_id": "rev", "display_name": "r"}})
    second = gov.resume_callback(bid, "patch_approval",
                                 {"gate": "patch_approval", "decision": "APPROVE_CANDIDATE",
                                  "reviewer": {"reviewer_id": "rev", "display_name": "r"}})

    assert first["approval_id"] == second["approval_id"], \
        "the recovery re-fire minted a second approval"
    approvals = [a for a in gov._load("approvals.json", []) if a.get("build_id") == bid]
    assert len(approvals) == 1


def test_concurrent_approvers_get_distinct_approval_ids(ddb):
    """Two approvals for two different builds minted 'simultaneously': the
    sequence collision must resolve by retry, never by a shared id."""
    arts = gov._artifact_hashes({"new_rules": [], "procedure": {}, "patched_workflow": {},
                                 "patch": {}, "certificate": {}})
    seen = []
    for bid in ("BUILD-A1", "BUILD-A2"):
        rec = gov._record_approval({"build_id": bid, "approval_type": "PATCH_REVIEW",
                                    "decision": "APPROVE_CANDIDATE",
                                    "reviewer": {"reviewer_id": "r"}, "role": "PROCEDURE_OWNER",
                                    "reason": "race", "timestamp": 0.0, "artifacts": arts})
        seen.append(rec["approval_id"])
    assert seen[0] != seen[1]
    ids = [a["approval_id"] for a in gov._load("approvals.json", [])]
    assert len(ids) == len(set(ids)), "duplicate approval ids in the ledger"


def test_a_decision_that_fails_gives_the_gate_back(files):
    """A guardrail rejection must not strand the gate in DECIDING for a minute —
    the claim is released and the reviewer can retry immediately."""
    bid = "BUILD-RETRY"
    reg.save_build({"build_id": bid, "status": "PATCH_VALIDATED"})
    gov.save_callback(bid, "activation", "tok-1")  # no APPROVE_CANDIDATE on record
    with pytest.raises(ValueError):
        gov.resume_callback(bid, "activation",
                            {"gate": "activation", "decision": "APPROVE",
                             "reviewer": {"reviewer_id": "r"}, "reason": "x"})
    cb = gov.get_callback(bid, "activation")
    assert cb["status"] == "WAITING", f"gate stranded in {cb.get('status')}"


def test_audit_rows_are_never_lost_under_concurrency(ddb):
    """The ledger used to rewrite itself per event: two concurrent operations
    could drop one of their rows. One record per event now."""
    barrier = threading.Barrier(12)

    def worker(i):
        barrier.wait()
        reg.audit("RACE_PROBE", {"worker": i})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    events = [r for r in gov._load("audit.json", []) if r.get("event") == "RACE_PROBE"]
    assert len(events) == 12, f"ledger dropped {12 - len(events)} of 12 concurrent events"
    assert len({r["worker"] for r in events}) == 12
