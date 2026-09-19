"""Normalizer edge-case tests — v0.3 language additions.

Covers:
  1. semantic_rule_delta pairs thresholds within the same field only (not
     across fields, e.g. cgpa bound vs NOT_IN category).
  2. compile_rules interval satisfiability: valid interval compiles; empty
     domain raises ValueError CONFLICT / COMPILATION BLOCKED.
  3. IN/NOT_IN evaluation through services.workflow.expr.eval_condition:
     member, non-member, missing field.
  4. validate_rule rejects: unknown kind, conditional_obligation without
     condition, rule missing provenance.source_text.
  5. Delta of identical rule lists: different provenance sections →
     PROVENANCE_ONLY; identical sections → SEMANTICS_UNCHANGED.
"""
from __future__ import annotations

import pytest

from services.normalizer.normalizer import validate_rule, semantic_rule_delta
from services.compiler.compiler import compile_rules
from services.workflow.expr import eval_condition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _threshold(rule_id, field, operator, value, action="eligible", **kwargs):
    """Minimal valid threshold rule."""
    return {
        "rule_id": rule_id,
        "kind": "threshold",
        "action": action,
        "status": "active",
        "condition": {"field": field, "operator": operator, "value": value},
        "provenance": {"source_text": f"{field} {operator} {value}"},
        **kwargs,
    }


def _threshold_notin(rule_id, field, values, action="eligible"):
    """Minimal valid NOT_IN threshold rule."""
    return {
        "rule_id": rule_id,
        "kind": "threshold",
        "action": action,
        "status": "active",
        "condition": {"field": field, "operator": "NOT_IN", "value": values},
        "provenance": {"source_text": f"{field} NOT_IN {values}"},
    }


# ---------------------------------------------------------------------------
# Test 1 — same-field-only threshold pairing
# ---------------------------------------------------------------------------

def test_delta_same_field_threshold_relaxed_plus_new_field_added():
    """old has cgpa >= 8.0; new has cgpa >= 7.5 AND category NOT_IN [STAFF].
    The cgpa change is THRESHOLD_RELAXED (same field); the NOT_IN rule is a
    new threshold for a different field → THRESHOLD_ADDED.
    Together they form COMPOUND.
    """
    old = [_threshold("R-CGPA-V1", "cgpa", ">=", 8.0)]
    new = [
        _threshold("R-CGPA-V2", "cgpa", ">=", 7.5),
        _threshold_notin("R-CAT-V2", "category", ["STAFF"]),
    ]
    delta = semantic_rule_delta(old, new)

    assert delta["type"] == "COMPOUND"
    assert "THRESHOLD_RELAXED" in delta["changes"]
    assert "THRESHOLD_ADDED" in delta["changes"]
    assert set(delta["affected_rule_ids"]) == {"R-CGPA-V2", "R-CAT-V2"}


def test_delta_does_not_cross_pair_different_fields():
    """A cgpa lower-bound and an amount lower-bound must NOT be paired as a
    single threshold change; the cgpa rule is a relaxation of the old one and
    the amount rule is an entirely new threshold."""
    old = [_threshold("R-CGPA-V1", "cgpa", ">=", 8.0)]
    new = [
        _threshold("R-CGPA-V2", "cgpa", ">=", 7.5),
        _threshold("R-AMT-V1", "amount", "<=", 50000, action="eligible"),
    ]
    delta = semantic_rule_delta(old, new)

    assert delta["type"] == "COMPOUND"
    # cgpa relaxed, amount is new
    assert "THRESHOLD_RELAXED" in delta["changes"]
    assert "THRESHOLD_ADDED" in delta["changes"]
    # Both new rule ids are affected
    assert "R-CGPA-V2" in delta["affected_rule_ids"]
    assert "R-AMT-V1" in delta["affected_rule_ids"]


def test_delta_same_field_tightened():
    """Raising a lower bound is THRESHOLD_TIGHTENED."""
    old = [_threshold("R-V1", "cgpa", ">=", 7.5)]
    new = [_threshold("R-V2", "cgpa", ">=", 8.0)]
    delta = semantic_rule_delta(old, new)

    assert delta["type"] == "THRESHOLD_TIGHTENED"
    assert delta["behavioral"] is True
    assert "R-V2" in delta["affected_rule_ids"]


# ---------------------------------------------------------------------------
# Test 2 — compile_rules interval satisfiability
# ---------------------------------------------------------------------------

def test_compile_valid_interval():
    """age >= 18 AND age <= 25 is a satisfiable interval — must compile."""
    rules = [
        _threshold("R-LO", "age", ">=", 18),
        _threshold("R-HI", "age", "<=", 25),
    ]
    model = compile_rules(rules)
    # Both bounds land in eligibility; no exception raised
    assert len(model.eligibility) == 2


def test_compile_empty_interval_raises_conflict():
    """age >= 8.0 AND age < 7.5 is an empty domain — must raise CONFLICT."""
    rules = [
        _threshold("R-LO", "age", ">=", 8.0),
        _threshold("R-HI", "age", "<", 7.5),
    ]
    with pytest.raises(ValueError, match="CONFLICT"):
        compile_rules(rules)


def test_compile_conflicting_lower_bounds_raises():
    """Two distinct lower bounds for the same field (no precedence) → CONFLICT."""
    rules = [
        _threshold("R-A", "cgpa", ">=", 7.5),
        _threshold("R-B", "cgpa", ">=", 8.0),
    ]
    with pytest.raises(ValueError, match="CONFLICT"):
        compile_rules(rules)


# ---------------------------------------------------------------------------
# Test 3 — IN / NOT_IN evaluation via eval_condition
# ---------------------------------------------------------------------------

def test_eval_in_member():
    cond = {"field": "category", "operator": "IN", "value": ["STAFF", "VISITOR"]}
    assert eval_condition(cond, {"category": "STAFF"}) is True


def test_eval_in_non_member():
    cond = {"field": "category", "operator": "IN", "value": ["STAFF", "VISITOR"]}
    assert eval_condition(cond, {"category": "general"}) is False


def test_eval_in_missing_field():
    """Missing field → False (fail-closed)."""
    cond = {"field": "category", "operator": "IN", "value": ["STAFF"]}
    assert eval_condition(cond, {}) is False


def test_eval_notin_non_member():
    cond = {"field": "category", "operator": "NOT_IN", "value": ["STAFF"]}
    assert eval_condition(cond, {"category": "general"}) is True


def test_eval_notin_member():
    cond = {"field": "category", "operator": "NOT_IN", "value": ["STAFF"]}
    assert eval_condition(cond, {"category": "STAFF"}) is False


def test_eval_notin_missing_field():
    """Missing field → False (fail-closed)."""
    cond = {"field": "category", "operator": "NOT_IN", "value": ["STAFF"]}
    assert eval_condition(cond, {}) is False


# ---------------------------------------------------------------------------
# Test 4 — validate_rule rejects invalid rules
# ---------------------------------------------------------------------------

def test_validate_rule_unknown_kind():
    r = {"rule_id": "R-1", "kind": "magic", "provenance": {"source_text": "x"}}
    errs = validate_rule(r)
    assert any("unknown kind" in e for e in errs)


def test_validate_rule_conditional_obligation_no_condition():
    r = {
        "rule_id": "R-2",
        "kind": "conditional_obligation",
        "action": "upload_rec",
        "provenance": {"source_text": "if cgpa < 8 then upload rec"},
    }
    errs = validate_rule(r)
    assert any("conditional_obligation missing condition" in e for e in errs)


def test_validate_rule_missing_provenance_source_text():
    r = {
        "rule_id": "R-3",
        "kind": "threshold",
        "condition": {"field": "cgpa", "operator": ">=", "value": 7.5},
    }
    errs = validate_rule(r)
    assert any("missing provenance.source_text" in e for e in errs)


def test_validate_rule_valid_threshold_no_errors():
    r = {
        "rule_id": "R-OK",
        "kind": "threshold",
        "action": "eligible",
        "status": "active",
        "condition": {"field": "cgpa", "operator": ">=", "value": 7.5},
        "provenance": {"source_text": "cgpa >= 7.5"},
    }
    assert validate_rule(r) == []


# ---------------------------------------------------------------------------
# Test 5 — provenance-only vs semantics-unchanged delta
# ---------------------------------------------------------------------------

def _make_rule(rule_id, section="Sec 1.1"):
    return {
        "rule_id": rule_id,
        "kind": "threshold",
        "action": "eligible",
        "status": "active",
        "condition": {"field": "cgpa", "operator": ">=", "value": 7.5},
        "provenance": {"source_text": "cgpa >= 7.5", "section": section},
    }


def test_delta_different_provenance_section_is_provenance_only():
    """Same semantic rule, different provenance section → PROVENANCE_ONLY."""
    old = [_make_rule("R-V1", section="Sec 1.1")]
    new = [_make_rule("R-V1", section="Sec 2.3")]
    delta = semantic_rule_delta(old, new)

    assert delta["type"] == "PROVENANCE_ONLY"
    assert delta["behavioral"] is False


def test_delta_identical_rules_is_semantics_unchanged():
    """Same semantic rule, same provenance section → SEMANTICS_UNCHANGED."""
    rule = _make_rule("R-V1", section="Sec 1.1")
    delta = semantic_rule_delta([rule], [rule])

    assert delta["type"] == "SEMANTICS_UNCHANGED"
    assert delta["behavioral"] is False
