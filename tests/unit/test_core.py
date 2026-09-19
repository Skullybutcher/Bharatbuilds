import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def demo(domain="research_grant"):
    d = ROOT / "demo" / domain
    return (json.loads((d / "rules_v1.json").read_text()),
            json.loads((d / "rules_v2.json").read_text()),
            json.loads((d / "workflow_v1.json").read_text()))


def test_threshold_compile():
    from services.compiler.compiler import compile_rules
    _, new, _ = demo()
    m = compile_rules(new)
    assert m.eligibility[0]["value"] == 7.5
    assert m.obligations["upload_recommendation"]["mode"] == "conditional"


def test_conflict_fails_closed():
    from services.compiler.compiler import compile_rules
    import pytest
    with pytest.raises(ValueError, match="CONFLICT"):
        compile_rules([
            {"rule_id": "A", "kind": "threshold", "status": "active",
             "condition": {"field": "cgpa", "operator": ">=", "value": 7.5}},
            {"rule_id": "B", "kind": "threshold", "status": "active",
             "condition": {"field": "cgpa", "operator": ">=", "value": 8.0}}])


def test_paraphrase_noop():
    from services.normalizer.normalizer import semantic_rule_delta
    old, _, _ = demo()
    assert semantic_rule_delta(old, old)["behavioral"] is False


def test_ambiguity_fail_closed():
    from services.extractor.extractor import extract
    assert extract("Applicants with strong academic standing may receive an exemption.")["status"] == "NEEDS_REVIEW"


def test_canonical_witnesses():
    from services.compiler.compiler import compile_rules
    from services.witness.generator import find_witnesses
    _, new, proc = demo()
    ws = find_witnesses(compile_rules(new), proc)
    assert {w["kind"] for w in ws} == {"wrong_rejection", "unnecessary_burden"}


def test_patch_validates_both_domains():
    from services.api.pipeline import run_build
    for domain, pv in (("research_grant", "POLICY-V2"), ("reimbursement", "REIMB-V2")):
        old, new, proc = demo(domain)
        b = run_build(pv, old, new, proc)
        assert b["status"] == "PATCH_VALIDATED", (domain, b["status"])
