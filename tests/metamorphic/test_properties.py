import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_monotone_relaxation():
    from services.compiler.compiler import compile_rules, evaluate_expected
    import json
    d = ROOT / "demo" / "research_grant"
    new = json.loads((d / "rules_v2.json").read_text())
    m = compile_rules(new)
    for cgpa in (8.0, 8.5, 9.0):
        assert evaluate_expected(m, {"cgpa": cgpa})["eligible"] is True


def test_deadline_extension_monotone():
    from services.compiler.compiler import compile_rules, evaluate_expected
    import json
    old = [{"rule_id": "D1", "kind": "deadline", "action": "s", "status": "active",
            "condition": {"field": "submission_date", "operator": "<=", "value": "2026-09-25"}}]
    new = [{"rule_id": "D2", "kind": "deadline", "action": "s", "status": "active",
            "condition": {"field": "submission_date", "operator": "<=", "value": "2026-09-30"}}]
    mo, mn = compile_rules(old), compile_rules(new)
    for day in ("2026-09-20", "2026-09-25"):
        assert (not evaluate_expected(mo, {"submission_date": day})["on_time"]
                or evaluate_expected(mn, {"submission_date": day})["on_time"])
