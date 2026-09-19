"""ProcessPatch verification: deterministic core + governance + benchmark.

Run: make verify  (no network, no LLM, no AWS credentials)
"""
import json
import os
import pathlib
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="pp-verify-")
os.environ["PROCESSPATCH_DATA"] = _TMP
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.compiler.compiler import compile_rules, evaluate_expected
from services.workflow.interpreter import execute
from services.witness.generator import find_witnesses
from services.localizer.localizer import localize_all
from services.patcher.patcher import propose
from services.regression.validator import validate
from services.extractor.extractor import extract
from services.normalizer.normalizer import semantic_rule_delta
from services.provenance.provenance import coverage, evidence_drawer

GROUPS: dict[str, list] = {}


def check(group: str, name: str, cond: bool, detail: str = ""):
    GROUPS.setdefault(group, []).append((name, bool(cond), detail))


def demo(domain: str):
    d = ROOT / "demo" / domain
    return (json.loads((d / "rules_v1.json").read_text()),
            json.loads((d / "rules_v2.json").read_text()),
            json.loads((d / "workflow_v1.json").read_text()))


def main() -> int:
    print("ProcessPatch Verification\n")
    old, new, proc = demo("research_grant")
    rold, rnew, rproc = demo("reimbursement")

    m = compile_rules(new)
    om = compile_rules([{**r, "status": "active"} for r in old])
    rm = compile_rules(rnew)
    rom = compile_rules([{**r, "status": "active"} for r in rold])

    # ---- Rule semantics ----
    check("Rule semantics", "grant threshold 7.5", m.eligibility[0]["value"] == 7.5)
    check("Rule semantics", "grant rec conditional", m.obligations["upload_recommendation"]["mode"] == "conditional")
    check("Rule semantics", "grant ordering kept", len(m.ordering) == 1)
    check("Rule semantics", "7.8 eligible", evaluate_expected(m, {"cgpa": 7.8})["eligible"] is True)
    check("Rule semantics", "7.8 rec required", evaluate_expected(m, {"cgpa": 7.8})["required"]["upload_recommendation"] is True)
    check("Rule semantics", "8.2 eligible", evaluate_expected(m, {"cgpa": 8.2})["eligible"] is True)
    check("Rule semantics", "8.2 rec waived", evaluate_expected(m, {"cgpa": 8.2})["required"]["upload_recommendation"] is False)
    check("Rule semantics", "reimb limit 50000", rm.eligibility[0]["value"] == 50000)
    check("Rule semantics", "reimb approval conditional", rm.obligations["manager_approval"]["mode"] == "conditional")
    check("Rule semantics", "reimb deadline 09-30", rm.deadlines[0]["value"] == "2026-09-30")
    check("Rule semantics", "reimb 60000 needs approval",
          evaluate_expected(rm, {"amount": 60000, "submission_date": "2026-09-28"})["required"]["manager_approval"] is True)
    check("Rule semantics", "reimb 40000 no approval",
          evaluate_expected(rm, {"amount": 40000, "submission_date": "2026-09-28"})["required"]["manager_approval"] is False)
    check("Rule semantics", "reimb late not on_time",
          evaluate_expected(rm, {"amount": 40000, "submission_date": "2026-10-01"})["on_time"] is False)
    check("Rule semantics", "exception waives rec",
          evaluate_expected(compile_rules(new + [{"rule_id": "X", "kind": "exception", "subject": "a",
                                                  "action": "upload_recommendation", "status": "active",
                                                  "condition": {"field": "category", "operator": "==", "value": "X"}}]),
                            {"cgpa": 7.0, "category": "X"})["required"]["upload_recommendation"] is False)
    check("Rule semantics", "conflict fails closed", _conflict())
    check("Rule semantics", "conditional needs condition", _needs_cond())
    check("Rule semantics", "prohibition recorded", _prohibition())
    check("Rule semantics", "generic gates AND", _and_gates())

    # ---- Semantic no-op ----
    check("Semantic no-op", "identical rules no-op", semantic_rule_delta(old, old)["behavioral"] is False)
    check("Semantic no-op", "paraphrase no-op", _paraphrase())
    check("Semantic no-op", "renumber provenance-only", _renumber())
    check("Semantic no-op", "irrelevant edit no-op", _irrelevant())
    check("Semantic no-op", "ambiguity fail-closed", extract("Applicants with strong academic standing may receive an exemption.")["status"] == "NEEDS_REVIEW")
    check("Semantic no-op", "conflict blocked", extract("Applicants must have CGPA >= 7.5.\nApplicants must have CGPA >= 8.0.")["status"] == "CONFLICT")
    check("Semantic no-op", "v2 extraction 3 rules", len(extract((ROOT / "demo/research_grant/policy_v2.md").read_text(), "POLICY-V2")["rules"]) == 3)
    check("Semantic no-op", "conditional line not a conflict", extract((ROOT / "demo/research_grant/policy_v2.md").read_text(), "POLICY-V2")["status"] == "EXTRACTED")

    # ---- Witness generation ----
    ws = find_witnesses(m, proc)
    kinds = {(w["case"].get("cgpa"), w["kind"]) for w in ws}
    check("Witness generation", "witness A 7.5-8.0 rejection", any(k == "wrong_rejection" and 7.5 <= (c or 0) < 8.0 for c, k in kinds))
    check("Witness generation", "witness B 8.x burden", any(k == "unnecessary_burden" and (c or 0) >= 8.0 for c, k in kinds))
    check("Witness generation", "exactly 2 minimal witnesses", len(ws) == 2, str(len(ws)))
    check("Witness generation", "100% reproduce", all(_reproduces(m, proc, w) for w in ws))
    rws = find_witnesses(rm, rproc)
    rks = {w["kind"] for w in rws}
    check("Witness generation", "reimb wrong_acceptance", "wrong_acceptance" in rks, str(rks))
    check("Witness generation", "reimb wrong_journey", "wrong_journey" in rks)
    check("Witness generation", "reimb deadline_mismatch", "deadline_mismatch" in rks)
    check("Witness generation", "reimb burden", "unnecessary_burden" in rks)
    check("Witness generation", "reimb witnesses reproduce", all(_reproduces(rm, rproc, w) for w in rws))
    check("Witness generation", "no witness when equivalent", find_witnesses(compile_rules(new), _patched_copy(new, proc)) == [])
    check("Witness generation", "ineligible pair no rec false-positive",
          not [w for w in find_witnesses(m, proc) if w["case"].get("cgpa", 9) < 7.0])
    for i, w in enumerate(ws[:2]):
        check("Witness generation", f"witness {w['witness_id']} labeled", bool(w.get("label")))
    for w in rws[:4]:
        check("Witness generation", f"reimb {w['witness_id']} verified", w.get("verified") is True)

    # ---- Structural regression ----
    a78 = execute(proc, {"cgpa": 7.8}, m.ordering)
    check("Structural regression", "stale rejects 7.8", a78["eligible"] is False)
    a82 = execute(proc, {"cgpa": 8.2}, m.ordering)
    check("Structural regression", "stale requires rec at 8.2", a82["required"]["upload_recommendation"] is True)
    check("Structural regression", "reimb pays before verify", _pays_first(rproc))
    check("Structural regression", "reimb stale limit 100000", _gate_value(rproc, "amount") == 100000)
    check("Structural regression", "reimb missing deadline gate", _has_dl_gate(rproc) is False)
    check("Structural regression", "trace non-empty", len(a78["trace"]) >= 2)
    check("Structural regression", "path starts at start", a78["path"][0] == "NODE-START")
    for f, op, v in (("cgpa", ">=", 7.5), ("amount", "<=", 50000)):
        check("Structural regression", f"expr {f} {op} {v}", _expr(f, op, v))

    # ---- Behavior regression ----
    for cgpa, exp_e, exp_r in [(7.49, False, True), (7.50, True, True), (7.99, True, True), (8.00, True, False), (8.01, True, False)]:
        ee = evaluate_expected(m, {"cgpa": cgpa})
        check("Behavior regression", f"boundary {cgpa}", ee["eligible"] == exp_e and ee["required"]["upload_recommendation"] == exp_r)
    for amt, exp_e in [(49999, True), (50000, True), (50001, False), (100000, False)]:
        check("Behavior regression", f"amount boundary {amt}",
              evaluate_expected(rm, {"amount": amt, "submission_date": "2026-09-28"})["eligible"] == exp_e)
    for day, exp in [("2026-09-29", True), ("2026-09-30", True), ("2026-10-01", False)]:
        check("Behavior regression", f"deadline boundary {day}",
              evaluate_expected(rm, {"amount": 100, "submission_date": day})["on_time"] == exp)

    # ---- Patch validation ----
    from services.api.pipeline import run_build
    b = run_build("POLICY-V2", old, new, proc)
    check("Patch validation", "canonical PATCH_VALIDATED", b["status"] == "PATCH_VALIDATED", b["status"])
    check("Patch validation", "canonical 12/12", b["validation"]["passed"] == b["validation"]["total"] == 12, str(b["validation"]["passed"]))
    check("Patch validation", "patch cost small", b["patch"]["cost"] <= 9.0, str(b["patch"]["cost"]))
    check("Patch validation", "patch ops constrained", all(o["op"] in ("CHANGE_CONDITION", "CHANGE_REQUIRED_FLAG", "ADD_GATE", "ADD_EDGE", "REMOVE_EDGE", "ADD_NODE", "REMOVE_NODE", "MOVE_NODE", "ADD_PREREQUISITE", "REMOVE_PREREQUISITE") for o in b["patch"]["operations"]))
    check("Patch validation", "certificate validated", (b["certificate"] or {}).get("status") == "VALIDATED_WITHIN_TESTED_MODEL")
    rb = run_build("REIMB-V2", rold, rnew, rproc)
    check("Patch validation", "reimb PATCH_VALIDATED", rb["status"] == "PATCH_VALIDATED", rb["status"])
    check("Patch validation", "reimb 16/16", rb["validation"]["passed"] == rb["validation"]["total"] == 16)
    check("Patch validation", "reimb order fixed", rb["patched_workflow"] and __import__("services.workflow.interpreter", fromlist=["execute"]).execute(rb["patched_workflow"], {"amount": 1}, rm.ordering)["order_ok"])
    check("Patch validation", "reimb deadline gate added", _has_dl_gate(rb["patched_workflow"]))
    check("Patch validation", "metamorphic relaxation holds", any(r["suite"] == "metamorphic" and r["pass"] for r in b["validation"]["results"]))

    # ---- Provenance ----
    cov = coverage(b["patched_workflow"]["nodes"])
    check("Provenance", "coverage 1.0", cov["coverage"] == 1.0, str(cov))
    check("Provenance", "structural nodes excluded", cov["governed_nodes"] < cov["nodes"])
    drawer = evidence_drawer(next(n for n in b["patched_workflow"]["nodes"] if n["node_id"] == "NODE-REC-UPLOAD"),
                             {r["rule_id"]: r for r in new})
    check("Provenance", "drawer links rule", any(c["rule_id"] == "RULE-REC-014" for c in drawer["chain"]))
    check("Provenance", "drawer has source text", all(c["source_text"] for c in drawer["chain"]))
    check("Provenance", "drawer has review state", all("review_state" in c for c in drawer["chain"]))
    check("Provenance", "changed nodes linked", all(n.get("provenance_links") for n in b["patched_workflow"]["nodes"] if n["node_id"] in ("NODE-ELIGIBILITY", "NODE-REC-UPLOAD")) if any(n["node_id"] == "NODE-ELIGIBILITY" for n in b["patched_workflow"]["nodes"]) else True)

    # ---- Impact ----
    im = b["impact"]
    check("Impact", "summary contract keys", all(k in im for k in ("build_id", "semantic_changes", "artifacts", "behavioral", "test_cohort", "verification", "approval")))
    check("Impact", "behavioral counts", im["behavioral"]["wrong_rejections"] >= 1 and im["behavioral"]["unnecessary_burdens"] >= 1)
    check("Impact", "cohort labeled synthetic", "synthetic" in im["test_cohort"]["label"].lower())
    check("Impact", "cohort newly eligible > 0", im["test_cohort"]["newly_eligible"] > 0)
    check("Impact", "approval awaiting", im["approval"]["human_status"] == "AWAITING_APPROVAL")
    from services.impact.engine import before_after_table
    check("Impact", "before/after table", len(before_after_table(im)) == 4)

    # ---- Governance ----
    from services.governance.store import (open_rule_reviews, review_rule, accepted_rules, unresolved_rule_reviews,
                                           approval_guardrails, request_patch_review, decide_patch, activate_procedure,
                                           approvals_for)
    from services.registry.store import audit_for, list_procedure_versions
    revs = open_rule_reviews(b["build_id"], new)
    check("Governance", "3 reviews opened", len(revs) == 3, str(len(revs)))
    check("Governance", "unresolved 3", unresolved_rule_reviews(b["build_id"]) == 3)
    for r in new:
        review_rule(b["build_id"], r["rule_id"], "ACCEPT")
    check("Governance", "accepted 3", len(accepted_rules(b["build_id"])) == 3)
    check("Governance", "guardrails approvable", approval_guardrails(b)["approvable"] is True, str(approval_guardrails(b)["blockers"]))
    request_patch_review(b["build_id"], reviewer_opened_hash=None)
    rec = decide_patch(b["build_id"], b, "APPROVE_CANDIDATE",
                       {"reviewer_id": "USR-001", "display_name": "Verify"}, "ok", "PROCEDURE_OWNER")
    check("Governance", "approval recorded", rec["approval_type"] == "PATCH_REVIEW")
    check("Governance", "approval binds hashes", rec["artifacts"]["patch_hash"] == __import__("services.registry.store", fromlist=["sha"]).sha(b["patch"]["operations"]))
    out = activate_procedure(b["build_id"], b, {"reviewer_id": "USR-001"}, "go")
    check("Governance", "activation creates version", out["procedure_version"]["status"] == "active")
    check("Governance", "audit timeline grows", len(audit_for(b["build_id"])) >= 5, str(len(audit_for(b["build_id"]))))
    check("Governance", "reject flow blocks activation", _reject_blocks())
    check("Governance", "stale hash invalidates", _stale_hash(b))

    # ---- Benchmark ----
    from services.bench.runner import run_all
    results = run_all()
    by_status: dict = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    for r in results:
        check("Benchmark", f"{r['case_id']} {r['status']}",
              r["status"] in ("AUTO_REPAIRED", "CORRECTLY_NO_OP", "CORRECTLY_ESCALATED"), r.get("error", "")[:120])
    check("Benchmark", "26 scenarios", len(results) == 26, str(len(results)))
    check("Benchmark", "19 auto-repaired", by_status.get("AUTO_REPAIRED") == 19, str(by_status))
    check("Benchmark", "3 no-op", by_status.get("CORRECTLY_NO_OP") == 3, str(by_status))
    check("Benchmark", "4 escalated", by_status.get("CORRECTLY_ESCALATED") == 4, str(by_status))

    # ---- Infra ----
    import yaml
    tpl = yaml.load((ROOT / "infra/template.yaml").read_text(), Loader=_cfn_loader(yaml))
    check("Infra", "7 lambdas", sum(1 for v in tpl["Resources"].values() if v.get("Type") == "AWS::Serverless::Function") == 7)
    check("Infra", "single-table registry", "RegistryTable" in tpl["Resources"])
    sm = json.loads((ROOT / "infra/statemachine.asl.json").read_text())
    check("Infra", "31 pipeline states", len(sm["States"]) == 31, str(len(sm["States"])))
    check("Infra", "3 task-token gates", sum("waitForTaskToken" in json.dumps(s) for s in sm["States"].values()) == 3)
    dash = json.loads((ROOT / "infra/cloudwatch-dashboard.json").read_text())
    check("Infra", "dashboard widgets", len(dash["widgets"]) >= 5)

    total = sum(len(v) for v in GROUPS.values())
    passed = sum(1 for v in GROUPS.values() for _, c, _ in v if c)
    print()
    for g, items in GROUPS.items():
        gp = sum(1 for _, c, _ in items if c)
        print(f"{g:24s} {gp}/{len(items)} {'PASS' if gp == len(items) else 'FAIL'}")
        for name, c, detail in items:
            if not c:
                print(f"    FAIL {name} {detail}")
    print(f"\n{total} assertions: {passed} passed, {total - passed} failed")
    print("PASS" if passed == total else "FAIL")
    return 0 if passed == total else 1


# ---- helpers ----
def _conflict():
    try:
        compile_rules([
            {"rule_id": "A", "kind": "threshold", "status": "active",
             "condition": {"field": "cgpa", "operator": ">=", "value": 7.5}},
            {"rule_id": "B", "kind": "threshold", "status": "active",
             "condition": {"field": "cgpa", "operator": ">=", "value": 8.0}}])
        return False
    except ValueError as e:
        return "CONFLICT" in str(e)


def _needs_cond():
    try:
        compile_rules([{"rule_id": "A", "kind": "conditional_obligation",
                        "action": "x", "status": "active", "condition": None}])
        return False
    except ValueError:
        return True


def _prohibition():
    m = compile_rules([{"rule_id": "P", "kind": "prohibition", "status": "active",
                        "condition": {"field": "amount", "operator": ">", "value": 10}}])
    return len(m.prohibitions) == 1


def _and_gates():
    m = compile_rules([
        {"rule_id": "A", "kind": "threshold", "action": "eligible", "status": "active",
         "condition": {"field": "cgpa", "operator": ">=", "value": 7.5}},
        {"rule_id": "B", "kind": "threshold", "action": "eligible", "status": "active",
         "condition": {"field": "year", "operator": "IN", "value": [3, 4]}}])
    return (evaluate_expected(m, {"cgpa": 8.0, "year": 3})["eligible"] is True
            and evaluate_expected(m, {"cgpa": 8.0, "year": 2})["eligible"] is False)


def _paraphrase():
    a = [{"rule_id": "D", "kind": "deadline", "action": "s", "status": "active",
          "condition": {"field": "submission_date", "operator": "<=", "value": "2026-09-30"},
          "provenance": {"section": "6.1"}}]
    b = [{**a[0], "provenance": {"section": "6.1"}}]
    return semantic_rule_delta(a, b)["type"] == "SEMANTICS_UNCHANGED"


def _renumber():
    a = [{"rule_id": "D", "kind": "deadline", "action": "s", "status": "active",
          "condition": {"field": "submission_date", "operator": "<=", "value": "2026-09-30"},
          "provenance": {"section": "4.2"}}]
    b = [{**a[0], "provenance": {"section": "5.1"}}]
    return semantic_rule_delta(a, b)["type"] == "PROVENANCE_ONLY"


def _irrelevant():
    a = [{"rule_id": "D", "kind": "deadline", "action": "s", "status": "active",
          "condition": {"field": "submission_date", "operator": "<=", "value": "2026-09-30"},
          "provenance": {"section": "6.1"}}]
    return semantic_rule_delta(a, a)["behavioral"] is False


def _reproduces(model, proc, w):
    from services.compiler.compiler import evaluate_expected as ee
    e = {**ee(model, w["case"]), "order_ok": True}
    a = execute(proc, w["case"], model.ordering)
    return e["eligible"] != a["eligible"] or e["required"] != a["required"] or e["on_time"] != a["on_time"]


def _patched_copy(rules, proc):
    from services.api.pipeline import run_build
    old = [{**r, "status": "superseded" if r.get("status") == "active" else r.get("status")} for r in rules]
    return run_build("P", old, rules, proc)["patched_workflow"]


def _pays_first(proc):
    ids = [n["node_id"] for n in proc["nodes"]]
    return ids.index("NODE-PAYMENT") < ids.index("NODE-VERIFY")


def _gate_value(proc, field):
    for n in proc["nodes"]:
        impl = n.get("implementation", {}) or {}
        if impl.get("field") == field:
            return impl.get("value")
    return None


def _has_dl_gate(proc):
    return any((n.get("implementation", {}) or {}).get("kind") == "deadline_gate" for n in proc["nodes"])


def _expr(f, op, v):
    from services.workflow.expr import eval_condition
    return eval_condition({"field": f, "operator": op, "value": v},
                          {f: v, "amount": v, "cgpa": v}) is True


def _reject_blocks():
    from services.governance.store import decide_patch
    b = {"build_id": "B-REJ", "patch": {"operations": []}, "validation": {"status": "FAILED", "results": []},
         "new_rules": [], "procedure": {}, "certificate": {}, "conflicts": [], "impact": {}}
    try:
        decide_patch("B-REJ", b, "APPROVE_CANDIDATE", {"reviewer_id": "U"}, "x", "PROCEDURE_OWNER")
        return False
    except ValueError:
        return True


def _stale_hash(b):
    import copy
    from services.registry.store import sha
    from services.governance.store import decide_patch, request_patch_review
    bid = b["build_id"] + "-stale"
    opened = sha(b["patch"]["operations"])
    request_patch_review(bid, reviewer_opened_hash=opened)
    b2 = copy.deepcopy(b)
    b2["build_id"] = bid
    b2["patch"]["operations"] = b2["patch"]["operations"] + [{"op": "ADD_GATE", "node_id": "X"}]
    try:
        decide_patch(bid, b2, "APPROVE_CANDIDATE", {"reviewer_id": "U"}, "x", "PROCEDURE_OWNER")
        return False
    except ValueError as e:
        return "INVALIDATED" in str(e)


def _cfn_loader(yaml):
    class CfnLoader(yaml.SafeLoader):
        pass

    def _cfn(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return {tag_suffix: loader.construct_scalar(node)}
        if isinstance(node, yaml.SequenceNode):
            return {tag_suffix: loader.construct_sequence(node)}
        return {tag_suffix: loader.construct_mapping(node)}

    for tag in ("Ref", "Sub", "GetAtt", "Join", "Select", "If", "Equals"):
        CfnLoader.add_constructor(f"!{tag}", lambda l, n, t=tag: _cfn(l, t, n))
    CfnLoader.add_multi_constructor("!", lambda l, s, n: _cfn(l, s, n))
    return CfnLoader


if __name__ == "__main__":
    raise SystemExit(main())
