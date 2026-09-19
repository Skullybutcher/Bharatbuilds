"""Schema contracts enforced at external boundaries (not documentation).

Validates Rule IR (normalize), Workflow (execute/propose), Patch (propose),
Witness (generator output spot-checks), Approval (decide), ImpactSummary
(compute). Requires the `jsonschema` dev dependency.
"""
from __future__ import annotations
import json
import pathlib

SCHEMAS = pathlib.Path(__file__).resolve().parents[1] / "shared" / "schemas"
_cache: dict = {}


def _schema(name: str) -> dict:
    if name not in _cache:
        _cache[name] = json.loads((SCHEMAS / f"{name}.json").read_text())
    return _cache[name]


def check(name: str, obj: dict, where: str) -> None:
    import jsonschema
    try:
        jsonschema.validate(obj, _schema(name))
    except jsonschema.ValidationError as e:
        raise ValueError(f"SCHEMA_VIOLATION at {where} ({name}): {e.message[:200]}") from e


def check_each(name: str, objs: list, where: str) -> None:
    for o in objs:
        check(name, o, where)
