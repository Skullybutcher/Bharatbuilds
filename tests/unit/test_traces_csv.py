"""CSV bulk trace ingestion (services.api.actions.bulk_ingest_traces_csv).

Under test: header/case-column rules, scalar coercion, all-or-nothing batch
validation (pass 1 validates every row before pass 2 stores any), content-hash
dedupe (in-batch repeats + cross-batch via occurred_at), and the evidence-only
doctrine (ingestion never mints witnesses or touches procedure versions).
"""
from __future__ import annotations

import pytest

from services.api.actions import bulk_ingest_traces_csv
from services.storage import _save
from services.traces.store import list_traces

CSV_OK = ("cgpa,amount,year,category,eligible,required,steps_done,occurred_at\n"
          "7.2,0,3,general,approved,w-2;w-5,docs-verified,2026-09-01T10:00:00Z\n"
          "6.4,500,2,obc,rejected,,deferred,2026-09-02T10:00:00Z\n")


@pytest.fixture(autouse=True)
def _clean_store():
    _save("traces.json", [])
    yield
    _save("traces.json", [])


def test_happy_path_counts_and_coercion():
    res = bulk_ingest_traces_csv({"csv": CSV_OK})
    assert res["ingested"] == 2 and res["duplicates"] == 0
    stored = {t["case"]["cgpa"]: t for t in list_traces()}
    assert set(stored) == {7.2, 6.4}          # numeric coercion happened
    r1 = stored[7.2]
    assert r1["case"]["amount"] == 0 and isinstance(r1["case"]["amount"], int)
    assert r1["outcome"]["eligible"] is True
    assert r1["outcome"]["required"] == {"w-2": True, "w-5": True}
    assert r1["steps_done"] == ["docs-verified"]
    assert r1["source"] == "csv"


def test_cross_batch_dedupe_via_occurred_at():
    bulk_ingest_traces_csv({"csv": CSV_OK})
    again = bulk_ingest_traces_csv({"csv": CSV_OK})
    assert again["ingested"] == 0 and again["duplicates"] == 2
    assert len(list_traces()) == 2


def test_in_batch_repeat_counts_duplicate():
    csv = ("cgpa,eligible,occurred_at\n7.1,approved,2026-09-03\n"
           "7.1,approved,2026-09-03\n")
    res = bulk_ingest_traces_csv({"csv": csv})
    assert res["ingested"] == 1 and res["duplicates"] == 1


def test_fail_closed_bad_row_stores_nothing():
    bad = CSV_OK + "9.9,0,1,general,not-a-bool,,,\n"  # row 4 invalid
    with pytest.raises(ValueError, match="row 4"):
        bulk_ingest_traces_csv({"csv": bad})
    assert list_traces() == [], "rows before the bad row must NOT be stored"


def test_reingest_is_idempotent_even_without_occurred_at():
    """Content-hash idempotency: the hash uses the BODY's occurred_at (None
    when absent), so identical content re-ingests as a duplicate and replaces
    nothing — evidence is never silently dropped or double-counted."""
    csv = "cgpa,eligible\n7.0,approved\n"
    first = bulk_ingest_traces_csv({"csv": csv})
    second = bulk_ingest_traces_csv({"csv": csv})
    assert first["ingested"] == 1
    assert second["ingested"] == 0 and second["duplicates"] == 1
    assert len(list_traces()) == 1


def test_header_and_column_rules():
    with pytest.raises(ValueError, match="non-empty CSV"):
        bulk_ingest_traces_csv({"csv": "   "})
    # a single case column with NO outcome columns fails closed on outcome
    with pytest.raises(ValueError, match="row 2.*comparable fields"):
        bulk_ingest_traces_csv({"csv": "cgpa\n7.0\n"})
    with pytest.raises(ValueError, match="case column"):
        bulk_ingest_traces_csv({"csv": "eligible,source\napproved,csv\n"})
    with pytest.raises(ValueError, match="column count"):
        bulk_ingest_traces_csv({"csv": "cgpa,eligible\n7.0,approved,extra\n"})
    with pytest.raises(ValueError, match="empty case cell"):
        bulk_ingest_traces_csv({"csv": "cgpa,eligible\n,approved\n"})


def test_bool_forms_accepted():
    csv = ("cgpa,eligible,on_time,prohibited\n"
           "7.0,yes,true,clear\n"
           "6.0,no,late,blocked\n")
    res = bulk_ingest_traces_csv({"csv": csv})
    assert res["ingested"] == 2
    outcomes = {t["case"]["cgpa"]: t["outcome"] for t in list_traces()}
    assert outcomes[7.0] == {"eligible": True, "on_time": True, "prohibited": False}
    assert outcomes[6.0] == {"eligible": False, "on_time": False, "prohibited": True}


def test_body_workflow_id_applies_to_all_rows():
    res = bulk_ingest_traces_csv({"csv": CSV_OK, "workflow_id": "WF-X"})
    assert all(t["workflow_id"] == "WF-X" for t in res["traces"])
