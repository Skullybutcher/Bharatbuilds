"""T68 — build identity is singular: build_id == compile_key, everywhere.

N2 live-verification found that every activated cloud build failed reverify on
`build_id` and `certificate_content_sha256`: the Step Functions machine mints
build_id PROVISIONALLY from policy+procedure (HASH_ARTIFACT, before any rules
exist) and never reconciled it with compile_key = sha(accepted_rules,
procedure) — the identity local run_build has always used. Persist wrote
build_id=X, compile_key=Y into the SAME record; certificate_content_sha256
followed because the certificate embeds build_id.

The ASL now canonicalizes at CANONICALIZE_BUILD_ID (immediately after the
idempotency lookup, where compile_key first exists and BEFORE any consumer).
These tests pin the contract from both sides: the machine document itself, and
the record shape that previously shipped to production.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
with open(os.path.join(ROOT, "infra", "statemachine.asl.json")) as _f:
    ASL = json.load(_f)

from services import storage  # noqa: E402
from services.api import actions  # noqa: E402


def test_asl_mints_build_id_provisionally_then_canonicalizes_to_compile_key():
    """The identity contract, read off the machine document.

    HASH_ARTIFACT mints a provisional id (rules don't exist yet), and the
    first state after the idempotency lookup MUST overwrite $.build_id from
    $.idempotency.compile_key — before RESOLVE_AUTHORITY and everything after.
    """
    assert ASL["States"]["HASH_ARTIFACT"]["Parameters"]["op"] == "hash"
    assert ASL["States"]["HASH_ARTIFACT"]["Next"] == "SET_BUILD_ID"

    canon = ASL["States"]["CANONICALIZE_BUILD_ID"]
    assert canon["Type"] == "Pass"
    assert canon["Parameters"]["build_id.$"] == "$.idempotency.compile_key"
    assert canon["ResultPath"] == "$.build_id"

    # placement: the canonicalization is the FIRST consumer of the lookup
    # result and runs before any state that uses $.build_id
    hit = ASL["States"]["IDEMPOTENT_HIT?"]
    assert hit["Choices"][0]["Next"] == "READY_CACHED"
    assert hit["Default"] == "CANONICALIZE_BUILD_ID"
    assert canon["Next"] == "RESOLVE_AUTHORITY"

    # nothing between the lookup and the canonicalization consumes $.build_id
    between = {hit["Choices"][0]["Next"], hit["Default"]}
    assert between == {"READY_CACHED", "CANONICALIZE_BUILD_ID"}


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    storage._FILE_VERSIONS.clear()
    actions.MEMO.clear()


def test_crossed_identity_record_fails_reverify_then_repairs_clean(tmp_path, monkeypatch):
    """Reproduces the live finding exactly: a build persisted by the OLD machine
    carries build_id=X, compile_key=Y (X != Y). Reverify must NAME both drifted
    fields (never fake a pass); recompiling the same inputs and persisting
    under the canonical id restores verified=True — evidence that the new
    machine's single identity is what reverify demands."""
    _isolate(tmp_path, monkeypatch)
    b = actions.canonical("research_grant")
    assert b["build_id"] == b["compile_key"], "local pipeline must stay canonical"

    from services.registry.store import save_build
    from services.certificate.certificate import sha as _csha
    crossed = dict(b)
    crossed["build_id"] = "BUILD-PROVISIONAL9999"  # what the old ASL persisted
    # ...and the certificate was ISSUED under that provisional id (build and
    # impact_summary_ref embed it; the self-hash covers both)
    cert = dict(b["certificate"])
    cert["build"] = crossed["build_id"]
    if cert.get("impact_summary_ref") == b["build_id"]:
        cert["impact_summary_ref"] = crossed["build_id"]
    cert["certificate_sha256"] = _csha({k: v for k, v in cert.items()
                                        if k != "certificate_sha256"})
    crossed["certificate"] = cert
    save_build(crossed)

    r = actions.reverify_build("BUILD-PROVISIONAL9999")
    assert r["verified"] is False
    assert set(r["mismatches"]) >= {"build_id", "certificate_content_sha256"}, r["mismatches"]

    # the new machine persists under compile_key; the crossed id disappears and
    # the canonical record re-verifies
    canonical = dict(b)
    save_build(canonical)
    r2 = actions.reverify_build(b["build_id"])
    assert r2["verified"] is True, r2.get("mismatches")
    for c in r2["checks"]:
        assert c["match"], f"check {c['check']} still mismatched"
