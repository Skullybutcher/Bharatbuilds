"""Storage abstraction: JSON files locally, DynamoDB single-table on AWS.

Backend selected by PROCESSPATCH_STORAGE=files|dynamodb (default files).

DynamoDB design (explicit, float-safe):
  - Every payload is stored as a JSON STRING (data_json). Boto3 rejects
    Python floats ("Float types are not supported"), and our domain objects
    are full of them (thresholds, confidences, costs, timestamps). Strings
    dodge the entire Decimal problem and stay human-inspectable.
  - Collections keep list-or-dict semantics identical across backends:
      files:    data/<name>                      (JSON list or dict)
      dynamodb: PK=COLL#<name> SK=item id        (each list element one item;
                dict collections stored as a single META item)

Fail-closed: DynamoDB errors RAISE (with collection context) instead of
returning empty defaults. A governance check must never mistake "the database
failed" for "zero unresolved reviews".
"""
from __future__ import annotations
import json
import os
import time

DATA_DIR = os.environ.get("PROCESSPATCH_DATA",
                          os.path.join(os.path.dirname(__file__), "..", "data"))
TABLE = os.environ.get("REGISTRY_TABLE", "processpatch-registry")


def _backend() -> str:
    return os.environ.get("PROCESSPATCH_STORAGE", "files")


def _path(name: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, name)


# ---- files backend ----------------------------------------------------------
def _file_load(name: str, default):
    p = _path(name)
    if not os.path.exists(p):
        return default
    with open(p) as f:
        return json.load(f)


def _file_save(name: str, obj) -> None:
    with open(_path(name), "w") as f:
        json.dump(obj, f, indent=2, default=str)


# ---- dynamodb backend -------------------------------------------------------
def _dd():
    import boto3  # lazy: Lambda only
    return boto3.resource("dynamodb").Table(TABLE)


def _item_id(name: str, item: dict, n: int) -> str:
    return (item.get("review_id") or item.get("approval_id")
            or item.get("policy_version_id") or item.get("procedure_version_id")
            or item.get("executionArn") or item.get("build_id")
            or f"{time.time():.3f}-{n}")


def _dd_load(name: str, default):
    if _backend() != "dynamodb":
        return _file_load(name, default)
    try:
        if isinstance(default, dict):
            r = _dd().get_item(Key={"PK": f"COLL#{name}", "SK": "META"})
            raw = (r.get("Item") or {}).get("data_json")
            return json.loads(raw) if raw is not None else default
        r = _dd().query(KeyConditionExpression="PK = :pk",
                        ExpressionAttributeValues={":pk": f"COLL#{name}"})
        items = sorted(r.get("Items", []), key=lambda i: i.get("SK", ""))
        return [json.loads(i["data_json"]) for i in items]
    except Exception as e:  # noqa: BLE001 — re-raised, never swallowed
        raise RuntimeError(f"storage load failed for {name}: {type(e).__name__}: {e}") from e


def _dd_save(name: str, obj) -> None:
    if _backend() != "dynamodb":
        return _file_save(name, obj)
    try:
        t = _dd()
        if isinstance(obj, dict):
            t.put_item(Item={"PK": f"COLL#{name}", "SK": "META",
                             "data_json": json.dumps(obj, default=str),
                             "GSI_PK": "COLL", "GSI_SK": name})
            return
        old = t.query(KeyConditionExpression="PK = :pk",
                      ExpressionAttributeValues={":pk": f"COLL#{name}"}).get("Items", [])
        with t.batch_writer() as b:
            for i in old:
                b.delete_item(Key={"PK": i["PK"], "SK": i["SK"]})
        with t.batch_writer() as b:
            for n, item in enumerate(obj):
                b.put_item(Item={"PK": f"COLL#{name}", "SK": _item_id(name, item, n),
                                 "data_json": json.dumps(item, default=str),
                                 "GSI_PK": "COLL", "GSI_SK": name})
    except Exception as e:  # noqa: BLE001 — re-raised, never swallowed
        raise RuntimeError(f"storage save failed for {name}: {type(e).__name__}: {e}") from e


def _load(name: str, default):
    return _dd_load(name, default)


def _save(name: str, obj) -> None:
    _dd_save(name, obj)
