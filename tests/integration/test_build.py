import os
import pathlib
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="pp-test-")
os.environ["PROCESSPATCH_DATA"] = TMP
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _build():
    import json
    from services.api.pipeline import run_build
    d = ROOT / "demo" / "research_grant"
    old = json.loads((d / "rules_v1.json").read_text())
    new = json.loads((d / "rules_v2.json").read_text())
    proc = json.loads((d / "workflow_v1.json").read_text())
    return run_build("POLICY-V2", old, new, proc)


def test_end_to_end_build():
    b = _build()
    assert b["status"] == "PATCH_VALIDATED"
    assert b["certificate"]["status"] == "VALIDATED_WITHIN_TESTED_MODEL"
    assert len(b["witnesses"]) == 2
    assert b["impact"]["approval"]["human_status"] == "AWAITING_APPROVAL"


def test_idempotent_reuse():
    from services.registry.store import compile_key, save_build, find_build_by_key
    b = _build()
    save_build(b)
    assert find_build_by_key(b["compile_key"])["build_id"] == b["build_id"]
    assert compile_key(b["new_rules"], b["procedure"]) == b["compile_key"]
