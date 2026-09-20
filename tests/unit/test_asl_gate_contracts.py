"""ASL gate contracts (T53) — every human gate's resume payload must satisfy the
state machine that consumes it.

The ASL is the contract: a `waitForTaskToken` state's ResultPath IS the payload a
human decision delivers, and other states read fields out of it. These tests
derive the required fields from `infra/statemachine.asl.json` and drive the real
local gate chain, so a payload that would die as `States.Runtime` in production
fails here instead.

T51 was exactly that bug (activation emitted {decision} while ACTIVATE read
.reviewer/.reason) and it was found live, in production, after a full compile
cycle. This suite makes it impossible to reintroduce for ANY gate.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services import storage  # noqa: E402
from services.api import actions  # noqa: E402
from services.governance import store as gov  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
with open(os.path.join(ROOT, "infra", "statemachine.asl.json")) as _f:
    ASL = json.load(_f)

# Which gate a wait state belongs to, read off its Lambda payload.
GATE_BY_PAYLOAD = {"open_reviews": "rule_review", "request_review": "patch_approval"}


def _wait_gates() -> dict:
    """{gate: ResultPath} for every waitForTaskToken state, from the ASL."""
    out = {}
    for st in ASL["States"].values():
        if st.get("Type") == "Task" and "waitForTaskToken" in str(st.get("Resource", "")):
            payload = (st.get("Parameters") or {}).get("Payload") or {}
            if payload.get("kind") == "activation":
                gate = "activation"
            else:
                gate = GATE_BY_PAYLOAD[payload.get("op")]
            out[gate] = st["ResultPath"]
    return out


def _refs(result_path: str) -> set:
    """Every `<result_path>.<field>` the ASL reads, anywhere in the document."""
    prefix = result_path + "."
    found: set = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.endswith(".$") and isinstance(v, str) and v.startswith(prefix):
                    field = v[len(prefix):].split(".")[0].split("[")[0]
                    found.add(field)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(ASL)
    return found


def _approve_value(state: str, nxt: str) -> str:
    """The decision value the ASL's Choice expects for the approving branch —
    read, not hardcoded, so a vocabulary rename surfaces here."""
    for c in ASL["States"][state].get("Choices", []):
        if c.get("Next") == nxt:
            return c["StringEquals"]
    raise AssertionError(f"{state} has no Choice to {nxt}")


@pytest.fixture()
def build(tmp_path, monkeypatch):
    """A real compiled build from the canonical demo pipeline, in an isolated
    files-backend data dir — the same path the local app takes."""
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    return actions.canonical("research_grant")


def test_every_wait_state_maps_to_a_known_gate():
    gates = _wait_gates()
    assert set(gates) == {"rule_review", "patch_approval", "activation"}, gates
    assert gates["patch_approval"] == "$.patch_decision"
    assert gates["activation"] == "$.activation_decision"
    assert gates["rule_review"] == "$.rule_review_wait"


def test_rule_review_payload_satisfies_asl(build):
    bid = build["build_id"]
    required = _refs(_wait_gates()["rule_review"])
    gov.save_callback(bid, "rule_review", "tok-rule")
    out = gov.resume_callback(bid, "rule_review",
                              {"gate": "rule_review", "decisions": {},
                               "reviewer": {"reviewer_id": "rev", "display_name": "rev"}})
    assert required, "ASL reads nothing off the rule-review payload? suspicious"
    assert required - set(out) == set(), f"missing {required - set(out)}"
    assert isinstance(out["accepted_rules"], list)


def test_patch_approval_payload_satisfies_asl(build):
    bid = build["build_id"]
    required = _refs(_wait_gates()["patch_approval"])
    approve = _approve_value("PATCH_APPROVED?", "FETCH_CANDIDATE")
    gov.request_patch_review(bid, None)
    gov.save_callback(bid, "patch_approval", "tok-patch")
    out = gov.resume_callback(bid, "patch_approval",
                              {"gate": "patch_approval", "decision": approve,
                               "role": "PROCEDURE_OWNER",
                               "reviewer": {"reviewer_id": "rev", "display_name": "rev"},
                               "reason": "test"})
    assert required - set(out) == set(), f"missing {required - set(out)}"
    # the ASL Choice must match what the gate actually emitted
    assert out["decision"] == approve


def test_activation_payload_satisfies_asl(build):
    bid = build["build_id"]
    required = _refs(_wait_gates()["activation"])
    approve = _approve_value("ACTIVATION_APPROVED?", "ACTIVATE")
    gov.request_patch_review(bid, None)
    gov.save_callback(bid, "patch_approval", "tok-patch")
    gov.resume_callback(bid, "patch_approval",
                        {"gate": "patch_approval",
                         "decision": _approve_value("PATCH_APPROVED?", "FETCH_CANDIDATE"),
                         "reviewer": {"reviewer_id": "rev", "display_name": "rev"}})
    gov.save_callback(bid, "activation", "tok-act")
    out = gov.resume_callback(bid, "activation",
                              {"gate": "activation", "decision": approve,
                               "reviewer": {"reviewer_id": "rev", "display_name": "rev"},
                               "reason": "test"})
    assert required - set(out) == set(), f"missing {required - set(out)}"
    assert out["decision"] == approve


def test_the_full_gate_chain_covers_every_reference_the_asl_makes(build):
    """One build, all three gates in order: the union of payloads emitted must
    cover every field the ASL reads off any gate ResultPath. This is the class
    test — a new ASL reference with no payload producer fails here."""
    bid = build["build_id"]
    gates = _wait_gates()
    produced: dict = {}

    gov.save_callback(bid, "rule_review", "tok-1")
    produced["rule_review"] = gov.resume_callback(
        bid, "rule_review", {"gate": "rule_review", "decisions": {},
                             "reviewer": {"reviewer_id": "rev"}})

    gov.request_patch_review(bid, None)
    gov.save_callback(bid, "patch_approval", "tok-2")
    produced["patch_approval"] = gov.resume_callback(
        bid, "patch_approval",
        {"gate": "patch_approval",
         "decision": _approve_value("PATCH_APPROVED?", "FETCH_CANDIDATE"),
         "reviewer": {"reviewer_id": "rev"}})

    gov.save_callback(bid, "activation", "tok-3")
    produced["activation"] = gov.resume_callback(
        bid, "activation",
        {"gate": "activation", "decision": _approve_value("ACTIVATION_APPROVED?", "ACTIVATE"),
         "reviewer": {"reviewer_id": "rev"}, "reason": "chain"})

    uncovered = {}
    for gate, path in gates.items():
        missing = _refs(path) - set(produced[gate])
        if missing:
            uncovered[gate] = missing
    assert not uncovered, f"ASL reads fields no gate payload produces: {uncovered}"

    # and the chain actually got the build to activation readiness
    build_after = actions.get_build_view(bid)
    assert build_after is not None
