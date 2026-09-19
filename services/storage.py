"""Storage abstraction: JSON files locally, DynamoDB single-table on AWS.

Backend selected by PROCESSPATCH_STORAGE=files|dynamodb (default files).
Collections keep list-or-dict semantics identical across backends:

  files:    data/<name>                      (JSON list or dict)
  dynamodb: PK=COLL#<name> SK=item id        (each list element one item;
            dict collections stored as a single META item)
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


def _dd_load(name: str, default):
    if _backend() != "dynamodb":
        return _file_load(name, default)
    try:
        if isinstance(default, dict):
            r = _dd().get_item(Key={"PK": f"COLL#{name}", "SK": "META"})
            return (r.get("Item") or {}).get("data", default)
        r = _dd().query(KeyConditionExpression="PK = :pk",
                        ExpressionAttributeValues={":pk": f"COLL#{name}"})
        items = sorted(r.get("Items", []), key=lambda i: i.get("SK", ""))
        if not items and "Count" not in r:
            return default
        return [i["data"] for i in items]
    except Exception:
        return default


def _dd_save(name: str, obj) -> None:
    if _backend() != "dynamodb":
        return _file_save(name, obj)
    import time as _t
    t = _dd()
    if isinstance(obj, dict):
        t.put_item(Item={"PK": f"COLL#{name}", "SK": "META", "data": obj,
                         "GSI_PK": "COLL", "GSI_SK": name})
        return
    old = t.query(KeyConditionExpression="PK = :pk",
                  ExpressionAttributeValues={":pk": f"COLL#{name}"}).get("Items", [])
    with t.batch_writer() as b:
        for i in old:
            b.delete_item(Key={"PK": i["PK"], "SK": i["SK"]})
        for n, item in enumerate(obj):
            rid = item.get("review_id") or item.get("approval_id") or \
                item.get("policy_version_id") or item.get("procedure_version_id") or \
                item.get("build_id") or f"{_t.time():.3f}-{n}"
            b.put_item(Item={"PK": f"COLL#{name}", "SK": f"{rid}",
                             "data": item, "GSI_PK": "COLL", "GSI_SK": name})


def _load(name: str, default):
    return _dd_load(name, default)


def _save(name: str, obj) -> None:
    _dd_save(name, obj)
