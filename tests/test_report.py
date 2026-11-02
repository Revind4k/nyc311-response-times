import duckdb
import numpy as np
import pytest

from pipeline.report import curve, fmt, summarize


@pytest.fixture
def con():
    con = duckdb.connect()
    con.execute(
        "create table requests (agency varchar, quality varchar, hours double, is_closed boolean, instant_close boolean)"
    )
    con.executemany(
        "insert into requests values (?, ?, ?, ?, ?)",
        [
            ("DPR", "ok", 1.0, True, False),
            ("DPR", "ok", 2.0, True, False),
            ("DPR", "ok", 10.0, False, False),  # still open at the pull
            ("DPR", "ok", 10.0, False, False),
            ("DPR", "closed_before_created", -5.0, True, False),  # excluded by quality
            ("NYPD", "ok", 0.01, True, True),
        ],
    )
    return con


def test_summarize_censors_open_requests_and_ignores_bad_rows(con):
    s = summarize(con, "agency = ?", ["DPR"])
    assert s["n"] == 4
    assert s["open_share"] == 0.5
    assert s["naive_median_h"] == 1.5  # closed requests only
    assert s["km_median_h"] == 2.0  # half have closed by hour 2
    assert s["km_p90_h"] is None  # the curve never gets that low


def test_curve_steps_down_only_at_closes(con):
    grid = np.array([0.5, 1.0, 1.5, 2.0, 50.0])
    # 4 at risk: one closes at 1 (3/4 left), one at 2 (2/4 left); the open ones never close.
    assert curve(con, "DPR", grid) == [1.0, 0.75, 0.75, 0.5, 0.5]


@pytest.mark.parametrize(
    ("hours", "text"),
    [(None, "not reached"), (0.5, "30 min"), (1.0, "1.0 h"), (47.9, "47.9 h"), (48.0, "2.0 days")],
)
def test_fmt_picks_the_unit_at_the_boundaries(hours, text):
    assert fmt(hours) == text
