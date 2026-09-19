"""Normalizer: validate Rule IR + typed semantic delta between rule versions.

Delta types: THRESHOLD_RELAXED | THRESHOLD_TIGHTENED | OBLIGATION_ADDED |
OBLIGATION_REMOVED | CONDITION_CHANGED | EXCEPTION_ADDED | EXCEPTION_REMOVED |
PREREQUISITE_ADDED | PREREQUISITE_REMOVED | PREREQUISITE_CHANGED |
DEADLINE_EXTENDED | DEADLINE_TIGHTENED | DEADLINE_ADDED | PROHIBITION_ADDED |
SEMANTICS_UNCHANGED |
PROVENANCE_ONLY | CONFLICT | NEEDS_REVIEW | COMPOUND
"""
from __future__ import annotations

VALID_KINDS = {"threshold", "obligation", "conditional_obligation", "prohibition",
               "prerequisite", "exception", "deadline"}


def validate_rule(r: dict) -> list[str]:
    errs = []
    if r.get("kind") not in VALID_KINDS:
        errs.append(f"unknown kind {r.get('kind')}")
    if not r.get("rule_id"):
        errs.append("missing rule_id")
    if not (r.get("provenance") or {}).get("source_text"):
        errs.append("missing provenance.source_text")
    if r.get("kind") == "conditional_obligation" and not r.get("condition"):
        errs.append("conditional_obligation missing condition")
    return errs


def normalize(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    from services.schemas import check as _scheck
    ok, bad = [], []
    for r in candidates:
        errs = validate_rule(r)
        try:
            _scheck("rule_ir", r, f"normalize/{r.get('rule_id')}")
        except ValueError as e:
            errs = errs + [str(e)]
        (ok if not errs else bad).append(r if not errs else {"rule_id": r.get("rule_id"), "errors": errs})
    return ok, bad


def _key(r: dict) -> tuple:
    c = r.get("condition")
    return (r.get("kind"), r.get("action"),
            str(sorted((c or {}).items())) if isinstance(c, dict) else str(c))


def _threshold_cmp(old_v, old_op, new_v, new_op):
    """Decide relaxed vs tightened for monotone numeric gates."""
    try:
        o, n = float(old_v), float(new_v)
    except (TypeError, ValueError):
        return "CONDITION_CHANGED"
    if old_op in (">=", ">") and new_op in (">=", ">"):
        return "THRESHOLD_RELAXED" if n < o else ("THRESHOLD_TIGHTENED" if n > o else "CONDITION_CHANGED")
    if old_op in ("<=", "<") and new_op in ("<=", "<"):
        return "THRESHOLD_RELAXED" if n > o else ("THRESHOLD_TIGHTENED" if n < o else "CONDITION_CHANGED")
    return "CONDITION_CHANGED"


def semantic_rule_delta(old_rules: list[dict], new_rules: list[dict]) -> dict:
    old = {_key(r): r for r in old_rules}
    new = {_key(r): r for r in new_rules}
    added = [r for s, r in new.items() if s not in old]
    removed = [r for s, r in old.items() if s not in new]
    if not added and not removed:
        prov = any((old[s].get("provenance") or {}).get("section") !=
                   (new[s].get("provenance") or {}).get("section") for s in old)
        return {"type": "PROVENANCE_ONLY" if prov else "SEMANTICS_UNCHANGED",
                "behavioral": False, "added": [], "removed": [],
                "affected_rule_ids": [], "notes": []}
    changes, notes, affected = [], [], []
    old_by_fam = {(r.get("kind"), r.get("action")): r for r in old_rules}
    for r in added:
        fam = (r.get("kind"), r.get("action"))
        o = old_by_fam.get((r.get("kind"), r.get("action")))
        c = r.get("condition") or {}
        if r.get("kind") == "threshold" and o and o.get("kind") == "threshold":
            oc = o.get("condition") or {}
            t = _threshold_cmp(oc.get("value"), oc.get("operator"), c.get("value"), c.get("operator"))
            changes.append(t)
            notes.append(f"{t}: {c.get('field')} {oc.get('operator')} {oc.get('value')} -> {c.get('operator')} {c.get('value')}")
            affected.append(r.get("rule_id"))
        elif r.get("kind") == "threshold":
            # paired with a removed threshold of same field?
            ro = next((x for x in removed if x.get("kind") == "threshold"
                       and (x.get("condition") or {}).get("field") == c.get("field")), None)
            if ro:
                oc = ro.get("condition") or {}
                t = _threshold_cmp(oc.get("value"), oc.get("operator"), c.get("value"), c.get("operator"))
                changes.append(t)
                notes.append(f"{t}: {c.get('field')} {oc.get('operator')} {oc.get('value')} -> {c.get('operator')} {c.get('value')}")
            else:
                changes.append("THRESHOLD_ADDED")
                notes.append(f"new gate {r.get('normalized_expression')}")
            affected.append(r.get("rule_id"))
        elif r.get("kind") == "obligation":
            changes.append("OBLIGATION_ADDED"); affected.append(r.get("rule_id"))
            notes.append(f"new obligation {r.get('action')}")
        elif r.get("kind") == "conditional_obligation":
            ro = next((x for x in removed if x.get("action") == r.get("action")), None)
            changes.append("CONDITION_CHANGED" if ro else "OBLIGATION_ADDED")
            notes.append(f"{r.get('action')}: {ro.get('normalized_expression') if ro else 'absent'} -> {r.get('normalized_expression')}")
            affected.append(r.get("rule_id"))
        elif r.get("kind") == "exception":
            changes.append("EXCEPTION_ADDED"); affected.append(r.get("rule_id"))
            notes.append(f"exception {r.get('normalized_expression')}")
        elif r.get("kind") == "prerequisite":
            changes.append("PREREQUISITE_ADDED"); affected.append(r.get("rule_id"))
            notes.append(f"prerequisite {r.get('normalized_expression')}")
        elif r.get("kind") == "prohibition":
            changes.append("PROHIBITION_ADDED"); affected.append(r.get("rule_id"))
            notes.append(f"prohibition {r.get('normalized_expression')}")
        elif r.get("kind") == "deadline":
            ro = next((x for x in removed if x.get("kind") == "deadline"), None)
            if ro and (ro.get("condition") or {}).get("value") != c.get("value"):
                t = "DEADLINE_EXTENDED" if str(c.get("value")) > str((ro.get("condition") or {}).get("value")) else "DEADLINE_TIGHTENED"
                changes.append(t)
                notes.append(f"{t}: {(ro.get('condition') or {}).get('value')} -> {c.get('value')}")
            else:
                changes.append("DEADLINE_ADDED")
                notes.append(f"new deadline {r.get('normalized_expression')}")
            affected.append(r.get("rule_id"))
    for r in removed:
        if r.get("kind") == "obligation" and not any(x.get("action") == r.get("action") for x in added):
            changes.append("OBLIGATION_REMOVED"); affected.append(r.get("rule_id"))
            notes.append(f"removed obligation {r.get('action')}")
        elif r.get("kind") == "exception" and not any(x.get("kind") == "exception" for x in added):
            changes.append("EXCEPTION_REMOVED"); affected.append(r.get("rule_id"))
        elif r.get("kind") == "prerequisite" and not any(x.get("kind") == "prerequisite" for x in added):
            changes.append("PREREQUISITE_REMOVED"); affected.append(r.get("rule_id"))
    uniq = sorted(set(changes))
    dtype = uniq[0] if len(uniq) == 1 else ("COMPOUND" if uniq else "SEMANTICS_UNCHANGED")
    out = {"type": dtype, "behavioral": True, "added": added, "removed": removed,
           "affected_rule_ids": sorted(set(affected)), "notes": notes, "changes": uniq}
    if dtype in ("OBLIGATION_REMOVED",):
        out["action"] = removed[0].get("action") if removed else None
    if dtype == "EXCEPTION_ADDED" and added:
        out["action"] = added[0].get("action")
        out["exception_condition"] = added[0].get("condition")
    if dtype == "CONDITION_CHANGED" and added:
        out["action"] = added[0].get("action")
    return out
