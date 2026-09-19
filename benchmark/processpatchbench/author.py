"""Author heterogeneous ProcessPatchBench cases (Spec 57C) — writes case files.

Run: python benchmark/processpatchbench/author.py
Every case is genuinely different (family, domain, fields, failure mode).
Splits: dev (tuning allowed) vs eval (held-out style).
"""
import json
import pathlib

HERE = pathlib.Path(__file__).parent
CASES_DIR = HERE / "cases"
VERSION = "v0.2.0"


def R(rid, kind, action, cond, expr, sec, text, pv, sup=None, conf=0.95,
      status="active", subj="applicant"):
    return {"rule_id": rid, "kind": kind, "subject": subj, "action": action,
            "condition": cond, "normalized_expression": expr,
            "effective_from": "2026-09-18", "effective_to": None, "status": status,
            "supersedes": sup,
            "provenance": {"policy_version_id": pv, "document_sha256": "bench",
                           "page": 2, "section": sec, "source_text": text},
            "extraction": {"model": "hand-authored-gold", "confidence": conf,
                           "review_state": "accepted" if status == "active" else "superseded"}}


def N(nid, wf, ntype, label, impl, targets):
    return {"node_id": nid, "workflow_id": wf, "type": ntype, "label": label,
            "preconditions": [], "postconditions": [],
            "implementation": impl,
            "provenance_links": [{"type": "IMPLEMENTS_RULE", "target": t} for t in targets]}


def START(wf):
    return N("NODE-START", wf, "start", "Start", {}, [])


def GATE(wf, field, op, val, target):
    return N("NODE-GATE", wf, "gate", f"Check {field}",
             {"kind": "threshold_gate", "field": field, "operator": op, "value": val}, [target])


def STEP(wf, action, field, required, cond, target):
    return N("NODE-STEP", wf, "action", action.replace("_", " ").title(),
             {"form_field": field, "action": action, "required": required,
              "required_condition": cond}, [target])


def APPR(wf, nid, label, action, field, required, cond, target):
    return N(nid, wf, "approval", label,
             {"form_field": field, "action": action, "required": required,
              "required_condition": cond, "approver": action}, [target])


def PAPPR(wf, nid, label, approver, target):
    """Pure prerequisite approval: no per-applicant required flag (not an obligation)."""
    return N(nid, wf, "approval", label,
             {"approver": approver, "role": approver}, [target])


def SUBMIT(wf):
    return N("NODE-SUBMIT", wf, "action", "Final Submission",
             {"action": "submit"}, [])


def DLGATE(wf, value, target):
    return N("NODE-DL", wf, "gate", "Check Submission Deadline",
             {"kind": "deadline_gate", "field": "submission_date",
              "operator": "<=", "value": value}, [target])


def PAY(wf):
    return N("NODE-PAY", wf, "action", "Release Payment",
             {"action": "payment", "role": "payment"}, ["R-ORD"])


def VERIFY(wf):
    return N("NODE-VERIFY", wf, "action", "Verify Claim",
             {"action": "verification", "role": "verification"}, ["R-ORD"])


def linear(ids):
    return [{"from": a, "to": b, "type": "NEXT", "condition": None}
            for a, b in zip(ids, ids[1:])]


def WF(wid, version, nodes, edges):
    return {"workflow_id": wid, "procedure_version_id": version,
            "version_label": version, "status": "active",
            "nodes": nodes, "edges": edges}


CASES = []


def case(cid, family, domain, split, v1text, v2text, rules1, rules2, proc,
         gold_delta, gold_witness, gold_loc, gold_repair):
    CASES.append({"case_id": cid, "family": family, "domain": domain, "split": split,
                  "policy_v1": v1text, "policy_v2": v2text, "rules_v1": rules1,
                  "rules_v2": rules2, "procedure": proc, "gold_delta": gold_delta,
                  "gold_witness": gold_witness, "gold_localization": gold_loc,
                  "gold_repair": gold_repair})


# ---------------- 01 THRESH-RELAX-001 (dev, canonical shape) ----------------
_T1 = "Applicants must have CGPA >= 8.0."
_T2 = "All applicants must provide a faculty recommendation."
_T3 = "Department approval must occur before final submission."
_U1 = "Applicants must have CGPA >= 7.5."
_U2 = "A faculty recommendation is required only when CGPA < 8.0."
case("THRESH-RELAX-001", "threshold_relaxation", "university_application", "dev",
     f"Sec 4.1 {_T1}\nSec 4.2 {_T2}\nSec 4.3 {_T3}",
     f"Sec 4.1 {_U1}\nSec 4.2 {_U2}\nSec 4.3 {_T3}",
     [R("R-ELIG-V1", "threshold", "eligible", {"field": "cgpa", "operator": ">=", "value": 8.0}, "cgpa >= 8.0", "4.1", _T1, "PV1", status="superseded"),
      R("R-REC-V1", "obligation", "upload_recommendation", None, "recommendation_required = true", "4.2", _T2, "PV1", status="superseded"),
      R("R-ORD-V1", "prerequisite", "final_submission", {"prerequisite": "dept_approval", "target": "final_submission", "relation": "BEFORE"}, "dept_approval BEFORE final_submission", "4.3", _T3, "PV1")],
     [R("R-ELIG-V2", "threshold", "eligible", {"field": "cgpa", "operator": ">=", "value": 7.5}, "cgpa >= 7.5", "4.1", _U1, "PV2", sup="R-ELIG-V1"),
      R("R-REC-V2", "conditional_obligation", "upload_recommendation", {"field": "cgpa", "operator": "<", "value": 8.0}, "IF cgpa < 8.0 THEN rec", "4.2", _U2, "PV2", sup="R-REC-V1"),
      R("R-ORD-V1", "prerequisite", "final_submission", {"prerequisite": "dept_approval", "target": "final_submission", "relation": "BEFORE"}, "dept_approval BEFORE final_submission", "4.3", _T3, "PV1")],
     WF("WF-T1", "WF-T1-V1", [START("WF-T1"), GATE("WF-T1", "cgpa", ">=", 8.0, "R-ELIG-V1"),
        STEP("WF-T1", "upload_recommendation", "recommendation_file", True, None, "R-REC-V1"),
        PAPPR("WF-T1", "NODE-APPR", "Department Approval", "dept_approval", "R-ORD-V1"),
        SUBMIT("WF-T1")],
        linear(["NODE-START", "NODE-GATE", "NODE-STEP", "NODE-APPR", "NODE-SUBMIT"])),
     {"type": "COMPOUND", "field": "cgpa", "old": 8.0, "new": 7.5, "affected_rule_ids": ["R-ELIG-V2", "R-REC-V2"]},
     {"kinds": ["wrong_rejection", "unnecessary_burden"],
      "domains": {"wrong_rejection": [{"field": "cgpa", "operator": ">=", "value": 7.5}, {"field": "cgpa", "operator": "<", "value": 8.0}],
                  "unnecessary_burden": [{"field": "cgpa", "operator": ">=", "value": 8.0}]}},
     {"must_include_nodes": ["NODE-GATE", "NODE-STEP"], "may_include_nodes": ["NODE-START"], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"gate": {"field": "cgpa", "operator": ">=", "value": 7.5}},
      "forbidden_operations": ["REMOVE_NODE:NODE-APPR"], "max_locality_cost": 9.0})

# ---------------- 02 THRESH-TIGHTEN-001 (dev, reimbursement limit) ----------------
case("THRESH-TIGHTEN-001", "threshold_tightening", "reimbursement", "dev",
     "Sec 2.1 Claims up to amount <= 100000 are accepted.\nSec 2.2 All claimants must provide a receipt.",
     "Sec 2.1 Claims up to amount <= 50000 are accepted.\nSec 2.2 All claimants must provide a receipt.",
     [R("R-LIM-V1", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 100000}, "amount <= 100000", "2.1", "Claims up to amount <= 100000 are accepted.", "PV1", status="superseded"),
      R("R-RCT-V1", "obligation", "upload_receipt", None, "receipt = true", "2.2", "All claimants must provide a receipt.", "PV1")],
     [R("R-LIM-V2", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 50000}, "amount <= 50000", "2.1", "Claims up to amount <= 50000 are accepted.", "PV2", sup="R-LIM-V1"),
      R("R-RCT-V1", "obligation", "upload_receipt", None, "receipt = true", "2.2", "All claimants must provide a receipt.", "PV1")],
     WF("WF-T2", "WF-T2-V1", [START("WF-T2"), GATE("WF-T2", "amount", "<=", 100000, "R-LIM-V1"),
        STEP("WF-T2", "upload_receipt", "receipt_file", True, None, "R-RCT-V1"), SUBMIT("WF-T2")],
        linear(["NODE-START", "NODE-GATE", "NODE-STEP", "NODE-SUBMIT"])),
     {"type": "THRESHOLD_TIGHTENED", "field": "amount", "old": 100000, "new": 50000, "affected_rule_ids": ["R-LIM-V2"]},
     {"kinds": ["wrong_acceptance"],
      "domains": {"wrong_acceptance": [{"field": "amount", "operator": ">", "value": 50000}, {"field": "amount", "operator": "<=", "value": 100000}]}},
     {"must_include_nodes": ["NODE-GATE"], "may_include_nodes": ["NODE-START"], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"gate": {"field": "amount", "operator": "<=", "value": 50000}},
      "forbidden_operations": ["REMOVE_NODE:NODE-STEP"], "max_locality_cost": 6.0})

# ---------------- 03 REQ-REMOVE-001 (dev) ----------------
case("REQ-REMOVE-001", "requirement_removed", "university_application", "dev",
     "Sec 4.2 All applicants must provide a faculty recommendation.",
     "Sec 4.2 No recommendation is required. (Clause removed.)",
     [R("R-REC-V1", "obligation", "upload_recommendation", None, "recommendation_required = true", "4.2", "All applicants must provide a faculty recommendation.", "PV1", status="superseded")],
     [],
     WF("WF-T3", "WF-T3-V1", [START("WF-T3"),
        STEP("WF-T3", "upload_recommendation", "recommendation_file", True, None, "R-REC-V1"), SUBMIT("WF-T3")],
        linear(["NODE-START", "NODE-STEP", "NODE-SUBMIT"])),
     {"type": "OBLIGATION_REMOVED", "action": "upload_recommendation", "affected_rule_ids": []},
     {"kinds": ["unnecessary_burden"], "domains": {"unnecessary_burden": []}},
     {"must_include_nodes": ["NODE-STEP"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"required": {"action": "upload_recommendation", "value": False}},
      "forbidden_operations": [], "max_locality_cost": 6.0})

# ---------------- 04 REQ-ADD-001 (dev, transcript added, node missing) ----------------
case("REQ-ADD-001", "requirement_added", "university_application", "dev",
     "Sec 5.1 Applicants must have CGPA >= 7.5.",
     "Sec 5.1 Applicants must have CGPA >= 7.5.\nSec 5.2 All applicants must provide a transcript.",
     [R("R-ELIG-V1", "threshold", "eligible", {"field": "cgpa", "operator": ">=", "value": 7.5}, "cgpa >= 7.5", "5.1", "Applicants must have CGPA >= 7.5.", "PV1")],
     [R("R-ELIG-V1", "threshold", "eligible", {"field": "cgpa", "operator": ">=", "value": 7.5}, "cgpa >= 7.5", "5.1", "Applicants must have CGPA >= 7.5.", "PV1"),
      R("R-TR-V2", "obligation", "upload_transcript", None, "transcript = true", "5.2", "All applicants must provide a transcript.", "PV2")],
     WF("WF-T4", "WF-T4-V1", [START("WF-T4"), GATE("WF-T4", "cgpa", ">=", 7.5, "R-ELIG-V1"), SUBMIT("WF-T4")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "OBLIGATION_ADDED", "action": "upload_transcript", "affected_rule_ids": ["R-TR-V2"]},
     {"kinds": ["missing_safeguard"], "domains": {"missing_safeguard": [{"field": "cgpa", "operator": ">=", "value": 7.5}]}},
     {"must_include_nodes": [], "may_include_nodes": ["NODE-GATE", "NODE-SUBMIT"], "must_not_include_nodes": []},
     {"required_effect": {"required": {"action": "upload_transcript", "value": True}},
      "forbidden_operations": [], "max_locality_cost": 9.0})

# ---------------- 05 COND-001 (dev, approval always -> amount>50000) ----------------
case("COND-001", "conditional_requirement", "reimbursement", "dev",
     "Sec 3.1 All claims must receive manager approval.",
     "Sec 3.1 Manager approval is required only when amount > 50000.",
     [R("R-AP-V1", "obligation", "manager_approval", None, "manager_approval = true", "3.1", "All claims must receive manager approval.", "PV1", status="superseded")],
     [R("R-AP-V2", "conditional_obligation", "manager_approval", {"field": "amount", "operator": ">", "value": 50000}, "IF amount > 50000 THEN approval", "3.1", "Manager approval is required only when amount > 50000.", "PV2", sup="R-AP-V1")],
     WF("WF-T5", "WF-T5-V1", [START("WF-T5"),
        APPR("WF-T5", "NODE-APPR", "Manager Approval", "manager_approval", "manager_signoff", True, None, "R-AP-V1"),
        SUBMIT("WF-T5")],
        linear(["NODE-START", "NODE-APPR", "NODE-SUBMIT"])),
     {"type": "CONDITION_CHANGED", "action": "manager_approval", "affected_rule_ids": ["R-AP-V2"]},
     {"kinds": ["unnecessary_burden"],
      "domains": {"unnecessary_burden": [{"field": "amount", "operator": "<=", "value": 50000}]}},
     {"must_include_nodes": ["NODE-APPR"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"required_probe": {"action": "manager_approval",
                                             "case_true": {"amount": 60000}, "case_false": {"amount": 40000}}},
      "forbidden_operations": ["REMOVE_NODE:NODE-APPR"], "max_locality_cost": 9.0})

# ---------------- 06 EXC-ADD-001 (dev, category X exempt from rec) ----------------
case("EXC-ADD-001", "exception_added", "university_application", "dev",
     "Sec 4.2 All applicants must provide a faculty recommendation.",
     "Sec 4.2 All applicants must provide a faculty recommendation.\nSec 4.3 Recommendation is waived if applicant category is X.",
     [R("R-REC-V1", "obligation", "upload_recommendation", None, "recommendation_required = true", "4.2", "All applicants must provide a faculty recommendation.", "PV1")],
     [R("R-REC-V1", "obligation", "upload_recommendation", None, "recommendation_required = true", "4.2", "All applicants must provide a faculty recommendation.", "PV1"),
      R("R-EXC-V2", "exception", "upload_recommendation", {"field": "category", "operator": "==", "value": "X"}, "waive rec IF category == X", "4.3", "Recommendation is waived if applicant category is X.", "PV2")],
     WF("WF-T6", "WF-T6-V1", [START("WF-T6"),
        STEP("WF-T6", "upload_recommendation", "recommendation_file", True, None, "R-REC-V1"), SUBMIT("WF-T6")],
        linear(["NODE-START", "NODE-STEP", "NODE-SUBMIT"])),
     {"type": "EXCEPTION_ADDED", "action": "upload_recommendation",
      "exception_condition": {"field": "category", "operator": "==", "value": "X"},
      "affected_rule_ids": ["R-EXC-V2"]},
     {"kinds": ["unnecessary_burden"],
      "domains": {"unnecessary_burden": [{"field": "category", "operator": "==", "value": "X"}]}},
     {"must_include_nodes": ["NODE-STEP"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"required_probe": {"action": "upload_recommendation",
                                             "case_true": {"category": "general"}, "case_false": {"category": "X"}}},
      "forbidden_operations": [], "max_locality_cost": 9.0})

# ---------------- 07 ORDER-001 (dev, payment-before-verify amended to verify-first) ----------------
case("ORDER-001", "ordering_change", "reimbursement", "dev",
     "Sec 2.3 Payment must occur before verification.",
     "Sec 2.3 Payment must occur after verification.",
     [R("R-ORD-V1", "prerequisite", "verification", {"prerequisite": "payment", "target": "verification", "relation": "BEFORE"}, "payment BEFORE verification", "2.3", "Payment must occur before verification.", "PV1", subj="workflow", status="superseded")],
     [R("R-ORD-V2", "prerequisite", "payment", {"prerequisite": "verification", "target": "payment", "relation": "BEFORE"}, "verification BEFORE payment", "2.3", "Payment must occur after verification.", "PV2", sup="R-ORD-V1", subj="workflow")],
     WF("WF-T7", "WF-T7-V1", [START("WF-T7"), PAY("WF-T7"), VERIFY("WF-T7"), SUBMIT("WF-T7")],
        linear(["NODE-START", "NODE-PAY", "NODE-VERIFY", "NODE-SUBMIT"])),
     {"type": "PREREQUISITE_ADDED", "affected_rule_ids": ["R-ORD-V1"]},
     {"kinds": ["wrong_journey"], "domains": {"wrong_journey": []}},
     {"must_include_nodes": ["NODE-PAY", "NODE-VERIFY"], "may_include_nodes": [], "must_not_include_nodes": []},
     {"required_effect": {"order_ok": True}, "forbidden_operations": [], "max_locality_cost": 12.0})

# ---------------- 08 PRE-ADD-001 (dev, dept approval prerequisite missing) ----------------
case("PRE-ADD-001", "prerequisite_added", "university_application", "dev",
     "Sec 1.1 Applicants must have CGPA >= 7.5.",
     "Sec 1.1 Applicants must have CGPA >= 7.5.\nSec 1.2 Department approval must occur before final submission.",
     [R("R-ELIG-V1", "threshold", "eligible", {"field": "cgpa", "operator": ">=", "value": 7.5}, "cgpa >= 7.5", "1.1", "Applicants must have CGPA >= 7.5.", "PV1")],
     [R("R-ELIG-V1", "threshold", "eligible", {"field": "cgpa", "operator": ">=", "value": 7.5}, "cgpa >= 7.5", "1.1", "Applicants must have CGPA >= 7.5.", "PV1"),
      R("R-ORD-V2", "prerequisite", "final_submission", {"prerequisite": "dept_approval", "target": "final_submission", "relation": "BEFORE"}, "dept_approval BEFORE final_submission", "1.2", "Department approval must occur before final submission.", "PV2", subj="workflow")],
     WF("WF-T8", "WF-T8-V1", [START("WF-T8"), GATE("WF-T8", "cgpa", ">=", 7.5, "R-ELIG-V1"), SUBMIT("WF-T8")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "PREREQUISITE_ADDED", "affected_rule_ids": ["R-ORD-V2"]},
     {"kinds": ["wrong_journey"], "domains": {"wrong_journey": []}},
     {"must_include_nodes": [], "may_include_nodes": ["NODE-GATE", "NODE-SUBMIT"], "must_not_include_nodes": []},
     {"required_effect": {"order_ok": True}, "forbidden_operations": [], "max_locality_cost": 14.0})

# ---------------- 09 DL-EXT-001 (dev, deadline extension) ----------------
case("DL-EXT-001", "deadline_extended", "university_application", "dev",
     "Sec 6.1 Applications must be submitted by September 25.",
     "Sec 6.1 Applications must be submitted by September 30.",
     [R("R-DL-V1", "deadline", "submit_claim", {"field": "submission_date", "operator": "<=", "value": "2026-09-25"}, "submission_date <= 2026-09-25", "6.1", "Applications must be submitted by September 25.", "PV1", status="superseded")],
     [R("R-DL-V2", "deadline", "submit_claim", {"field": "submission_date", "operator": "<=", "value": "2026-09-30"}, "submission_date <= 2026-09-30", "6.1", "Applications must be submitted by September 30.", "PV2", sup="R-DL-V1")],
     WF("WF-T9", "WF-T9-V1", [START("WF-T9"), DLGATE("WF-T9", "2026-09-25", "R-DL-V1"), SUBMIT("WF-T9")],
        linear(["NODE-START", "NODE-DL", "NODE-SUBMIT"])),
     {"type": "DEADLINE_EXTENDED", "field": "submission_date", "old": "2026-09-25", "new": "2026-09-30", "affected_rule_ids": ["R-DL-V2"]},
     {"kinds": ["deadline_mismatch"],
      "domains": {"deadline_mismatch": [{"field": "submission_date", "operator": ">", "value": "2026-09-25"}, {"field": "submission_date", "operator": "<=", "value": "2026-09-30"}]}},
     {"must_include_nodes": ["NODE-DL"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"deadline": {"field": "submission_date", "operator": "<=", "value": "2026-09-30"}},
      "forbidden_operations": [], "max_locality_cost": 6.0})

# ---------------- 10-11 no-ops (dev) ----------------
case("NOOP-PARA-001", "semantic_paraphrase", "university_application", "dev",
     "Sec 6.1 Applications must be submitted by September 30.",
     "Sec 6.1 Applications are required to be submitted no later than September 30.",
     [R("R-DL-V1", "deadline", "submit_claim", {"field": "submission_date", "operator": "<=", "value": "2026-09-30"}, "submission_date <= 2026-09-30", "6.1", "Applications must be submitted by September 30.", "PV1")],
     [R("R-DL-V1", "deadline", "submit_claim", {"field": "submission_date", "operator": "<=", "value": "2026-09-30"}, "submission_date <= 2026-09-30", "6.1", "Applications are required to be submitted no later than September 30.", "PV1")],
     WF("WF-T10", "WF-T10-V1", [START("WF-T10"), DLGATE("WF-T10", "2026-09-30", "R-DL-V1"), SUBMIT("WF-T10")],
        linear(["NODE-START", "NODE-DL", "NODE-SUBMIT"])),
     {"type": "SEMANTICS_UNCHANGED", "affected_rule_ids": []},
     {"no_witness": True}, {"must_include_nodes": [], "may_include_nodes": [], "must_not_include_nodes": ["NODE-DL"]},
     {"required_effect": {}, "forbidden_operations": [], "max_locality_cost": 0.0})

case("NOOP-RENUM-001", "section_renumbering", "university_application", "dev",
     "Sec 4.2 All applicants must provide a faculty recommendation.",
     "Sec 5.1 All applicants must provide a faculty recommendation.",
     [R("R-REC-V1", "obligation", "upload_recommendation", None, "recommendation_required = true", "4.2", "All applicants must provide a faculty recommendation.", "PV1")],
     [R("R-REC-V1", "obligation", "upload_recommendation", None, "recommendation_required = true", "5.1", "All applicants must provide a faculty recommendation.", "PV1")],
     WF("WF-T11", "WF-T11-V1", [START("WF-T11"),
        STEP("WF-T11", "upload_recommendation", "recommendation_file", True, None, "R-REC-V1"), SUBMIT("WF-T11")],
        linear(["NODE-START", "NODE-STEP", "NODE-SUBMIT"])),
     {"type": "PROVENANCE_ONLY", "affected_rule_ids": []},
     {"no_witness": True}, {"must_include_nodes": [], "may_include_nodes": [], "must_not_include_nodes": ["NODE-STEP"]},
     {"required_effect": {}, "forbidden_operations": [], "max_locality_cost": 0.0})

# ---------------- 12-13 escalation (dev) ----------------
case("AMBIG-001", "ambiguity", "university_application", "dev",
     "Sec 4.1 Applicants must have CGPA >= 8.0.",
     "Sec 4.1 Applicants with strong academic standing may receive an exemption.",
     [R("R-ELIG-V1", "threshold", "eligible", {"field": "cgpa", "operator": ">=", "value": 8.0}, "cgpa >= 8.0", "4.1", "Applicants must have CGPA >= 8.0.", "PV1")],
     [],
     WF("WF-T12", "WF-T12-V1", [START("WF-T12"), GATE("WF-T12", "cgpa", ">=", 8.0, "R-ELIG-V1"), SUBMIT("WF-T12")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "NEEDS_REVIEW", "affected_rule_ids": []},
     {"escalation": "ambiguity"}, {"must_include_nodes": [], "may_include_nodes": [], "must_not_include_nodes": []},
     {"required_effect": {}, "forbidden_operations": [], "max_locality_cost": 0.0})

case("CONFL-001", "contradiction", "university_application", "dev",
     "Sec 4.1 Applicants must have CGPA >= 8.0.",
     "Sec 4.1 Applicants must have CGPA >= 7.5.\nSec 4.5 Applicants must have CGPA >= 8.0.",
     [R("R-ELIG-V1", "threshold", "eligible", {"field": "cgpa", "operator": ">=", "value": 8.0}, "cgpa >= 8.0", "4.1", "Applicants must have CGPA >= 8.0.", "PV1")],
     [],
     WF("WF-T12", "WF-T12-V1", [START("WF-T12"), GATE("WF-T12", "cgpa", ">=", 8.0, "R-ELIG-V1"), SUBMIT("WF-T12")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "CONFLICT", "affected_rule_ids": []},
     {"escalation": "conflict"}, {"must_include_nodes": [], "may_include_nodes": [], "must_not_include_nodes": []},
     {"required_effect": {}, "forbidden_operations": [], "max_locality_cost": 0.0})

# ---------------- EVAL cases ----------------
case("THRESH-RELAX-002", "threshold_relaxation", "internship", "eval",
     "Sec 3.1 Interns must have score >= 80.",
     "Sec 3.1 Interns must have score >= 75.",
     [R("R-SC-V1", "threshold", "eligible", {"field": "score", "operator": ">=", "value": 80}, "score >= 80", "3.1", "Interns must have score >= 80.", "PV1", status="superseded")],
     [R("R-SC-V2", "threshold", "eligible", {"field": "score", "operator": ">=", "value": 75}, "score >= 75", "3.1", "Interns must have score >= 75.", "PV2", sup="R-SC-V1")],
     WF("WF-E1", "WF-E1-V1", [START("WF-E1"), GATE("WF-E1", "score", ">=", 80, "R-SC-V1"), SUBMIT("WF-E1")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "THRESHOLD_RELAXED", "field": "score", "old": 80, "new": 75, "affected_rule_ids": ["R-SC-V2"]},
     {"kinds": ["wrong_rejection"],
      "domains": {"wrong_rejection": [{"field": "score", "operator": ">=", "value": 75}, {"field": "score", "operator": "<", "value": 80}]}},
     {"must_include_nodes": ["NODE-GATE"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"gate": {"field": "score", "operator": ">=", "value": 75}},
      "forbidden_operations": [], "max_locality_cost": 6.0})

case("THRESH-TIGHTEN-002", "threshold_tightening", "housing_assistance", "eval",
     "Sec 1.1 Households with income <= 60000 are eligible.",
     "Sec 1.1 Households with income <= 40000 are eligible.",
     [R("R-IN-V1", "threshold", "eligible", {"field": "income", "operator": "<=", "value": 60000}, "income <= 60000", "1.1", "Households with income <= 60000 are eligible.", "PV1", status="superseded")],
     [R("R-IN-V2", "threshold", "eligible", {"field": "income", "operator": "<=", "value": 40000}, "income <= 40000", "1.1", "Households with income <= 40000 are eligible.", "PV2", sup="R-IN-V1")],
     WF("WF-E2", "WF-E2-V1", [START("WF-E2"), GATE("WF-E2", "income", "<=", 60000, "R-IN-V1"), SUBMIT("WF-E2")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "THRESHOLD_TIGHTENED", "field": "income", "old": 60000, "new": 40000, "affected_rule_ids": ["R-IN-V2"]},
     {"kinds": ["wrong_acceptance"],
      "domains": {"wrong_acceptance": [{"field": "income", "operator": ">", "value": 40000}, {"field": "income", "operator": "<=", "value": 60000}]}},
     {"must_include_nodes": ["NODE-GATE"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"gate": {"field": "income", "operator": "<=", "value": 40000}},
      "forbidden_operations": [], "max_locality_cost": 6.0})

case("REQ-REMOVE-002", "requirement_removed", "reimbursement", "eval",
     "Sec 3.1 All claims must receive manager approval.",
     "Sec 3.1 No manager approval is required. (Clause removed.)",
     [R("R-AP-V1", "obligation", "manager_approval", None, "manager_approval = true", "3.1", "All claims must receive manager approval.", "PV1", status="superseded")],
     [],
     WF("WF-E3", "WF-E3-V1", [START("WF-E3"),
        APPR("WF-E3", "NODE-APPR", "Manager Approval", "manager_approval", "manager_signoff", True, None, "R-AP-V1"),
        SUBMIT("WF-E3")],
        linear(["NODE-START", "NODE-APPR", "NODE-SUBMIT"])),
     {"type": "OBLIGATION_REMOVED", "action": "manager_approval", "affected_rule_ids": []},
     {"kinds": ["unnecessary_burden"], "domains": {"unnecessary_burden": []}},
     {"must_include_nodes": ["NODE-APPR"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"required": {"action": "manager_approval", "value": False}},
      "forbidden_operations": [], "max_locality_cost": 6.0})

case("REQ-ADD-002", "requirement_added", "reimbursement", "eval",
     "Sec 1.1 Claims up to amount <= 50000 are accepted.",
     "Sec 1.1 Claims up to amount <= 50000 are accepted.\nSec 1.5 All claims must complete identity verification.",
     [R("R-LIM-V1", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 50000}, "amount <= 50000", "1.1", "Claims up to amount <= 50000 are accepted.", "PV1")],
     [R("R-LIM-V1", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 50000}, "amount <= 50000", "1.1", "Claims up to amount <= 50000 are accepted.", "PV1"),
      R("R-IDV-V2", "obligation", "identity_verification", None, "identity_verification = true", "1.5", "All claims must complete identity verification.", "PV2")],
     WF("WF-E4", "WF-E4-V1", [START("WF-E4"), GATE("WF-E4", "amount", "<=", 50000, "R-LIM-V1"), SUBMIT("WF-E4")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "OBLIGATION_ADDED", "action": "identity_verification", "affected_rule_ids": ["R-IDV-V2"]},
     {"kinds": ["missing_safeguard"], "domains": {"missing_safeguard": [{"field": "amount", "operator": "<=", "value": 50000}]}},
     {"must_include_nodes": [], "may_include_nodes": ["NODE-GATE", "NODE-SUBMIT"], "must_not_include_nodes": []},
     {"required_effect": {"required": {"action": "identity_verification", "value": True}},
      "forbidden_operations": [], "max_locality_cost": 9.0})

case("COND-002", "conditional_requirement", "university_application", "eval",
     "Sec 4.2 All applicants must provide a transcript.",
     "Sec 4.2 A transcript is required only when backlogs > 0.",
     [R("R-TR-V1", "obligation", "upload_transcript", None, "transcript = true", "4.2", "All applicants must provide a transcript.", "PV1", status="superseded")],
     [R("R-TR-V2", "conditional_obligation", "upload_transcript", {"field": "backlogs", "operator": ">", "value": 0}, "IF backlogs > 0 THEN transcript", "4.2", "A transcript is required only when backlogs > 0.", "PV2", sup="R-TR-V1")],
     WF("WF-E5", "WF-E5-V1", [START("WF-E5"),
        STEP("WF-E5", "upload_transcript", "transcript_file", True, None, "R-TR-V1"), SUBMIT("WF-E5")],
        linear(["NODE-START", "NODE-STEP", "NODE-SUBMIT"])),
     {"type": "CONDITION_CHANGED", "action": "upload_transcript", "affected_rule_ids": ["R-TR-V2"]},
     {"kinds": ["unnecessary_burden"],
      "domains": {"unnecessary_burden": [{"field": "backlogs", "operator": "==", "value": 0}]}},
     {"must_include_nodes": ["NODE-STEP"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"required_probe": {"action": "upload_transcript",
                                             "case_true": {"backlogs": 2}, "case_false": {"backlogs": 0}}},
      "forbidden_operations": ["REMOVE_NODE:NODE-STEP"], "max_locality_cost": 9.0})

case("EXC-REMOVE-001", "exception_removed", "university_application", "eval",
     "Sec 4.2 All applicants must provide a faculty recommendation.\nSec 4.3 Recommendation is waived if applicant category is X.",
     "Sec 4.2 All applicants must provide a faculty recommendation.",
     [R("R-REC-V1", "obligation", "upload_recommendation", None, "recommendation_required = true", "4.2", "All applicants must provide a faculty recommendation.", "PV1"),
      R("R-EXC-V1", "exception", "upload_recommendation", {"field": "category", "operator": "==", "value": "X"}, "waive rec IF category == X", "4.3", "Recommendation is waived if applicant category is X.", "PV1", status="superseded")],
     [R("R-REC-V1", "obligation", "upload_recommendation", None, "recommendation_required = true", "4.2", "All applicants must provide a faculty recommendation.", "PV1")],
     WF("WF-E6", "WF-E6-V1", [START("WF-E6"),
        STEP("WF-E6", "upload_recommendation", "recommendation_file", True,
             {"field": "category", "operator": "!=", "value": "X"}, "R-REC-V1"), SUBMIT("WF-E6")],
        linear(["NODE-START", "NODE-STEP", "NODE-SUBMIT"])),
     {"type": "EXCEPTION_REMOVED", "action": "upload_recommendation", "affected_rule_ids": []},
     {"kinds": ["missing_safeguard"],
      "domains": {"missing_safeguard": [{"field": "category", "operator": "==", "value": "X"}]}},
     {"must_include_nodes": ["NODE-STEP"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"required": {"action": "upload_recommendation", "value": True}},
      "forbidden_operations": [], "max_locality_cost": 9.0})

case("ORDER-002", "ordering_change", "university_application", "eval",
     "Sec 1.2 Final submission must occur before department approval.",
     "Sec 1.2 Department approval must occur before final submission.",
     [R("R-ORD-V1", "prerequisite", "dept_approval", {"prerequisite": "final_submission", "target": "dept_approval", "relation": "BEFORE"}, "final_submission BEFORE dept_approval", "1.2", "Final submission must occur before department approval.", "PV1", subj="workflow", status="superseded")],
     [R("R-ORD-V2", "prerequisite", "final_submission", {"prerequisite": "dept_approval", "target": "final_submission", "relation": "BEFORE"}, "dept_approval BEFORE final_submission", "1.2", "Department approval must occur before final submission.", "PV2", sup="R-ORD-V1", subj="workflow")],
     WF("WF-E7", "WF-E7-V1",
        [START("WF-E7"), SUBMIT("WF-E7"),
         PAPPR("WF-E7", "NODE-APPR", "Department Approval", "dept_approval", "R-ORD-V1")],
        linear(["NODE-START", "NODE-SUBMIT", "NODE-APPR"])),
     {"type": "PREREQUISITE_ADDED", "affected_rule_ids": ["R-ORD-V1"]},
     {"kinds": ["wrong_journey"], "domains": {"wrong_journey": []}},
     {"must_include_nodes": ["NODE-APPR", "NODE-SUBMIT"], "may_include_nodes": [], "must_not_include_nodes": []},
     {"required_effect": {"order_ok": True}, "forbidden_operations": [], "max_locality_cost": 12.0})

case("DL-TIGHT-001", "deadline_tightened", "reimbursement", "eval",
     "Sec 2.4 Claims MUST NOT be submitted after 2026-09-30.",
     "Sec 2.4 Claims MUST NOT be submitted after 2026-09-25.",
     [R("R-DL-V1", "deadline", "submit_claim", {"field": "submission_date", "operator": "<=", "value": "2026-09-30"}, "submission_date <= 2026-09-30", "2.4", "Claims MUST NOT be submitted after 2026-09-30.", "PV1", status="superseded")],
     [R("R-DL-V2", "deadline", "submit_claim", {"field": "submission_date", "operator": "<=", "value": "2026-09-25"}, "submission_date <= 2026-09-25", "2.4", "Claims MUST NOT be submitted after 2026-09-25.", "PV2", sup="R-DL-V1")],
     WF("WF-E8", "WF-E8-V1", [START("WF-E8"), DLGATE("WF-E8", "2026-09-30", "R-DL-V1"), SUBMIT("WF-E8")],
        linear(["NODE-START", "NODE-DL", "NODE-SUBMIT"])),
     {"type": "DEADLINE_TIGHTENED", "field": "submission_date", "old": "2026-09-30", "new": "2026-09-25", "affected_rule_ids": ["R-DL-V2"]},
     {"kinds": ["deadline_mismatch"],
      "domains": {"deadline_mismatch": [{"field": "submission_date", "operator": ">", "value": "2026-09-25"}, {"field": "submission_date", "operator": "<=", "value": "2026-09-30"}]}},
     {"must_include_nodes": ["NODE-DL"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"deadline": {"field": "submission_date", "operator": "<=", "value": "2026-09-25"}},
      "forbidden_operations": [], "max_locality_cost": 6.0})

case("NOOP-IRREL-001", "irrelevant_edit", "reimbursement", "eval",
     "Sec 1.0 This policy governs employee claims.\nSec 1.1 Claims up to amount <= 50000 are accepted.",
     "Sec 1.0 This policy governs employee claims fairly and transparently.\nSec 1.1 Claims up to amount <= 50000 are accepted.",
     [R("R-LIM-V1", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 50000}, "amount <= 50000", "1.1", "Claims up to amount <= 50000 are accepted.", "PV1")],
     [R("R-LIM-V1", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 50000}, "amount <= 50000", "1.1", "Claims up to amount <= 50000 are accepted.", "PV1")],
     WF("WF-E9", "WF-E9-V1", [START("WF-E9"), GATE("WF-E9", "amount", "<=", 50000, "R-LIM-V1"), SUBMIT("WF-E9")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "SEMANTICS_UNCHANGED", "affected_rule_ids": []},
     {"no_witness": True}, {"must_include_nodes": [], "may_include_nodes": [], "must_not_include_nodes": ["NODE-GATE"]},
     {"required_effect": {}, "forbidden_operations": [], "max_locality_cost": 0.0})

case("AMBIG-002", "ambiguity", "reimbursement", "eval",
     "Sec 3.1 All claims must receive manager approval.",
     "Sec 3.1 Suitable candidates may receive an exemption from approval.",
     [R("R-AP-V1", "obligation", "manager_approval", None, "manager_approval = true", "3.1", "All claims must receive manager approval.", "PV1")],
     [],
     WF("WF-E10", "WF-E10-V1", [START("WF-E10"),
        APPR("WF-E10", "NODE-APPR", "Manager Approval", "manager_approval", "manager_signoff", True, None, "R-AP-V1"),
        SUBMIT("WF-E10")],
        linear(["NODE-START", "NODE-APPR", "NODE-SUBMIT"])),
     {"type": "NEEDS_REVIEW", "affected_rule_ids": []},
     {"escalation": "ambiguity"}, {"must_include_nodes": [], "may_include_nodes": [], "must_not_include_nodes": []},
     {"required_effect": {}, "forbidden_operations": [], "max_locality_cost": 0.0})

case("CONFL-002", "contradiction", "reimbursement", "eval",
     "Sec 2.1 Claims up to amount <= 50000 are accepted.",
     "Sec 2.1 Claims up to amount <= 50000 are accepted.\nSec 2.9 Claims up to amount <= 75000 are accepted.",
     [R("R-LIM-V1", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 50000}, "amount <= 50000", "2.1", "Claims up to amount <= 50000 are accepted.", "PV1")],
     [],
     WF("WF-E11", "WF-E11-V1", [START("WF-E11"), GATE("WF-E11", "amount", "<=", 50000, "R-LIM-V1"), SUBMIT("WF-E11")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "CONFLICT", "affected_rule_ids": []},
     {"escalation": "conflict"}, {"must_include_nodes": [], "may_include_nodes": [], "must_not_include_nodes": []},
     {"required_effect": {}, "forbidden_operations": [], "max_locality_cost": 0.0})

case("COMPOUND-001", "compound_amendment", "university_application", "eval",
     "Sec 4.1 Applicants must have CGPA >= 8.0.",
     "Sec 4.1 Applicants must have CGPA >= 7.8.\nSec 4.4 All applicants must provide a transcript.",
     [R("R-ELIG-V1", "threshold", "eligible", {"field": "cgpa", "operator": ">=", "value": 8.0}, "cgpa >= 8.0", "4.1", "Applicants must have CGPA >= 8.0.", "PV1", status="superseded")],
     [R("R-ELIG-V2", "threshold", "eligible", {"field": "cgpa", "operator": ">=", "value": 7.8}, "cgpa >= 7.8", "4.1", "Applicants must have CGPA >= 7.8.", "PV2", sup="R-ELIG-V1"),
      R("R-TR-V2", "obligation", "upload_transcript", None, "transcript = true", "4.4", "All applicants must provide a transcript.", "PV2")],
     WF("WF-E12", "WF-E12-V1", [START("WF-E12"), GATE("WF-E12", "cgpa", ">=", 8.0, "R-ELIG-V1"), SUBMIT("WF-E12")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "COMPOUND", "field": "cgpa", "old": 8.0, "new": 7.8, "affected_rule_ids": ["R-ELIG-V2", "R-TR-V2"]},
     {"kinds": ["wrong_rejection", "missing_safeguard"],
      "domains": {"wrong_rejection": [{"field": "cgpa", "operator": ">=", "value": 7.8}, {"field": "cgpa", "operator": "<", "value": 8.0}],
                  "missing_safeguard": [{"field": "cgpa", "operator": ">=", "value": 7.8}]}},
     {"must_include_nodes": ["NODE-GATE"], "may_include_nodes": ["NODE-SUBMIT"], "must_not_include_nodes": []},
     {"required_effect": {"gate": {"field": "cgpa", "operator": ">=", "value": 7.8}},
      "forbidden_operations": [], "max_locality_cost": 12.0})

case("EXC-ADD-002", "exception_added", "university_application", "eval",
     "Sec 4.2 All applicants must provide a transcript.",
     "Sec 4.2 All applicants must provide a transcript.\nSec 4.5 Transcript is waived if applicant category is STAFF.",
     [R("R-TR-V1", "obligation", "upload_transcript", None, "transcript = true", "4.2", "All applicants must provide a transcript.", "PV1")],
     [R("R-TR-V1", "obligation", "upload_transcript", None, "transcript = true", "4.2", "All applicants must provide a transcript.", "PV1"),
      R("R-EXC-V2", "exception", "upload_transcript", {"field": "category", "operator": "==", "value": "STAFF"}, "waive transcript IF category == STAFF", "4.5", "Transcript is waived if applicant category is STAFF.", "PV2")],
     WF("WF-E13", "WF-E13-V1", [START("WF-E13"),
        STEP("WF-E13", "upload_transcript", "transcript_file", True, None, "R-TR-V1"), SUBMIT("WF-E13")],
        linear(["NODE-START", "NODE-STEP", "NODE-SUBMIT"])),
     {"type": "EXCEPTION_ADDED", "action": "upload_transcript",
      "exception_condition": {"field": "category", "operator": "==", "value": "STAFF"},
      "affected_rule_ids": ["R-EXC-V2"]},
     {"kinds": ["unnecessary_burden"],
      "domains": {"unnecessary_burden": [{"field": "category", "operator": "==", "value": "STAFF"}]}},
     {"must_include_nodes": ["NODE-STEP"], "may_include_nodes": [], "must_not_include_nodes": ["NODE-SUBMIT"]},
     {"required_effect": {"required_probe": {"action": "upload_transcript",
                                             "case_true": {"category": "general"}, "case_false": {"category": "STAFF"}}},
      "forbidden_operations": [], "max_locality_cost": 9.0})


# ---------------- PROH-001 (dev, prohibition enforced by new gate) ----------------
case("PROH-001", "prohibition_added", "reimbursement", "dev",
     "Sec 1.1 Claims up to amount <= 200000 are accepted.",
     "Sec 1.1 Claims up to amount <= 200000 are accepted.\nSec 1.6 Managers MUST NOT approve claims above amount 100000.",
     [R("R-LIM-V1", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 200000}, "amount <= 200000", "1.1", "Claims up to amount <= 200000 are accepted.", "PV1")],
     [R("R-LIM-V1", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 200000}, "amount <= 200000", "1.1", "Claims up to amount <= 200000 are accepted.", "PV1"),
      R("R-PRO-V2", "prohibition", "approve_claim", {"field": "amount", "operator": ">", "value": 100000}, "FORBID approve_claim WHEN amount > 100000", "1.6", "Managers MUST NOT approve claims above amount 100000.", "PV2")],
     WF("WF-P1", "WF-P1-V1", [START("WF-P1"), GATE("WF-P1", "amount", "<=", 200000, "R-LIM-V1"), SUBMIT("WF-P1")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "PROHIBITION_ADDED", "affected_rule_ids": ["R-PRO-V2"]},
     {"kinds": ["prohibition_breach"],
      "domains": {"prohibition_breach": [{"field": "amount", "operator": ">", "value": 100000}, {"field": "amount", "operator": "<=", "value": 200000}]}},
     {"must_include_nodes": [], "may_include_nodes": ["NODE-GATE", "NODE-SUBMIT"], "must_not_include_nodes": []},
     {"required_effect": {"prohibition_gate": {"field": "amount", "operator": ">", "value": 100000}},
      "forbidden_operations": [], "max_locality_cost": 12.0})

# ---------------- UNSUP-TEMP-001 (dev, temporal phrase outside the language) ----------------
case("UNSUP-TEMP-001", "unsupported_temporal", "reimbursement", "dev",
     "Sec 1.1 Claims up to amount <= 50000 are accepted.",
     "Sec 1.1 Claims up to amount <= 50000 are accepted.\nSec 1.7 Claims must be reviewed within three business days.",
     [R("R-LIM-V1", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 50000}, "amount <= 50000", "1.1", "Claims up to amount <= 50000 are accepted.", "PV1")],
     [R("R-LIM-V1", "threshold", "eligible", {"field": "amount", "operator": "<=", "value": 50000}, "amount <= 50000", "1.1", "Claims up to amount <= 50000 are accepted.", "PV1")],
     WF("WF-U1", "WF-U1-V1", [START("WF-U1"), GATE("WF-U1", "amount", "<=", 50000, "R-LIM-V1"), SUBMIT("WF-U1")],
        linear(["NODE-START", "NODE-GATE", "NODE-SUBMIT"])),
     {"type": "NEEDS_REVIEW", "affected_rule_ids": []},
     {"unsupported": True}, {"must_include_nodes": [], "may_include_nodes": [], "must_not_include_nodes": []},
     {"required_effect": {}, "forbidden_operations": [], "max_locality_cost": 0.0})

# ---------------- UNSUP-NEST-001 (eval, nested exception outside the language) ----------------
case("UNSUP-NEST-001", "unsupported_nested", "university_application", "eval",
     "Sec 4.2 All applicants must provide a transcript.",
     "Sec 4.2 All applicants must provide a transcript unless exempt under clause 9 or clause 12.",
     [R("R-TR-V1", "obligation", "upload_transcript", None, "transcript = true", "4.2", "All applicants must provide a transcript.", "PV1")],
     [R("R-TR-V1", "obligation", "upload_transcript", None, "transcript = true", "4.2", "All applicants must provide a transcript.", "PV1")],
     WF("WF-U2", "WF-U2-V1", [START("WF-U2"),
        STEP("WF-U2", "upload_transcript", "transcript_file", True, None, "R-TR-V1"), SUBMIT("WF-U2")],
        linear(["NODE-START", "NODE-STEP", "NODE-SUBMIT"])),
     {"type": "NEEDS_REVIEW", "affected_rule_ids": []},
     {"unsupported": True}, {"must_include_nodes": [], "may_include_nodes": [], "must_not_include_nodes": []},
     {"required_effect": {}, "forbidden_operations": [], "max_locality_cost": 0.0})


def main():
    import hashlib
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    for c in CASES:
        d = CASES_DIR / c["case_id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps(
            {"case_id": c["case_id"], "family": c["family"], "domain": c["domain"],
             "split": c["split"], "behavioral_change": "escalation" not in c["gold_witness"] and "no_witness" not in c["gold_witness"],
             "repairable": bool(c["gold_repair"].get("required_effect")),
             "requires_human_review": "escalation" in c["gold_witness"],
             "benchmark_version": VERSION,
             "variables": {"cgpa": {"type": "decimal", "min": 0, "max": 10},
                           "amount": {"type": "integer", "min": 0, "max": 200000}}}, indent=2))
        (d / "policy_v1.md").write_text(c["policy_v1"] + "\n")
        (d / "policy_v2.md").write_text(c["policy_v2"] + "\n")
        (d / "rules_v1.json").write_text(json.dumps(c["rules_v1"], indent=2))
        (d / "rules_v2.json").write_text(json.dumps(c["rules_v2"], indent=2))
        (d / "procedure.json").write_text(json.dumps(c["procedure"], indent=2))
        (d / "gold_delta.json").write_text(json.dumps(c["gold_delta"], indent=2))
        (d / "gold_witness.json").write_text(json.dumps(c["gold_witness"], indent=2))
        (d / "gold_localization.json").write_text(json.dumps(c["gold_localization"], indent=2))
        (d / "gold_repair.json").write_text(json.dumps(c["gold_repair"], indent=2))
    manifest = {"benchmark_version": VERSION,
                "total": len(CASES),
                "families": sorted({c["family"] for c in CASES}),
                "splits": {"dev": sum(1 for c in CASES if c["split"] == "dev"),
                           "eval": sum(1 for c in CASES if c["split"] == "eval")},
                "cases": [c["case_id"] for c in CASES]}
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2))
    h = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    (HERE / "BENCHMARK_VERSION").write_text(f"{VERSION}\nmanifest_sha256: {h}\n")
    print(f"wrote {len(CASES)} cases ({manifest['splits']}) manifest_sha256={h[:12]}")


if __name__ == "__main__":
    main()

