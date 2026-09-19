"""Governance bundle export — sha256-sealed evidence pack (T15).

Covers: unapproved builds are refused (409 path); approved builds produce a
complete bundle whose seal verifies over the exact canonical bytes; the
export itself lands in the audit trail.
"""
import hashlib
import json
import os
import pathlib
import sys
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="pp-test-bundle-")
os.environ["PROCESSPATCH_DATA"] = TMP
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _approved_bid() -> str:
    import services.api.actions as A
    b = A.canonical("research_grant")
    bid = b["build_id"]
    A.patch_review_request(bid, {})
    A.approve(bid, {"reviewer": {"reviewer_id": "USR-001"},
                    "reason": "checks pass", "role": "PROCEDURE_OWNER"})
    return bid


def test_bundle_refused_without_approval():
    import json
    import services.api.actions as A
    from services.api.pipeline import run_build
    # Unique new-rules content => unique build_id, immune to other tests
    # having approved the canonical build in the shared temp store.
    d = ROOT / "demo" / "research_grant"
    old = json.loads((d / "rules_v1.json").read_text())
    new = json.loads((d / "rules_v2.json").read_text())
    proc = json.loads((d / "workflow_v1.json").read_text())
    import random
    for r in new:
        v = (r.get("condition") or {}).get("value")
        if isinstance(v, (int, float)):
            r["condition"]["value"] = v + 17 + random.randint(1, 100_000)  # unique vs every other test's build
            break
    b = run_build("POLICY-UNAPPROVED", old, new, proc)
    assert b.get("status") not in ("NEEDS_REVIEW",), "fixture must compile clean"
    b = A._store(b)  # run_build returns the build; _need() reads it from storage
    with pytest.raises(ValueError, match="no human approval on record"):
        A.governance_bundle(b["build_id"])


def test_bundle_content_and_seal():
    bid = _approved_bid()
    import services.api.actions as A
    bundle = A.governance_bundle(bid)
    assert bundle["kind"] == "processpatch-governance-bundle"
    assert bundle["build"]["build_id"] == bid
    assert bundle["approvals"], "approved build must carry approval records"
    assert bundle["witnesses"], "demo build has verified witnesses"
    assert bundle["rule_reviews"], "Gate-1 decisions included"
    assert bundle["guardrails"], "merge-protection evaluation included"
    assert bundle["certificate"], "patch certificate included"
    # The export event can never appear inside its own bundle (the seal covers
    # the audit snapshot as of pre-export) — but it IS in the trail, and the
    # NEXT export's bundle carries this one's event.
    sha = bundle.pop("bundle_sha256")
    blob = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(blob).hexdigest() == sha
    from services.registry.store import audit_for
    assert any(e.get("event") == "BUNDLE_EXPORTED" for e in audit_for(bid))
    second = A.governance_bundle(bid)
    assert any(e.get("event") == "BUNDLE_EXPORTED" for e in second["audit"])


def test_bundle_refuses_unknown_build():
    import services.api.actions as A
    with pytest.raises(KeyError):
        A.governance_bundle("BUILD-NOPE")
