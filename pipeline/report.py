"""Time-to-close tables for the README and the data behind the dashboard.

uv run python -m pipeline.report      # writes docs/data.json and results/summary.md
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import duckdb
import numpy as np

from pipeline.build import connect
from pipeline.survival import kaplan_meier, km_quantile

ROOT = Path(__file__).resolve().parents[1]
CURVE_AGENCIES = ["NYPD", "HPD", "DSNY", "DOT", "DPR", "TLC"]
FOCUS = ["HEAT/HOT WATER", "Noise - Residential", "Illegal Parking", "UNSANITARY CONDITION", "Street Condition"]


def summarize(con: duckdb.DuckDBPyConnection, where: str = "true", params: list | None = None) -> dict:
    hours, closed, instant = (
        con.execute(
            f"select hours, is_closed, instant_close from requests where quality = 'ok' and {where}", params or []
        )
        .fetchnumpy()
        .values()
    )
    closed = closed.astype(bool)
    n = int(hours.size)
    if n == 0:
        return {"n": 0}
    hours = np.clip(hours, 0, None)  # an open request created after a month's pull can't exist; guard anyway
    return {
        "n": n,
        "open_share": round(1 - closed.mean(), 4),
        "instant_share": round(instant.astype(bool).mean(), 4),
        "naive_median_h": round(float(np.median(hours[closed])), 2) if closed.any() else None,
        "km_median_h": finite(km_quantile(hours, closed, 0.5)),
        "km_p90_h": finite(km_quantile(hours, closed, 0.9)),
    }


def curve(con: duckdb.DuckDBPyConnection, agency: str, grid: np.ndarray) -> list[float]:
    """Kaplan-Meier share still open at each grid time (hours), for the dashboard."""
    hours, closed = (
        con.execute("select greatest(hours, 0), is_closed from requests where quality = 'ok' and agency = ?", [agency])
        .fetchnumpy()
        .values()
    )
    times, surv = kaplan_meier(hours, closed.astype(bool))
    idx = np.searchsorted(times, grid, side="right") - 1
    return [round(float(surv[i]), 4) if i >= 0 else 1.0 for i in idx]


def finite(x: float) -> float | None:
    return None if math.isinf(x) else round(x, 2)


def group(con, column: str, limit: int, extra: str = "true", params: list | None = None) -> list[dict]:
    keys = [
        k
        for (k,) in con.execute(
            f"select {column} from requests where quality = 'ok' and {column} is not null and {extra} "
            f"group by 1 order by count(*) desc limit {limit}",
            params or [],
        ).fetchall()
    ]
    return [{column: k, **summarize(con, f"{column} = ? and {extra}", [k, *(params or [])])} for k in keys]


def fmt(h: float | None) -> str:
    if h is None:
        return "not reached"
    if h < 1:
        return f"{h * 60:.0f} min"
    return f"{h:.1f} h" if h < 48 else f"{h / 24:.1f} days"


def table(rows: list[dict], key: str, label: str) -> str:
    out = [
        (
            f"| {label} | Requests | Still open | Closed in under a minute | Median, closed only | "
            "Median, Kaplan-Meier | 90th percentile, KM |"
        ),
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r[key]} | {r['n']:,} | {r['open_share']:.1%} | {r['instant_share']:.1%} | "
            f"{fmt(r['naive_median_h'])} | {fmt(r['km_median_h'])} | {fmt(r['km_p90_h'])} |"
        )
    return "\n".join(out)


def main() -> None:
    con = connect()
    quality = con.execute("select quality, count(*) from requests group by 1 order by 2 desc").fetchall()
    overall = summarize(con)
    by_type = group(con, "complaint_type", 20)
    by_agency = group(con, "agency", 12)
    by_borough = {t: group(con, "borough", 5, "complaint_type = ?", [t]) for t in FOCUS}
    monthly = {
        t: [
            {"month": m, **summarize(con, "complaint_type = ? and month(created_at) = ?", [t, m])} for m in range(1, 13)
        ]
        for t in FOCUS[:2]
    }

    grid = np.unique(np.round(np.geomspace(0.1, 24 * 365, 60), 2))
    curves = {"hours": grid.tolist(), "agencies": {a: curve(con, a, grid) for a in CURVE_AGENCIES}}

    data = {
        "quality": quality,
        "curves": curves,
        "overall": overall,
        "by_type": by_type,
        "by_agency": by_agency,
        "by_borough": by_borough,
        "monthly": monthly,
        "pulled": con.execute("select min(pulled_at)::varchar, max(pulled_at)::varchar from manifest").fetchall()[0],
    }
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "data.json").write_text(json.dumps(data, indent=1) + "\n")

    md = ["## Data quality", "", "| Verdict | Requests |", "|---|---|"]
    md += [f"| {q} | {n:,} |" for q, n in quality]
    md += [
        "",
        "## Overall",
        "",
        json.dumps(overall),
        "",
        "## By complaint type (20 largest)",
        "",
        table(by_type, "complaint_type", "Complaint type"),
        "",
        "## By agency (12 largest)",
        "",
        table(by_agency, "agency", "Agency"),
    ]
    for t, rows in by_borough.items():
        md += ["", f"## {t} by borough", "", table(rows, "borough", "Borough")]
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
