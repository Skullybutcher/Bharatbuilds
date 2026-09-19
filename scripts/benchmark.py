"""Run ProcessPatchBench and emit versioned artifacts.

Usage: python scripts/benchmark.py [--split dev|eval] [--run-id ID]
Writes benchmark_runs/<run-id>/{manifest.json, results.json, metrics.json, report.md}
"""
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.bench.runner import run_all, metrics


def report_md(run_id: str, manifest: dict, results: list, m: dict) -> str:
    lines = [f"# ProcessPatchBench {manifest['benchmark_version']} — run {run_id}",
             f"{m['total']} total scenarios",
             ""]
    for status, n in sorted(m["by_status"].items()):
        lines.append(f"- {n} {status}")
    lines += ["", "## Metrics", ""]
    for k, v in m.items():
        if k not in ("total", "by_status"):
            lines.append(f"- {k}: {v}")
    lines += ["", "## Per-case results", ""]
    for r in results:
        extra = ""
        if r["status"] not in ("AUTO_REPAIRED", "CORRECTLY_NO_OP", "CORRECTLY_ESCALATED"):
            extra = f" — {r.get('error', '')} {r.get('witness', '')} {r.get('localization', '')} {r.get('repair', '')}"[:400]
        lines.append(f"- {r['case_id']} [{r.get('family')}/{r.get('split')}] {r['status']}{extra}")
    lines += ["", "Honest summary: failures above are real gaps, not hidden. See 57C.11.",
              "",
              "Methodology: extraction is scored against POLICY TEXT; downstream",
              "compiler/repair stages run on hand-authored GOLD RULE IR so extraction",
              "errors do not contaminate repair metrics. Do not cite these numbers as",
              "'raw-NL end-to-end repair'. Eval split is held-out authored, not",
              "independent real-world data."]
    return "\n".join(lines)


def main() -> int:
    args = sys.argv[1:]
    split = None
    if "--split" in args:
        split = args[args.index("--split") + 1]
    run_id = f"BENCH-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    if "--run-id" in args:
        run_id = args[args.index("--run-id") + 1]
    manifest = json.loads((ROOT / "benchmark" / "processpatchbench" / "manifest.json").read_text())
    results = run_all(split)
    m = metrics(results)
    out = ROOT / "benchmark_runs" / run_id
    (out / "failures").mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(
        {**manifest, "run_id": run_id, "split": split or "all",
         "compiler_version": "0.1.0", "extractor_version": "processpatch-extractor/0.1.0",
         "seed": "deterministic (no randomization)"}, indent=2))
    (out / "results.json").write_text(json.dumps({"run_id": run_id, "cases": results}, indent=2, default=str))
    (out / "metrics.json").write_text(json.dumps(m, indent=2))
    (out / "report.md").write_text(report_md(run_id, manifest, results, m))
    for r in results:
        if r["status"].startswith("FAILED"):
            (out / "failures" / f"{r['case_id']}.json").write_text(json.dumps(r, indent=2, default=str))
    print(f"ProcessPatchBench {manifest['benchmark_version']} run {run_id}: "
          f"{m['total']} scenarios, by_status={m['by_status']}")
    print(f"artifacts: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
