"""Generic boolean/numeric/date/enum expression evaluation (deterministic, stdlib only).

Condition forms:
  {"field","operator","value"}            comparison; ISO dates compare lexicographically
  {"and":[...]}, {"or":[...]}, {"not":...}
  prerequisite conditions {"prerequisite","target","relation"} are NOT case
  predicates (eval True) — they constrain workflow ordering instead.
"""
from __future__ import annotations
from datetime import date, timedelta

OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "IN": lambda a, b: a in b,
    "NOT_IN": lambda a, b: a not in b,
}


def _coerce(value):
    if isinstance(value, str):
        v = value.replace(",", "").strip()
        try:
            return float(v) if "." in v else int(v)
        except ValueError:
            return value
    return value


def eval_condition(cond: dict | None, case: dict) -> bool:
    if cond is None:
        return True
    if "and" in cond:
        return all(eval_condition(c, case) for c in cond["and"])
    if "or" in cond:
        return any(eval_condition(c, case) for c in cond["or"])
    if "not" in cond:
        return not eval_condition(cond["not"], case)
    field, op = cond.get("field"), cond.get("operator")
    if field is None or op is None:
        return True  # prerequisite-style / structural condition
    if field not in case or case[field] is None:
        return False
    actual, want = _coerce(case[field]), _coerce(cond.get("value"))
    fn = OPS.get(op)
    if fn is None:
        raise ValueError(f"Unsupported operator {op!r}")
    if op in ("IN", "NOT_IN") and not isinstance(want, (list, tuple, set)):
        want = [want]
    try:
        return bool(fn(actual, want))
    except TypeError:
        return str(actual) == str(want) if op == "==" else False


def iter_comparisons(cond: dict | None):
    """Yield all leaf {"field","operator","value"} comparisons in a condition tree."""
    if not cond:
        return
    if "and" in cond or "or" in cond:
        for c in cond.get("and", cond.get("or", [])):
            yield from iter_comparisons(c)
        return
    if "not" in cond:
        yield from iter_comparisons(cond["not"])
        return
    if cond.get("field") and cond.get("operator"):
        yield cond


def is_date_literal(value) -> bool:
    import re
    return isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value) is not None


def shift_date(value: str, days: int) -> str:
    d = date.fromisoformat(value[:10])
    out = (d + timedelta(days=days)).isoformat()
    return out + value[10:] if len(value) > 10 else out


def neighbors(field: str, literals: set, eps: float = 0.01):
    """Deterministic boundary candidates around literals for one field.
    List literals (IN/NOT_IN membership) contribute each member as a
    candidate so enum-boundary witnesses are reachable."""
    cands: set = set()
    expanded: set = set()
    for l in literals:
        if isinstance(l, (list, tuple, set)):
            cands.update(l)
        else:
            expanded.add(l)
    literals = expanded
    dates = [l for l in literals if is_date_literal(l)]
    nums = [float(l) for l in literals if isinstance(l, (int, float)) or (isinstance(l, str) and not is_date_literal(l) and str(l).replace(",", "").replace(".", "").strip("-").isdigit())]
    texts = [l for l in literals if isinstance(l, str) and not is_date_literal(l) and l not in {str(n) for n in nums}]
    for n in nums:
        for d in (-eps if abs(n) < 1000 else -1, 0, eps if abs(n) < 1000 else 1):
            v = n + d
            cands.add(int(v) if float(v).is_integer() and isinstance(n, int) or (float(v).is_integer() and abs(v) < 10**9 and n == int(n)) else round(v, 2))
    for dl in dates:
        cands.add(shift_date(dl, -1))
        cands.add(dl)
        cands.add(shift_date(dl, 1))
    cands.update(texts)
    return cands
