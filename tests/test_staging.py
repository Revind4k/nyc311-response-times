import csv
import gzip
import json

import pytest

from pipeline.build import build, connect
from pipeline.extract import COLUMNS


def write_month(raw, rows, pulled_at="2026-01-01T05:00:00+00:00"):
    raw.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw / "2025-01.csv.gz", "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r.get(c, "") for c in COLUMNS])
    (raw / "manifest.json").write_text(
        json.dumps({"2025-01": {"file": "2025-01.csv.gz", "rows": len(rows), "sha256": "x", "pulled_at": pulled_at}})
    )


def req(key, created, closed, status, **kw):
    return {
        "unique_key": key,
        "created_date": created,
        "closed_date": closed,
        "status": status,
        "agency": "HPD",
        "complaint_type": "HEAT/HOT WATER",
        "borough": "BRONX",
        **kw,
    }


def test_every_row_is_kept_and_classified(tmp_path):
    raw = tmp_path / "raw"
    write_month(
        raw,
        [
            req(1, "2025-01-02T08:00:00.000", "2025-01-02T10:30:00.000", "Closed"),
            req(2, "2025-01-02T08:00:00.000", "", "Closed"),
            req(3, "2025-01-02T08:00:00.000", "2025-01-01T08:00:00.000", "Closed"),
            req(4, "2025-01-02T08:00:00.000", "2026-03-01T00:00:00.000", "Closed"),
            req(5, "2025-12-31T00:00:00.000", "2026-02-01T00:00:00.000", "In Progress"),
            req(6, "2025-01-02T08:00:00.000", "2025-01-02T08:00:30.000", "Closed", borough="Unspecified"),
            req(7, "2025-01-02T08:00:00.000", "2025-01-02T08:01:00.000", "Closed"),
        ],
    )
    con = connect(tmp_path / "t.duckdb")
    build(con, raw)
    got = dict(con.execute("select request_id, quality from requests").fetchall())
    assert got == {
        1: "ok",
        2: "closed_without_date",
        3: "closed_before_created",
        4: "closed_in_future",
        5: "ok",
        6: "ok",
        7: "ok",
    }
    hours = dict(con.execute("select request_id, hours from requests where quality = 'ok'").fetchall())
    assert hours[1] == 2.5
    # Still open: measured to the pull, 2026-01-01 00:00 New York time, not to the target date in closed_date.
    assert hours[5] == 24.0
    flags = con.execute(
        "select request_id, is_closed, instant_close, borough from requests where request_id in (5, 6, 7) order by 1"
    ).fetchall()
    # 30 seconds counts as an instant close; a full minute does not.
    assert flags == [(5, False, False, "BRONX"), (6, True, True, None), (7, True, False, "BRONX")]


@pytest.mark.parametrize("manifest_rows", [0, 2])
def test_row_count_must_match_the_manifest(tmp_path, manifest_rows):
    # Too few rows means a truncated download; too many means a month was loaded twice.
    raw = tmp_path / "raw"
    write_month(raw, [req(1, "2025-01-02T08:00:00.000", "", "Open")])
    m = json.loads((raw / "manifest.json").read_text())
    m["2025-01"]["rows"] = manifest_rows
    (raw / "manifest.json").write_text(json.dumps(m))
    con = connect(tmp_path / "t.duckdb")
    with pytest.raises(RuntimeError, match=f"manifest says {manifest_rows}"):
        build(con, raw)
