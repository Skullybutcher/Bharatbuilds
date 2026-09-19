import os
import pathlib
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="pp-test-impact-")
os.environ["PROCESSPATCH_DATA"] = TMP
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_impact_contract_and_counts():
    import json
    from services.api.pipeline import run_build
    d = ROOT / "demo" / "research_grant"
    old = json.loads((d / "rules_v1.json").read_text())
    new = json.loads((d / "rules_v2.json").read_text())
    proc = json.loads((d / "workflow_v1.json").read_text())
    b = run_build("POLICY-V2", old, new, proc)
    im = b["impact"]
    assert set(("build_id", "artifacts", "behavioral", "test_cohort", "verification", "approval")) <= set(im)
    assert im["behavioral"]["wrong_rejections"] >= 1
    assert im["test_cohort"]["cohort_size"] >= 20
    assert "synthetic" in im["test_cohort"]["label"].lower()
    assert im["verification"]["provenance_coverage"] == 1.0
