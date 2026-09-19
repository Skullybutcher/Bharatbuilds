"""Rule extractor: policy text -> candidate Rule IR (deterministic MVP).

Trust boundary: proposes typed candidates with source spans + confidence;
never declares compliance. Ambiguity/conflict -> NEEDS_REVIEW / BLOCKED.
A model-backed extractor can replace `extract` later; schema validation stays.
"""
from __future__ import annotations
import hashlib
import re

FIELD_ALIASES = [
    (re.compile(r"cgpa", re.I), "cgpa", "decimal"),
    (re.compile(r"\bgpa\b", re.I), "gpa", "decimal"),
    (re.compile(r"(claim\s+)?amount|claim value|reimbursement total", re.I), "amount", "integer"),
    (re.compile(r"\bscore\b", re.I), "score", "decimal"),
    (re.compile(r"\byear\b", re.I), "year", "integer"),
    (re.compile(r"backlogs?", re.I), "backlogs", "integer"),
    (re.compile(r"categor(y|ies)|applicant class", re.I), "category", "enum"),
    (re.compile(r"submission date|submit(?:ted)?(?: on| by)?|filing date", re.I), "submission_date", "date"),
]

ACTION_ALIASES = [
    (re.compile(r"recommendation( letter)?", re.I), "upload_recommendation"),
    (re.compile(r"transcript", re.I), "upload_transcript"),
    (re.compile(r"manager approval|manager sign-?off", re.I), "manager_approval"),
    (re.compile(r"receipt", re.I), "upload_receipt"),
    (re.compile(r"department approval", re.I), "dept_approval"),
    (re.compile(r"identity verification", re.I), "identity_verification"),
    (re.compile(r"faculty recommendation", re.I), "upload_recommendation"),
]

THRESH_RE = re.compile(
    r"(CGPA|GPA|amount|claim amount|score|income|backlogs?|year)\s*(>=|<=|>|<|==)\s*([\d,]+(?:\.\d+)?)", re.I)
ONLY_WHEN_RE = re.compile(
    r"(manager approval|department approval|identity verification|faculty recommendation|recommendation|approval|transcript|verification)[^\n.]{0,60}?required only when\s+([A-Za-z ]+?)\s*(>=|<=|>|<|==)\s*([\d,]+(?:\.\d+)?)", re.I)
WAIVE_RE = re.compile(
    r"(manager approval|recommendation|approval|transcript|fee)[^\n.]{0,60}?(waived|exempt)(?:[^\n.]{0,40}?if\s+([A-Za-z ]+?)\s*(?:is\s+)?([A-Za-z0-9 _-]+))?[\.\n]", re.I)
CATEGORY_RE = re.compile(r"categor\w*\s+(?:is\s+)?([A-Za-z0-9_-]+)", re.I)
BEFORE_RE = re.compile(
    r"([A-Za-z ]+?)\s+must occur (?:before|prior to)\s+([A-Za-z ]+?)[\.\n]", re.I)
AFTER_RE = re.compile(
    r"([A-Za-z ]+?)\s+must occur after\s+([A-Za-z ]+?)[\.\n]", re.I)
MUST_NOT_ABOVE_RE = re.compile(
    r"must not[^\n.]*?\b(approve|pay|submit|accept)\b[^\n.]*?\b(above|over|more than|exceeding)\s+([A-Za-z ]+?)\s*([\d,]+(?:\.\d+)?)", re.I)
REQUIREMENT_VERBS_RE = re.compile(r"\bmust\b|\brequired?\b|\bshall\b|\bprohibit|\bwaiv|\bexempt", re.I)
DEADLINE_RE = re.compile(
    r"(?:no later than|by|before|on or before)\s+(\d{4}-\d{2}-\d{2})", re.I)
MUST_NOT_AFTER_RE = re.compile(r"must not[^\n.]*after\s+(\d{4}-\d{2}-\d{2})", re.I)
MUST_PROVIDE_RE = re.compile(r"all\s+\w+[^\n.]*must\s+(?:provide|upload|submit|complete|receive)\s+([a-z ]+?)[\.\n]", re.I)
SEC_RE = re.compile(r"(?:sec\.?|section|§)\s*(\d+\.\d+)", re.I)
MONTHDAY_RE = re.compile(r"(?:by|no later than|not later than|before)\s+(September|October|August)\s+(\d{1,2})", re.I)

AMBIGUOUS_TERMS = ["strong academic standing", "suitable", "appropriate", "timely manner",
                   "sufficient merit", "good standing", "as needed", "may receive",
                   "reasonable", "adequate", "satisfactory character"]

MONTHS = {"august": "08", "september": "09", "october": "10"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _field(name: str) -> tuple[str, str]:
    for rx, fid, dt in FIELD_ALIASES:
        if rx.search(name or ""):
            return fid, dt
    slug = re.sub(r"\W+", "_", (name or "value").strip().lower()).strip("_")
    return slug or "value", "decimal"


def _action(name: str) -> str:
    for rx, aid in ACTION_ALIASES:
        if rx.search(name or ""):
            return aid
    slug = re.sub(r"\W+", "_", (name or "item").strip().lower()).strip("_")
    return slug or "item"


def extract(policy_text: str, policy_version_id: str = "POLICY-VX",
            effective_from: str = "2026-09-18") -> dict:
    rules, needs_review, conflicts = [], [], []
    lines = policy_text.splitlines()

    def section_of(idx: int) -> str:
        for j in range(idx, -1, -1):
            m = SEC_RE.search(lines[j])
            if m:
                return m.group(1)
        return "?.?"

    low = policy_text.lower()
    for term in AMBIGUOUS_TERMS:
        for i, ln in enumerate(lines):
            if term in ln.lower():
                needs_review.append({"code": "UNCOMPILABLE / NEEDS_REVIEW",
                                     "reason": f"Undefined concept: {term!r}",
                                     "section": section_of(i), "source_text": ln.strip()})

    thresholds: dict = {}
    for m in THRESH_RE.finditer(policy_text):
        # Conditions inside conditional obligations / waivers are not competing
        # top-level thresholds — skip those lines for conflict detection.
        line_start = policy_text.rfind("\n", 0, m.start()) + 1
        line_end = policy_text.find("\n", m.end())
        line = policy_text[line_start:line_end if line_end != -1 else len(policy_text)]
        if ONLY_WHEN_RE.search(line) or "waiv" in line.lower() or "exempt" in line.lower():
            continue
        fid, _dt = _field(m.group(1))
        key = (fid, m.group(2), float(m.group(3).replace(",", "")))
        thresholds.setdefault(key, []).append(m.group(0))
    by_field: dict = {}
    for (fid, op, val) in thresholds:
        by_field.setdefault(fid, set()).add((op, val))
    for fid, sigs in by_field.items():
        if len(sigs) > 1:
            conflicts.append({"code": "CONFLICT / COMPILATION BLOCKED",
                              "reason": f"Multiple active thresholds for {fid}: {sorted(sigs)}; no precedence."})

    n = 0
    matched_lines: set[int] = set()
    def new_id(prefix: str) -> str:
        nonlocal n
        n += 1
        return f"RULE-{prefix}-{n:03d}"

    def base_rule(rid, kind, subject, action, cond, expr, i, conf):
        ln = lines[i].strip()
        # Exact character spans into the source text (page is None for plain
        # text input — never fabricate page numbers).
        char_start = sum(len(L) + 1 for L in lines[:i]) + lines[i].find(ln)
        return {"rule_id": rid, "kind": kind, "subject": subject, "action": action,
                "condition": cond, "normalized_expression": expr,
                "effective_from": effective_from, "effective_to": None, "status": "active",
                "supersedes": None,
                "provenance": {"policy_version_id": policy_version_id,
                               "document_sha256": _sha(policy_text), "page": None,
                               "section": section_of(i), "source_text": ln,
                               "line_start": i + 1, "line_end": i + 1,
                               "char_start": char_start, "char_end": char_start + len(ln),
                               "source_verified": True},
                "extraction": {"model": "processpatch-extractor/0.1.0",
                               "confidence": conf, "review_state": "accepted"}}

    for i, ln in enumerate(lines):
        if not ln.strip() or ln.strip().startswith("#"):
            matched_lines.add(i)
            continue
        m = ONLY_WHEN_RE.search(ln)
        if m:
            fid, dt = _field(m.group(2))
            val = float(m.group(4).replace(",", ""))
            rules.append(base_rule(new_id("REC"), "conditional_obligation", "applicant",
                                   _action(m.group(1)),
                                   {"field": fid, "operator": m.group(3), "value": val, "datatype": dt},
                                   f"IF {fid} {m.group(3)} {m.group(4)} THEN {_action(m.group(1))} = true ELSE false",
                                   i, 0.93))
            matched_lines.add(i)
            continue
        m = WAIVE_RE.search(ln)
        if m and ("if" in ln.lower() or "exempt" in ln.lower()):
            cat_m = CATEGORY_RE.search(ln)
            if cat_m:
                fid, val = "category", cat_m.group(1).strip()
            else:
                fid, _ = _field(m.group(3) or "category")
                val = (m.group(4) or "X").strip()
                if fid == "value":
                    fid = "category"
            rules.append(base_rule(new_id("EXC"), "exception", "applicant", _action(m.group(1)),
                                   {"field": fid, "operator": "==", "value": val, "datatype": "enum"},
                                   f"waive {_action(m.group(1))} IF {fid} == {val}", i, 0.90))
            matched_lines.add(i)
            continue
        m = THRESH_RE.search(ln)
        if m and "recommendation" not in ln.lower() and "approval" not in ln.lower() or \
           (m and re.search(r"(must have|up to|accepted|eligible|minimum|at least|maximum)", ln, re.I)):
            fid, dt = _field(m.group(1))
            val = float(m.group(3).replace(",", ""))
            action = "eligible"
            rules.append(base_rule(new_id("ELIG"), "threshold", "applicant", action,
                                   {"field": fid, "operator": m.group(2), "value": val, "datatype": dt},
                                   f"{fid} {m.group(2)} {m.group(3)}", i, 0.97))
            matched_lines.add(i)
            continue
        m = MUST_PROVIDE_RE.search(ln)
        if m:
            rules.append(base_rule(new_id("OBL"), "obligation", "applicant", _action(m.group(1)),
                                   None, f"{_action(m.group(1))} = true", i, 0.96))
            matched_lines.add(i)
            continue
        m = BEFORE_RE.search(ln) or AFTER_RE.search(ln)
        if m:
            before, after = (m.group(1), m.group(2)) if "before" in (m.group(0).lower()) else (m.group(2), m.group(1))
            rules.append(base_rule(new_id("ORD"), "prerequisite", "workflow", _action(after),
                                   {"prerequisite": _action(before), "target": _action(after), "relation": "BEFORE"},
                                   f"{_action(before)} BEFORE {_action(after)}", i, 0.99))
            matched_lines.add(i)
            continue
        m = MUST_NOT_AFTER_RE.search(ln) or DEADLINE_RE.search(ln)
        if m and ("must not" in ln.lower() or "submit" in ln.lower() or "claim" in ln.lower()):
            rules.append(base_rule(new_id("DL"), "deadline", "applicant", "submit_claim",
                                   {"field": "submission_date", "operator": "<=", "value": m.group(1), "datatype": "date"},
                                   f"submission_date <= {m.group(1)}", i, 0.95))
            matched_lines.add(i)
            continue
        m = MUST_NOT_ABOVE_RE.search(ln)
        if m:
            fid, dt = _field(m.group(3))
            val = float(m.group(4).replace(",", ""))
            rules.append(base_rule(new_id("PRO"), "prohibition", "applicant", _action(m.group(1) + " claim"),
                                   {"field": fid, "operator": ">", "value": val, "datatype": dt},
                                   f"FORBID {_action(m.group(1) + ' claim')} WHEN {fid} > {m.group(4)}", i, 0.90))
            matched_lines.add(i)
            continue
        m = MONTHDAY_RE.search(ln)
        if m and ("submit" in ln.lower()):
            rules.append(base_rule(new_id("DL"), "deadline", "applicant", "submit_claim",
                                   {"field": "submission_date", "operator": "<=",
                                    "value": f"2026-{MONTHS[m.group(1).lower()]}-{int(m.group(2)):02d}", "datatype": "date"},
                                   f"submission_date <= 2026-{MONTHS[m.group(1).lower()]}-{int(m.group(2)):02d}", i, 0.90))

    if not rules and REQUIREMENT_VERBS_RE.search(policy_text):
        # Requirement-like language the bounded parser cannot represent
        # (removals, temporal phrases, nested exceptions): refuse, don't guess.
        needs_review.append({"code": "UNSUPPORTED_CONSTRUCT / NEEDS_REVIEW",
                             "reason": "Requirement-like clause outside the bounded rule language; human review required.",
                             "section": "?", "source_text": policy_text.strip().splitlines()[0][:200]})
    import re as _re2
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if i in matched_lines:
            # Parsed, but qualified ("must provide X unless ..."): the
            # qualifier is outside the bounded language — flag it.
            if _re2.search(r"\bunless\b|\bexcluding\b|\bexcept\b", s, _re2.I):
                needs_review.append({"code": "UNSUPPORTED_CONSTRUCT / NEEDS_REVIEW",
                                     "reason": f"Qualified clause needs human review: {s[:160]}",
                                     "section": section_of(i), "source_text": s[:300]})
            continue
        if REQUIREMENT_VERBS_RE.search(s) or _re2.search(r"\bunless\b|\bexcept\b|\bexcluding\b", s, _re2.I):
            # A substantive clause the parser skipped (or only partially
            # parsed, e.g. "must provide X unless ..."): flag it so qualified
            # language can never slip through silently.
            needs_review.append({"code": "UNSUPPORTED_CONSTRUCT / NEEDS_REVIEW",
                                 "reason": f"Unparsed substantive clause: {s[:160]}",
                                 "section": section_of(i), "source_text": s[:300]})

    status = "NEEDS_REVIEW" if needs_review else ("CONFLICT" if conflicts else "EXTRACTED")
    return {"rules": rules, "needs_review": needs_review, "conflicts": conflicts, "status": status}
