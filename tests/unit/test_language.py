"""Bounded-language v0.3 extension: enum membership (IN / NOT_IN) + intervals.

Every construct must round-trip: parser -> Rule IR -> compiler -> evaluation,
with the delta classifier reporting field-accurate changes.
"""
from __future__ import annotations

from services.extractor.extractor import extract
from services.compiler.compiler import compile_rules, evaluate_expected
from services.normalizer.normalizer import semantic_rule_delta
from services.workflow.expr import eval_condition


def _kinds(rules):
    return {(r["kind"], r["action"], tuple(sorted((r.get("condition") or {}).items()))) for r in rules}


def test_list_waiver_extracts_in_exception():
    text = ("Sec 4.2 All applicants must provide a transcript.\n"
            "Sec 4.5 A transcript is waived if applicant category is STAFF or VISITOR.")
    out = extract(text, "POLICY-T")
    assert out["status"] == "EXTRACTED", out
    exc = [r for r in out["rules"] if r["kind"] == "exception"]
    assert len(exc) == 1
    c = exc[0]["condition"]
    assert c["field"] == "category" and c["operator"] == "IN"
    assert set(c["value"]) == {"STAFF", "VISITOR"}
    assert exc[0]["action"] == "upload_transcript"


def test_notin_extraction_and_compilation():
    text = ("Sec 2.1 Claims up to amount <= 50000 are accepted.\n"
            "Sec 2.2 Claimant category must not be STAFF or VISITOR.")
    out = extract(text, "POLICY-T")
    assert out["status"] == "EXTRACTED", out
    notin = [r for r in out["rules"] if (r.get("condition") or {}).get("operator") == "NOT_IN"]
    assert len(notin) == 1 and notin[0]["condition"]["value"] == ["STAFF", "VISITOR"]
    model = compile_rules(out["rules"])
    ok = evaluate_expected(model, {"amount": 1000, "category": "general"})
    staff = evaluate_expected(model, {"amount": 1000, "category": "STAFF"})
    assert ok["eligible"] is True and staff["eligible"] is False


def test_interval_extraction_two_bounds():
    text = "Sec 1.1 Applicant age must be between 18 and 25."
    out = extract(text, "POLICY-T")
    assert out["status"] == "EXTRACTED", out
    bounds = {(r["condition"]["operator"], r["condition"]["value"]) for r in out["rules"]}
    assert bounds == {(">=", 18.0), ("<=", 25.0)}
    field = out["rules"][0]["condition"]["field"]  # slugged: applicant_age
    model = compile_rules(out["rules"])
    assert evaluate_expected(model, {field: 21})["eligible"] is True
    assert evaluate_expected(model, {field: 30})["eligible"] is False
    assert evaluate_expected(model, {field: 17})["eligible"] is False


def test_in_condition_evaluation():
    cond = {"field": "category", "operator": "IN", "value": ["STAFF", "VISITOR"]}
    assert eval_condition(cond, {"category": "STAFF"}) is True
    assert eval_condition(cond, {"category": "general"}) is False
    nin = {"field": "category", "operator": "NOT_IN", "value": ["STAFF"]}
    assert eval_condition(nin, {"category": "general"}) is True
    assert eval_condition(nin, {"category": "STAFF"}) is False


def test_delta_pairs_thresholds_within_same_field_only():
    old = [{"rule_id": "R-ELIG-V1", "kind": "threshold", "action": "eligible", "status": "active",
            "condition": {"field": "cgpa", "operator": ">=", "value": 8.0},
            "provenance": {"source_text": "cgpa >= 8.0"}}]
    new = [{"rule_id": "R-ELIG-V2", "kind": "threshold", "action": "eligible", "status": "active",
            "condition": {"field": "cgpa", "operator": ">=", "value": 7.5},
            "provenance": {"source_text": "cgpa >= 7.5"}},
           {"rule_id": "R-CAT-V2", "kind": "threshold", "action": "eligible", "status": "active",
            "condition": {"field": "category", "operator": "NOT_IN", "value": ["STAFF"]},
            "provenance": {"source_text": "category must not be STAFF"}}]
    delta = semantic_rule_delta(old, new)
    assert delta["type"] == "COMPOUND"
    assert "THRESHOLD_RELAXED" in delta["changes"]
    assert "THRESHOLD_ADDED" in delta["changes"]
    assert set(delta["affected_rule_ids"]) == {"R-ELIG-V2", "R-CAT-V2"}
