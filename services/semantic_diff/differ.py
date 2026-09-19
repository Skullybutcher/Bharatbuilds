"""Semantic differ: expected constraint semantics vs actual workflow semantics.

Witness categories: wrong_rejection | wrong_acceptance | unnecessary_burden |
missing_safeguard | wrong_journey | deadline_mismatch | prohibition_breach
"""
from __future__ import annotations


def classify_disagreement(expected: dict, actual: dict) -> tuple[str | None, str | None]:
    """Returns (kind, detail_key). detail_key is action/rule/check name."""
    if expected.get("eligible") != actual.get("eligible"):
        return ("wrong_rejection" if expected.get("eligible") else "wrong_acceptance", "eligible")
    if expected.get("on_time") != actual.get("on_time"):
        # policy forbids late submission but portal accepts (or vice versa)
        return ("deadline_mismatch", "on_time")
    # prohibition: policy forbids this case but the procedure does not block it.
    # (Skipped when both sides already reject: an unreachable case cannot
    # bypass enforcement, mirroring the required-step rule below.)
    violated = expected.get("prohibitions_violated") or []
    if violated and not actual.get("prohibited") and (expected.get("eligible") or actual.get("eligible")):
        return ("prohibition_breach", violated[0])
    if not expected.get("eligible") and not actual.get("eligible"):
        if expected.get("order_ok", True) != actual.get("order_ok", True):
            return ("wrong_journey", "order")
        return (None, None)
    exp_req, act_req = expected.get("required", {}), actual.get("required", {})
    for action in sorted(set(exp_req) | set(act_req)):
        if exp_req.get(action, False) != act_req.get(action, False):
            if act_req.get(action, False):
                return ("unnecessary_burden", action)
            return ("missing_safeguard", action)
    if expected.get("order_ok", True) != actual.get("order_ok", True):
        return ("wrong_journey", "order")
    return (None, None)


def diff_case(expected: dict, actual: dict, case: dict) -> dict | None:
    kind, key = classify_disagreement(expected, actual)
    if kind is None:
        return None
    return {"case": dict(case), "kind": kind, "key": key,
            "expected": {"eligible": expected.get("eligible"), "required": expected.get("required"),
                         "on_time": expected.get("on_time"), "order_ok": expected.get("order_ok"),
                         "prohibitions_violated": expected.get("prohibitions_violated", [])},
            "actual": {"eligible": actual.get("eligible"), "required": actual.get("required"),
                       "on_time": actual.get("on_time"), "order_ok": actual.get("order_ok"),
                       "prohibited": actual.get("prohibited", False)},
            "trace_expected": list(expected.get("trace", [])),
            "trace_actual": list(actual.get("trace", []))}
