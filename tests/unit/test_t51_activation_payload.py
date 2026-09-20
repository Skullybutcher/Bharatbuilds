"""T51 — the activation gate payload must satisfy the ACTIVATE state contract.

Live failure (attempt 15): Gate 2 cleared, Gate 3 armed and APPROVED, the state
machine reached ACTIVATE and died with

    States.Runtime: JSONPath '$.activation_decision.reviewer' ... could not be found

because resume_callback's activation branch emitted only {"decision": "APPROVE"}.
The wait state's output IS that dict, so the human's reviewer/reason never
reached the activation side effect. The last test derives the required keys
from the ASL so this contract cannot silently drift again.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services import storage  # noqa: E402
from services.governance import store as gov  # noqa: E402
from services.registry import store as reg  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    bid = "BUILD-T51"
    reg.save_build({"build_id": bid, "status": "PATCH_VALIDATED", "compile_key": "k"})
    gov._save("approvals.json", [{"build_id": bid, "approval_id": "APR-1",
                                  "decision": "APPROVE_CANDIDATE",
                                  "candidate_version_id": "WF-V3-PATCH-X",
                                  "reviewer": {"reviewer_id": "rev"}, "artifacts": {}}])
    gov.save_callback(bid, "activation", "tok-1")
    return bid


def _approve(bid, reviewer, reason="cloud-e2e"):
    return gov.resume_callback(bid, "activation",
                               {"gate": "activation", "decision": "APPROVE",
                                "reviewer": reviewer, "reason": reason})


def test_activation_output_carries_reviewer_and_reason(seeded):
    out = _approve(seeded, {"reviewer_id": "demo-admin", "display_name": "demo"})
    assert out["decision"] == "APPROVE"
    assert out["reviewer"]["reviewer_id"] == "demo-admin"
    assert out["reason"] == "cloud-e2e"
    # send_task_success json-dumps this dict — it must round-trip
    assert json.loads(json.dumps(out, default=str))["reviewer"]["reviewer_id"] == "demo-admin"


def test_missing_reviewer_fails_at_the_gate_not_in_the_pipeline(seeded):
    with pytest.raises(ValueError) as e:
        _approve(seeded, {})
    assert "reviewer" in str(e.value)


def test_activation_still_blocked_without_candidate_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    bid = "BUILD-T51B"
    reg.save_build({"build_id": bid, "status": "PATCH_VALIDATED"})
    gov.save_callback(bid, "activation", "tok-2")  # no APPROVE_CANDIDATE anywhere
    with pytest.raises(ValueError) as e:
        _approve(bid, {"reviewer_id": "demo-admin"})
    assert "APPROVE_CANDIDATE" in str(e.value)


def test_activation_output_satisfies_the_asl_contract(seeded):
    """Derive what ACTIVATE reads from the ASL, and require the gate to emit it."""
    with open(os.path.join(ROOT, "infra", "statemachine.asl.json")) as f:
        asl = json.load(f)
    prefix = asl["States"]["WAIT_FOR_ACTIVATION_APPROVAL"]["ResultPath"] + "."
    required = {k[:-2] for k, v in asl["States"]["ACTIVATE"]["Parameters"].items()
                if k.endswith(".$") and isinstance(v, str) and v.startswith(prefix)}
    assert required == {"reviewer", "reason"}, f"ASL contract moved: {required}"
    out = _approve(seeded, {"reviewer_id": "demo-admin", "display_name": "demo"}, "why")
    missing = required - set(out)
    assert not missing, f"gate payload missing ASL-required keys: {missing}"
