"""Download one calendar year of NYC 311 service requests, one gzipped CSV per month.

    uv run python -m pipeline.extract --year 2025

Source: NYC Open Data, "311 Service Requests from 2010 to Present" (erm2-nwe9), via the
Socrata SODA API. Only the columns the analysis uses are requested. Each month is written to
a temp file and renamed into place only after the row count matches the server's count for
that month, so a dropped connection never leaves a half-written file that looks complete.
Re-running skips months that already verified, and data/raw/manifest.json records row
counts, SHA-256 checksums and the moment each month was pulled (needed later: a request
that is still open is "open as of" that moment).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE = "https://data.cityofnewyork.us/resource/erm2-nwe9"
COLUMNS = [
    "unique_key",
    "created_date",
    "closed_date",
    "agency",
    "complaint_type",
    "descriptor",
    "status",
    "incident_zip",
    "borough",
    "community_board",
    "open_data_channel_type",
]
PAGE = 250_000
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def month_bounds(year: int, month: int) -> tuple[str, str]:
    start = f"{year}-{month:02d}-01T00:00:00"
    end = f"{year + (month == 12)}-{month % 12 + 1:02d}-01T00:00:00"
    return start, end


def where(year: int, month: int) -> str:
    start, end = month_bounds(year, month)
    return f"created_date >= '{start}' AND created_date < '{end}'"


def get(client: httpx.Client, url: str, params: dict, tries: int = 5) -> httpx.Response:
    for attempt in range(tries):
        try:
            r = client.get(url, params=params, timeout=300)
            if r.status_code < 500 and r.status_code != 429:
                r.raise_for_status()
                return r
        except (httpx.TransportError, httpx.TimeoutException):
            if attempt == tries - 1:
                raise
        time.sleep(2**attempt)
    r.raise_for_status()
    return r


def server_count(client: httpx.Client, year: int, month: int) -> int:
    r = get(client, f"{BASE}.json", {"$select": "count(*)", "$where": where(year, month)})
    return int(r.json()[0]["count"])


def download_month(client: httpx.Client, year: int, month: int) -> dict:
    expected = server_count(client, year, month)
    out = RAW / f"{year}-{month:02d}.csv.gz"
    tmp = out.with_suffix(".tmp")
    rows = 0
    with gzip.open(tmp, "wt", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        offset = 0
        while True:
            params = {
                "$select": ",".join(COLUMNS),
                "$where": where(year, month),
                "$order": "unique_key",
                "$limit": PAGE,
                "$offset": offset,
            }
            text = get(client, f"{BASE}.csv", params).text
            page = list(csv.reader(io.StringIO(text)))[1:]  # drop the header Socrata repeats per page
            writer.writerows(page)
            rows += len(page)
            offset += PAGE
            if len(page) < PAGE:
                break
    if rows != expected:
        tmp.unlink()
        raise RuntimeError(f"{out.name}: got {rows} rows, server says {expected}")
    tmp.rename(out)
    return {
        "file": out.name,
        "rows": rows,
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "pulled_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    with httpx.Client(headers={"Accept-Encoding": "gzip"}) as client:
        for month in range(1, 13):
            key = f"{args.year}-{month:02d}"
            done = manifest.get(key)
            if (
                done
                and (RAW / done["file"]).exists()
                and hashlib.sha256((RAW / done["file"]).read_bytes()).hexdigest() == done["sha256"]
            ):
                print(f"{key}: verified, skipping")
                continue
            manifest[key] = download_month(client, args.year, month)
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            print(f"{key}: {manifest[key]['rows']:,} rows")


if __name__ == "__main__":
    main()
