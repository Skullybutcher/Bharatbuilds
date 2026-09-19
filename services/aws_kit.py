"""AWS kit: DynamoDB persistence layer with the same interface as the local
file-backed registry (services.registry.store). boto3 is imported lazily so
local runs and unit tests never require AWS credentials.

Table design (single table, on-demand):
  PK                    SK                        item
  WS#<id>               META                      workspace
  POLICY#<ver>          META                      policy version (+ rules, sha)
  PROC#<workflow>       VER#<version>             procedure version (+ graph, sha, status)
  BUILD#<id>            META                      build (full artifact, compile_key)
  BUILD#<id>            REVIEW#<rule>             rule review
  BUILD#<id>            APPROVAL#<n>              approval record
  AUDIT                 <ts>#<event>              audit event
GSI1: GSI_PK=BUILDKEY / GSI_SK=compile_key  (idempotency lookup)
"""
from __future__ import annotations
import os
import time

TABLE = os.environ.get("REGISTRY_TABLE", "processpatch-registry")


def _table():
    import boto3  # lazy: only on Lambda / configured hosts
    return boto3.resource("dynamodb").Table(TABLE)


def put_build(build: dict) -> None:
    _table().put_item(Item={"PK": f"BUILD#{build['build_id']}", "SK": "META",
                            "GSI_PK": "BUILDKEY", "GSI_SK": build.get("compile_key", ""),
                            "data": build})


def get_build(build_id: str) -> dict | None:
    r = _table().get_item(Key={"PK": f"BUILD#{build_id}", "SK": "META"})
    return (r.get("Item") or {}).get("data")


def find_build_by_key(key: str) -> dict | None:
    import boto3
    r = _table().query(IndexName="GSI1",
                       KeyConditionExpression=boto3.dynamodb.conditions.Key("GSI_PK").eq("BUILDKEY")
                       & boto3.dynamodb.conditions.Key("GSI_SK").eq(key))
    items = r.get("Items", [])
    return items[0].get("data") if items else None


def put_audit(event: str, payload: dict) -> None:
    _table().put_item(Item={"PK": "AUDIT", "SK": f"{time.time():.3f}#{event}",
                            "event": event, **payload})


def emit_metric(name: str, value: float = 1, unit: str = "Count", **dims) -> None:
    """CloudWatch Embedded Metric Format via stdout (no boto3 needed)."""
    import json as _json
    print(_json.dumps({"_aws": {"Timestamp": int(time.time() * 1000),
                                "CloudWatchMetrics": [{"Namespace": "ProcessPatch",
                                                       "Dimensions": [list(dims)],
                                                       "Metrics": [{"Name": name, "Unit": unit}]}]},
                       **{name: value, **dims}}))
