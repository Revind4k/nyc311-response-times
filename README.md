# nyc311-response-times

[![CI](https://github.com/Revind4k/nyc311-response-times/actions/workflows/ci.yml/badge.svg)](https://github.com/Revind4k/nyc311-response-times/actions/workflows/ci.yml)

How long does New York City take to close a 311 service request? This project loads every request created in 2025 (3,655,042 of them) from NYC Open Data into DuckDB, classifies data-quality problems instead of silently dropping them, and estimates wait times with **Kaplan-Meier survival analysis**, so requests that are still open count as "still waiting" rather than disappearing from the average.

**Dashboard:** https://revind4k.github.io/nyc311-response-times/

## Why survival analysis

The obvious way to measure response time is the median over closed requests. That quietly removes every request that hasn't been closed yet, and those are the slow ones, so the answer comes out too fast. A request still open when the data was pulled tells us only that it has taken *at least* this long. Kaplan-Meier treats it as right-censored at that moment, which is the standard fix (it's how clinical trials handle patients still alive at the end of a study).

For most of the city it barely matters: only 1.4% of 2025 requests were still open in November 2026. For the agencies with long backlogs it matters a lot:

| Agency | Requests | Still open | Median, closed only | Median, Kaplan-Meier |
|---|---|---|---|---|
| Parks (DPR) | 110,855 | 13.8% | 8.9 days | **15.9 days** |
| Taxi & Limousine (TLC) | 36,225 | 16.8% | 69.7 days | **103.7 days** |
| Transportation (DOT) | 212,095 | 3.1% | 46.6 h | **2.1 days** |
| Buildings (DOB) | 103,068 | 2.0% | 12.2 days | **13.3 days** |
| Police (NYPD) | 1,717,526 | 0.0% | 1.3 h | 1.3 h |
| Housing (HPD) | 774,535 | 0.4% | 3.3 days | 3.3 days |

Parks' open backlog is mostly trees: 29% of "Overgrown Tree/Branches" and 28% of "Root/Sewer/Sidewalk Condition" requests from 2025 were still open 10 or more months later.

## Results

Kaplan-Meier median and 90th percentile, 20 most common complaint types (full tables in [`results/summary.md`](results/summary.md)):

| Complaint type | Requests | Median | 90th percentile |
|---|---|---|---|
| Illegal Parking | 577,253 | 1.5 h | 7.1 h |
| Noise - Residential | 463,310 | 1.2 h | 8.1 h |
| HEAT/HOT WATER | 315,946 | 39.6 h | 3.2 days |
| Noise - Street/Sidewalk | 173,036 | 53 min | 4.0 h |
| Blocked Driveway | 172,723 | 1.7 h | 7.8 h |
| UNSANITARY CONDITION | 117,749 | 10.7 days | 65.7 days |
| Water System | 77,419 | 3.9 h | 9.9 days |
| Street Condition | 70,324 | 27.7 h | 8.6 days |
| PLUMBING | 69,548 | 8.1 days | 63.6 days |
| Abandoned Vehicle | 67,903 | 2.1 h | 10.7 h |
| DOOR/WINDOW | 45,463 | 12.1 days | 79.8 days |
| Missed Collection | 42,977 | 2.3 days | 9.2 days |

- **Police-handled complaints close in hours; housing-condition complaints take weeks.** NYPD (noise, parking, blocked driveways) has a 1.3-hour median. HPD's apartment-condition complaints (unsanitary conditions, plumbing, doors and windows) have medians of 8 to 12 days and 90th percentiles of two to three months.
- **Heat complaints are a winter problem, and the Bronx files the most.** HEAT/HOT WATER requests peak in January and December. The Bronx filed 112,368 of them, more than any other borough (Brooklyn is next at 82,248), yet its median close (33.5 h) is the fastest of the four large boroughs.
- **Noise complaints are closed fastest in Manhattan and slowest in the Bronx** (53 min vs 1.8 h median), and the Bronx files twice as many residential noise complaints as Brooklyn.
- **Queens street-condition requests (potholes and the like) have the biggest open backlog**: 10.2% still open, so their 90th percentile is never reached within the follow-up period.

### What "closed" means

A closed 311 request means the agency closed the ticket, which is not necessarily the same as the problem being fixed; each agency decides when a ticket is done. These numbers measure **time until the ticket is closed**, not time to resolution.

2% of requests close within a minute of being created, which is too fast to be a fix in the field; it is concentrated in a few agencies: DOHMH closes 30% of its requests that fast, DOB 11%, DEP 9%. They are kept in the medians (they really were closed) and reported in their own column so they can be told apart.

## Data quality

Every row is kept and given one verdict in `sql/01_staging.sql`; the analysis reads only `ok`.

| Verdict | Requests | Rule |
|---|---|---|
| ok | 3,648,941 | |
| closed_without_date | 6,024 | Status is Closed but there is no close timestamp, so the duration is unknown |
| closed_before_created | 77 | Close timestamp earlier than the creation timestamp |
| closed_in_future | 0 | Close timestamp after the data was pulled (checked, none in 2025) |

Two more traps the staging step handles:

- **A close date on an open ticket.** 3,813 requests whose status is not Closed (In Progress, Pending, Assigned...) already have a `closed_date`. Some agencies use the column for a target date. Status decides: those requests are treated as open, censored at the pull time.
- **Time zones.** 311 timestamps are New York wall-clock time; the pull time is recorded in UTC. The DuckDB session is pinned to `America/New_York` so the subtraction gives the same answer on a laptop and on a UTC CI runner, and a test checks it.

## Pipeline

```
NYC Open Data SODA API (erm2-nwe9)
        │  pipeline/extract.py: one month at a time, 11 columns, paged,
        │  written to a temp file and renamed only after the row count
        │  matches the server's count; manifest.json records rows,
        │  SHA-256 and pull time; re-runs skip verified months
        ▼
data/raw/2025-MM.csv.gz  (12 files, 71 MB)
        │  pipeline/build.py + sql/01_staging.sql: DuckDB reads the gzipped
        │  CSVs in place, types every column, assigns a quality verdict,
        │  computes hours to close (or to the pull, if still open), and fails
        │  if the loaded row count differs from the manifest in either direction
        ▼
nyc311.duckdb · requests
        │  pipeline/survival.py: Kaplan-Meier estimator and quantiles (numpy)
        │  pipeline/report.py: tables by type, agency and borough, survival curves
        ▼
results/summary.md · docs/data.json → docs/index.html (Vega-Lite dashboard)
```

The Kaplan-Meier estimator is about 20 lines of numpy rather than a library call, so it is tested against a published result: the Freireich et al. (1963) 6-MP leukemia trial, the textbook example, whose survival curve (to three decimals) and median (23 weeks) it reproduces.

## Running it

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run python -m pipeline.extract --year 2025   # about 3.7M rows, 71 MB; several minutes
uv run python -m pipeline.build                 # loads into nyc311.duckdb
uv run python -m pipeline.report                # writes results/summary.md and docs/data.json
uv run pytest
```

## Tests

`uv run pytest` runs 15 offline tests on every push (GitHub Actions, along with ruff):

- the Kaplan-Meier estimator against the published 6-MP curve, the no-censoring case (where it must equal the plain empirical distribution), the exact-boundary quantile, and a constructed case showing the naive median is biased;
- staging classification on synthetic rows: every verdict, open requests measured to the pull time rather than to a target date in `closed_date`, the under-a-minute boundary, "Unspecified" borough handled as missing;
- the manifest row-count check in both directions (truncated download, month loaded twice).
- the report helpers on a small in-memory table: open requests censored rather than dropped, rows with a bad quality verdict excluded, the dashboard's survival curve stepping only at closes, and the unit boundaries in the formatted times.

The tests were mutation-checked: deliberately breaking the at-risk count, the quality rules, the open-request duration, the instant-close boundary, or the row-count check each makes a test fail.

## Caveats

- **Observational.** Differences between boroughs or agencies reflect complaint mix, staffing and how each agency defines "closed", not just speed.
- **Censoring assumes a request's open time says nothing about its eventual close beyond "at least this long".** That's the standard Kaplan-Meier assumption. If some open tickets are simply abandoned and will never be closed, the true medians for those agencies are even longer.
- **Follow-up differs by month.** A request from December 2025 had about 10 months to close before the pull; one from January had 21. Kaplan-Meier accounts for this, but tail estimates (90th percentiles) for late-year requests rest on less data.
- One year only (2025); the data was pulled on 2026-11-01.

Data: [NYC Open Data, 311 Service Requests from 2010 to Present](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2010-to-Present/erm2-nwe9), published by the City of New York under its open-data terms.
