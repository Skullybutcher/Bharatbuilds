"""T67 — the public verifier CLI is a real verifier.

The promise: anyone holding a downloaded governance bundle can check its seal
offline with zero dependencies. These tests keep that promise honest by
round-tripping a REAL bundle (produced by actions.governance_bundle through the
actual approval path) through the CLI: pass on untouched bytes, FAIL on any
tampering — a flipped approval decision, a moved byte in the certificate — plus
the refusal modes (not JSON, not a bundle, unsealed).
"""
import json
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services import storage  # noqa: E402
from services.api import actions  # noqa: E402
from services.governance import store as gov  # noqa: E402


@pytest.fixture()
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSPATCH_STORAGE", "files")
    storage._FILE_VERSIONS.clear()
    actions.MEMO.clear()


@pytest.fixture()
def approved_bundle(files, tmp_path):
    """A real bundle from the real path: canonical build -> gate 2 approval."""
    b = actions.canonical("research_grant")
    bid = b["build_id"]
    gov.request_patch_review(bid, None)
    gov.save_callback(bid, "patch_approval", "tok-t67")
    out = gov.resume_callback(bid, "patch_approval",
                              {"gate": "patch_approval", "decision": "APPROVE_CANDIDATE",
                               "role": "PROCEDURE_OWNER",
                               "reviewer": {"reviewer_id": "rev", "display_name": "rev"},
                               "reason": "t67"})
    assert out.get("decision") == "APPROVE_CANDIDATE"
    bundle = actions.governance_bundle(bid)
    p = tmp_path / "bundle.json"
    p.write_text(json.dumps(bundle), encoding="utf-8")
    return str(p)


def _run(path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "verify_bundle", os.path.join(os.path.dirname(__file__), "..", "..",
                                      "scripts", "verify_bundle.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.verify(path)


def test_real_bundle_passes(approved_bundle):
    ok, notes = _run(approved_bundle)
    assert ok, notes
    assert any("seal:       OK" in n for n in notes)
    assert any("cert:       OK" in n for n in notes)


def test_tampered_bundle_is_named(approved_bundle):
    with open(approved_bundle, encoding="utf-8") as f:
        doc = json.load(f)
    doc["approvals"][0]["decision"] = "REJECT"  # flip a human decision
    with open(approved_bundle, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    ok, notes = _run(approved_bundle)
    assert not ok
    assert any("seal mismatch" in n for n in notes)


def test_tampered_certificate_is_named(approved_bundle):
    with open(approved_bundle, encoding="utf-8") as f:
        doc = json.load(f)
    doc["certificate"]["status"] = "FULLY_CERTIFIED"  # upgrade the disclaimer
    with open(approved_bundle, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    ok, notes = _run(approved_bundle)
    assert not ok
    assert any("certificate self-hash mismatch" in n for n in notes)


def test_non_json_and_wrong_kind_fail(tmp_path):
    junk = tmp_path / "junk.json"
    junk.write_text("not json at all", encoding="utf-8")
    ok, notes = _run(str(junk))
    assert not ok and any("not valid JSON" in n for n in notes)

    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"kind": "something-else"}), encoding="utf-8")
    ok, notes = _run(str(wrong))
    assert not ok and any("not a governance bundle" in n for n in notes)


def test_unsealed_bundle_fails(approved_bundle):
    with open(approved_bundle, encoding="utf-8") as f:
        doc = json.load(f)
    del doc["bundle_sha256"]
    with open(approved_bundle, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    ok, notes = _run(approved_bundle)
    assert not ok and any("no bundle_sha256" in n for n in notes)


def test_cli_exit_codes(approved_bundle, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "verify_bundle", os.path.join(os.path.dirname(__file__), "..", "..",
                                      "scripts", "verify_bundle.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert mod.main(["verify_bundle.py", approved_bundle]) == 0
    assert mod.main(["verify_bundle.py", str(bad)]) == 1
    assert mod.main(["verify_bundle.py"]) == 2
