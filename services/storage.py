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
import tempfile

DATA_DIR = os.environ.get("PROCESSPATCH_DATA",
                          os.path.join(os.path.dirname(__file__), "..", "data"))
TABLE = os.environ.get("REGISTRY_TABLE", "processpatch-registry")

# The legacy whole-collection blob (dict collections used to live in one META
# item). Reads merge it for backward compatibility; per-record writes retire it.
META_SK = "META"


class ConcurrencyError(RuntimeError):
    """An optimistic per-record write lost a race.

    Raised instead of silently overwriting a concurrent writer — two reviewers
    acting on the same build must not both 'win', and a gate decision must not
    be consumed twice."""


def _is_conditional_failure(e) -> bool:
    """True for DynamoDB's ConditionalCheckFailedException (checked by code, not
    by type: botocore may not be importable in every runtime that touches this)."""
    return getattr(e, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException"


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
    path = _path(name)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# ---- dynamodb backend -------------------------------------------------------
def _dd():
    import boto3  # lazy: Lambda only
    return boto3.resource("dynamodb").Table(TABLE)


def _item_id(name: str, item: dict, n: int) -> str:
    # Dedicated natural ids win first (reviews/approvals/versions/executions).
    # THEN gate callbacks: identified by (build_id, gate) — one WAITING slot
    # per gate per build. Keying on build_id alone collides the moment a build
    # arms a second gate: two items share an SK, BatchWriteItem rejects the
    # batch ("Provided list of item keys contains duplicates"), and every
    # future save of the collection wedges. Live failure: Gate-3 arming, T50.
    dedicated = (item.get("record_id") or item.get("review_id") or item.get("approval_id")
                 or item.get("policy_version_id") or item.get("procedure_version_id")
                 or item.get("executionArn"))
    if dedicated:
        return dedicated
    if item.get("gate") and item.get("build_id"):
        return f"{item['build_id']}#{item['gate']}"
    return (item.get("build_id")
            or f"{time.time():.3f}-{n}")


def _sks(name: str, obj) -> "list[tuple[str, dict]]":
    """Assign each list item its deterministic SK, collapsing duplicate keys
    last-wins (append semantics — the same rule save_callback uses in-list).
    BatchWriteItem rejects duplicate keys outright, so a legacy duplicate pair
    already in a collection must self-heal here rather than poison every
    subsequent save of that collection."""
    seen: dict = {}
    for n, item in enumerate(obj):
        seen[_item_id(name, item, n)] = item
    return list(seen.items())


def _dd_items(table, name: str) -> list:
    """Read the complete collection, including pages beyond DynamoDB's limit."""
    request = {"KeyConditionExpression": "PK = :pk",
               "ExpressionAttributeValues": {":pk": f"COLL#{name}"},
               "ConsistentRead": True}
    items = []
    while True:
        page = table.query(**request)
        items.extend(page.get("Items", []))
        if not page.get("LastEvaluatedKey"):
            return items
        request["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _dd_load(name: str, default):
    if _backend() != "dynamodb":
        return _file_load(name, default)
    try:
        t = _dd()
        if isinstance(default, dict):
            # Dict collections are stored per record (SK = record key). The
            # legacy META blob is merged first so a stack written by the old
            # single-item design keeps reading correctly; per-record rows win.
            merged = {}
            raw = (t.get_item(Key={"PK": f"COLL#{name}", "SK": META_SK},
                              ConsistentRead=True).get("Item") or {}).get("data_json")
            if raw is not None:
                merged.update(json.loads(raw))
            for i in sorted(_dd_items(t, name), key=lambda i: i.get("SK", "")):
                if i.get("SK") == META_SK:
                    continue
                merged[i["SK"]] = json.loads(i["data_json"])
            return merged or default
        items = sorted(_dd_items(t, name), key=lambda i: i.get("SK", ""))
        return [json.loads(i["data_json"]) for i in items]
    except Exception as e:  # noqa: BLE001 — re-raised, never swallowed
        raise RuntimeError(f"storage load failed for {name}: {type(e).__name__}: {e}") from e


def _dd_save(name: str, obj) -> None:
    if _backend() != "dynamodb":
        return _file_save(name, obj)
    try:
        t = _dd()
        if isinstance(obj, dict):
            # Bulk dict save = seed/migration path. It writes per record and
            # retires the legacy META blob, so a collection can never grow into
            # one 400 KB item again. Concurrency-safe single-record writes go
            # through put_item(expect=...) instead.
            old = {i["SK"] for i in _dd_items(t, name) if i.get("SK") != META_SK}
            with t.batch_writer() as b:
                for sk in old - set(obj):
                    b.delete_item(Key={"PK": f"COLL#{name}", "SK": sk})
                for key, val in obj.items():
                    b.put_item(Item={"PK": f"COLL#{name}", "SK": key,
                                     "data_json": json.dumps(val, default=str),
                                     "GSI_PK": "COLL", "GSI_SK": name})
                b.delete_item(Key={"PK": f"COLL#{name}", "SK": META_SK})
            return
        # Diff-based bulk save: put only new/changed records, delete only records
        # that disappeared. The old delete-all-then-put-all erased any record a
        # concurrent per-record writer added between our read and our write — a
        # bulk save could destroy another worker's fresh approval or procedure
        # version. Untouched records keep their version bookkeeping.
        old = {i["SK"]: i for i in _dd_items(t, name)}
        new = _sks(name, obj)
        new_keys = {sk for sk, _ in new}
        gone = [sk for sk in old if sk != META_SK and sk not in new_keys]
        changed = [(sk, item) for sk, item in new
                   if sk not in old or old[sk].get("data_json") != json.dumps(item, default=str)]
        with t.batch_writer() as b:
            for sk in gone:
                b.delete_item(Key={"PK": f"COLL#{name}", "SK": sk})
            for sk, item in changed:
                b.put_item(Item={"PK": f"COLL#{name}", "SK": sk,
                                 "data_json": json.dumps(item, default=str),
                                 "GSI_PK": "COLL", "GSI_SK": name})
    except Exception as e:  # noqa: BLE001 — re-raised, never swallowed
        raise RuntimeError(f"storage save failed for {name}: {type(e).__name__}: {e}") from e


def _load(name: str, default):
    return _dd_load(name, default)


def _save(name: str, obj) -> None:
    _dd_save(name, obj)


# ---- per-record primitives (the concurrency-safe path) -----------------------
# Bulk _save rewrites a whole collection. Under concurrent Lambda workers that
# is read-modify-write: writer A's batch delete can drop writer B's insert, and
# two writers that both read then write silently clobber each other. Anything
# with a race (gate decisions, approvals, callbacks) must use these instead:
# one record per write item, with the version the caller read passed back in.
_FILE_VERSIONS: dict = {}   # files backend: single process, so versions live here

# Collections whose records are addressed by key rather than listed. Everything
# else is a list collection. This decides the shape a MISSING files-backend
# collection is created with — getting it wrong writes a dict where readers
# expect a list, and list reads then iterate dict KEYS (strings).
DICT_COLLECTIONS = {"builds.json"}


def _shape(name: str) -> str:
    return "dict" if name in DICT_COLLECTIONS else "list"


def _record_ids(rec: dict) -> set:
    """Every id a record can be addressed by (mirrors _item_id)."""
    ids = {rec.get(k) for k in ("record_id", "build_id", "review_id", "approval_id",
                                "policy_version_id", "procedure_version_id", "executionArn")}
    if rec.get("build_id") and rec.get("gate"):
        ids.add(f"{rec['build_id']}#{rec['gate']}")
    return {i for i in ids if i}


def _file_get_item(name: str, item_id: str):
    """(payload, version). Version conventions: 0 = absent, >=1 = written
    through put_item (optimistic checks apply), -1 = exists but was written by
    a legacy bulk save, so it carries no version to check against."""
    data = _file_load(name, {})
    if isinstance(data, dict):
        item = data.get(item_id)
        if item is None:
            return None, 0
        v = _FILE_VERSIONS.get((name, item_id))
        return item, (v if v is not None else -1)
    for rec in data:
        if item_id in _record_ids(rec):
            v = _FILE_VERSIONS.get((name, item_id))
            return rec, (v if v is not None else -1)
    return None, 0


def _dd_get_item(name: str, item_id: str):
    row = _dd().get_item(Key={"PK": f"COLL#{name}", "SK": item_id},
                         ConsistentRead=True).get("Item") or {}
    if not row.get("data_json"):
        return None, 0
    return json.loads(row["data_json"]), int(row.get("ver", -1))


def _dd_put_item(name: str, item_id: str, item: dict, expect: int | None) -> int:
    t = _dd()
    row = t.get_item(Key={"PK": f"COLL#{name}", "SK": item_id},
                     ConsistentRead=True).get("Item") or {}
    if not row.get("data_json"):
        cur = 0
    else:
        cur = int(row.get("ver", -1))  # -1: legacy row written without a version
    if expect is not None and cur != expect:
        raise ConcurrencyError(f"{name}/{item_id}: expected version {expect}, found {cur}")
    new_ver = (cur if cur > 0 else 0) + 1
    kwargs = {"Item": {"PK": f"COLL#{name}", "SK": item_id,
                       "data_json": json.dumps(item, default=str),
                       "ver": new_ver, "GSI_PK": "COLL", "GSI_SK": name}}
    if expect == 0:
        # create-only: the database enforces that nothing was there
        kwargs["ConditionExpression"] = "attribute_not_exists(SK)"
    elif expect is not None and expect > 0:
        # exact-version match — a writer that read a stale version cannot win
        kwargs["ConditionExpression"] = "ver = :e"
        kwargs["ExpressionAttributeValues"] = {":e": expect}
    # expect -1 (legacy row) or None: unconditional overwrite, as before
    try:
        t.put_item(**kwargs)
    except Exception as e:  # noqa: BLE001
        if _is_conditional_failure(e):
            raise ConcurrencyError(
                f"{name}/{item_id}: lost a write race (expected version {expect})") from e
        raise RuntimeError(f"storage put failed for {name}/{item_id}: {type(e).__name__}: {e}") from e
    return new_ver


def get_item(name: str, item_id: str) -> "tuple[dict | None, int]":
    """Read one record: (payload, version). Version 0 means absent."""
    if _backend() != "dynamodb":
        return _file_get_item(name, item_id)
    try:
        return _dd_get_item(name, item_id)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"storage get failed for {name}/{item_id}: {type(e).__name__}: {e}") from e


def put_item(name: str, item_id: str, item: dict, expect: int | None = None) -> int:
    """Write ONE record and return its new version.

    `expect` = the version you read (0 = must not exist yet). Pass it whenever a
    lost update would be a correctness bug; the write then fails with
    ConcurrencyError instead of overwriting the other writer.
    """
    if _backend() != "dynamodb":
        cur, ver = _file_get_item(name, item_id)
        if expect is not None and ver != expect:
            raise ConcurrencyError(f"{name}/{item_id}: expected version {expect}, found {ver}")
        new_ver = (ver if ver > 0 else 0) + 1
        data = _file_load(name, None)
        if data is None:
            data = {} if _shape(name) == "dict" else []
        if isinstance(data, dict):
            data = dict(data)
            data[item_id] = item
        else:
            rows, idx = list(data), None
            for i, rec in enumerate(rows):
                if item_id in _record_ids(rec):
                    idx = i
                    break
            if idx is None:
                rows.append(item)
            else:
                rows[idx] = item
            data = rows
        _file_save(name, data)
        _FILE_VERSIONS[(name, item_id)] = new_ver
        return new_ver
    try:
        return _dd_put_item(name, item_id, item, expect)
    except ConcurrencyError:
        raise
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"storage put failed for {name}/{item_id}: {type(e).__name__}: {e}") from e


def delete_item(name: str, item_id: str) -> bool:
    """Delete one record. Returns True if something was there."""
    if _backend() != "dynamodb":
        rec, _ = _file_get_item(name, item_id)
        if rec is None:
            return False
        data = _file_load(name, None)
        if isinstance(data, dict):
            data.pop(item_id, None)
        else:
            data = [r for r in data if item_id not in _record_ids(r)]
        _file_save(name, data)
        _FILE_VERSIONS.pop((name, item_id), None)
        return True
    try:
        t = _dd()
        existed = bool((t.get_item(Key={"PK": f"COLL#{name}", "SK": item_id},
                                  ConsistentRead=True).get("Item") or {}).get("data_json"))
        t.delete_item(Key={"PK": f"COLL#{name}", "SK": item_id})
        return existed
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"storage delete failed for {name}/{item_id}: {type(e).__name__}: {e}") from e
