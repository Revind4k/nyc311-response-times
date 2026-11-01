"""Load the monthly extracts into DuckDB and build the staging table.

uv run python -m pipeline.build
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "nyc311.duckdb"


def connect(db: Path = DB) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db))
    # 311 timestamps are New York wall-clock time; the pull time is stored in UTC. Pin the
    # session zone so the conversion is the same on a laptop and on a UTC CI runner.
    con.execute("set TimeZone = 'America/New_York'")
    return con


def build(con: duckdb.DuckDBPyConnection, raw_dir: Path = ROOT / "data" / "raw") -> None:
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    rows = [(m["file"], m["pulled_at"], m["rows"]) for m in manifest.values()]
    con.execute("create or replace table manifest (file varchar, pulled_at timestamptz, rows bigint)")
    con.executemany("insert into manifest values (?, ?, ?)", rows)
    sql = (ROOT / "sql" / "01_staging.sql").read_text().replace("data/raw/", f"{raw_dir.as_posix()}/")
    con.execute(sql)
    ((loaded,),) = con.execute("select count(*) from requests").fetchall()
    expected = sum(r[2] for r in rows)
    if loaded != expected:
        raise RuntimeError(f"loaded {loaded} rows but the manifest says {expected}")


if __name__ == "__main__":
    con = connect()
    build(con)
    print(con.sql("select quality, count(*) n from requests group by 1 order by 2 desc"))
