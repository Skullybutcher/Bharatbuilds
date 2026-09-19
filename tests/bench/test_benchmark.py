import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_benchmark_all_green():
    from services.bench.runner import run_all
    results = run_all()
    assert len(results) == 26
    bad = [r["case_id"] for r in results
           if r["status"] not in ("AUTO_REPAIRED", "CORRECTLY_NO_OP", "CORRECTLY_ESCALATED")]
    assert not bad, bad
