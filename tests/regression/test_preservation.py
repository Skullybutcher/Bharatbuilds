import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_preservation_no_regressions():
    import json
    from services.api.pipeline import run_build
    d = ROOT / "demo" / "research_grant"
    old = json.loads((d / "rules_v1.json").read_text())
    new = json.loads((d / "rules_v2.json").read_text())
    proc = json.loads((d / "workflow_v1.json").read_text())
    b = run_build("POLICY-V2", old, new, proc)
    unchanged = [r for r in b["validation"]["results"] if r["suite"] == "unchanged"]
    assert unchanged and all(r["pass"] for r in unchanged)
