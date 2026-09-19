"""Terminal demo: person-first script (wrong outcome -> witness -> impact -> patch -> green)."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.compiler.compiler import compile_rules, evaluate_expected
from services.workflow.interpreter import execute
from services.api.pipeline import run_build
from services.certificate.certificate import render_text

d = ROOT / "demo" / "research_grant"
old = json.loads((d / "rules_v1.json").read_text())
new = json.loads((d / "rules_v2.json").read_text())
proc = json.loads((d / "workflow_v1.json").read_text())
model = compile_rules(new)
for cgpa in (7.8, 8.2):
    case = {"cgpa": cgpa, "year": 3, "backlogs": 0, "category": "general",
            "submission_date": "2026-09-28"}
    exp, act = evaluate_expected(model, case), execute(proc, case, model.ordering)
    print(f"CGPA {cgpa}: expected eligible={exp['eligible']} rec={exp['required']} | "
          f"portal eligible={act['eligible']} rec={act['required']}")
print()
b = run_build("POLICY-V2", old, new, proc)
print(f"BUILD {b['build_id']} {b['status']} witnesses={len(b['witnesses'])} "
      f"validation={b['validation']['passed']}/{b['validation']['total']}")
print(f"impact: {b['impact']['behavioral']} cohort_n={b['impact']['test_cohort']['cohort_size']}")
if b["certificate"]:
    print(render_text(b["certificate"]))
