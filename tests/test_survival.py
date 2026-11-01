import numpy as np
import pytest

from pipeline.survival import kaplan_meier, km_quantile

# Freireich et al. (1963), 6-MP arm: weeks in remission for 21 leukemia patients, the standard
# textbook Kaplan-Meier example. False = censored. Published KM median: 23 weeks.
SIX_MP = [
    (6, True),
    (6, True),
    (6, True),
    (6, False),
    (7, True),
    (9, False),
    (10, True),
    (10, False),
    (11, False),
    (13, True),
    (16, True),
    (17, False),
    (19, False),
    (20, False),
    (22, True),
    (23, True),
    (25, False),
    (32, False),
    (32, False),
    (34, False),
    (35, False),
]


def arrays(pairs):
    return np.array([t for t, _ in pairs], float), np.array([c for _, c in pairs])


def test_matches_the_published_six_mp_curve():
    t, c = arrays(SIX_MP)
    times, surv = kaplan_meier(t, c)
    assert times.tolist() == [6, 7, 10, 13, 16, 22, 23]
    # Published values: 0.857, 0.807, 0.753, 0.690, 0.627, 0.538, 0.448
    assert np.round(surv, 3).tolist() == [0.857, 0.807, 0.753, 0.690, 0.627, 0.538, 0.448]
    assert km_quantile(t, c) == 23


def test_without_censoring_it_is_the_empirical_distribution():
    t = np.array([1, 2, 2, 3, 4, 5], float)
    times, surv = kaplan_meier(t, np.ones(6, bool))
    assert times.tolist() == [1, 2, 3, 4, 5]
    assert np.allclose(surv, [5 / 6, 3 / 6, 2 / 6, 1 / 6, 0])
    assert km_quantile(t, np.ones(6, bool)) == 2


def test_quantile_is_reached_when_survival_equals_the_target():
    # Two of four closed by t=2, so survival is exactly 0.5 there and the median is 2, not 3.
    t = np.array([1, 2, 3, 4], float)
    assert km_quantile(t, np.ones(4, bool), 0.5) == 2


def test_dropping_open_requests_understates_the_wait():
    # Ten requests closed within a day; ten are still open after 30 days.
    t = np.array([0.5] * 10 + [30] * 10)
    closed = np.array([True] * 10 + [False] * 10)
    naive = np.median(t[closed])
    assert naive == 0.5
    # KM: half closed at 0.5 days, nobody else closed before we stopped looking.
    assert km_quantile(t, closed, 0.5) == 0.5
    assert km_quantile(t, closed, 0.75) == float("inf")


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        kaplan_meier(np.array([-1.0]), np.array([True]))
    with pytest.raises(ValueError):
        kaplan_meier(np.array([1.0, 2.0]), np.array([True]))
    with pytest.raises(ValueError):
        km_quantile(np.array([1.0]), np.array([True]), 1.0)
