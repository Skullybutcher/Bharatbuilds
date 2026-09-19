"""Witness coverage of the blast radius (T18) — read-only honesty metric.

Covers: nodes are covered only when a verified witness's localized fault
cites them (join via localizer faults, not witness dicts); field coverage
requires a witness case to cite the field; unknown builds 404.
"""
import os
import pathlib
import sys
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="pp-test-cov-")
os.environ["PROCESSPATCH_DATA"] = TMP
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_demo_build_full_coverage_with_attribution():
    import services.api.actions as A
    b = A.canonical("research_grant")
    c = A.coverage(b["build_id"])
    assert c["witness_count"] >= 1
    assert c["nodes"]["total"] >= 1
    # Every affected node is cited by at least one witness's fault.
    for row in c["nodes"]["rows"]:
        if row["covered"]:
            assert row["witnesses"], "covered rows must name their witnesses"
    assert c["nodes"]["pct"] == 1.0, "demo build: witnesses cover the full blast radius"
    # Affected rule fields come from the impact artifact; cgpa is the demo change.
    assert any(r["field"] == "cgpa" and r["covered"] for r in c["fields"]["rows"])


def test_coverage_shape_is_honest():
    import services.api.actions as A
    b = A.canonical("research_grant")
    c = A.coverage(b["build_id"])
    assert set(c["nodes"]) >= {"total", "covered", "pct", "rows"}
    assert set(c["fields"]) >= {"total", "covered", "pct", "rows"}
    assert "nothing else counts" in c["note"] or "covered =" in c["note"]
    # pct math agrees with the rows
    for dim in ("nodes", "fields"):
        if c[dim]["total"]:
            assert c[dim]["covered"] == sum(1 for r in c[dim]["rows"] if r["covered"])


def test_unknown_build_is_404():
    import services.api.actions as A
    with pytest.raises(KeyError):
        A.coverage("BUILD-NOPE")
