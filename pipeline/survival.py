"""Kaplan-Meier estimates for time-to-close when some requests are still open.

A request that is still open when the data was pulled has not "survived forever"; we only
know it took at least (pull time - created). Dropping those rows, which is what a plain
median over closed requests does, keeps only the requests that closed quickly enough to be
in the closed set and biases every wait time downward. Kaplan-Meier treats them as
right-censored instead: they count as "still waiting" up to the moment we stopped looking.
"""

from __future__ import annotations

import numpy as np


def kaplan_meier(durations: np.ndarray, closed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (event_times, survival) where survival[i] = P(still open just after event_times[i]).

    durations: time from creation to close (closed) or to the data pull (still open).
    closed:    True where the request closed, False where it is censored (still open).
    """
    durations = np.asarray(durations, dtype=float)
    closed = np.asarray(closed, dtype=bool)
    if durations.shape != closed.shape:
        raise ValueError("durations and closed must have the same shape")
    if durations.size == 0:
        return np.array([]), np.array([])
    if np.any(durations < 0):
        raise ValueError("durations must be non-negative")

    order = np.argsort(durations, kind="stable")
    t, e = durations[order], closed[order]
    times, first = np.unique(t, return_index=True)
    # Requests still at risk at each distinct time: everything not yet removed before it.
    at_risk = t.size - first
    events = np.add.reduceat(e.astype(int), first)
    keep = events > 0
    hazard = events[keep] / at_risk[keep]
    return times[keep], np.cumprod(1.0 - hazard)


def km_quantile(durations: np.ndarray, closed: np.ndarray, q: float = 0.5) -> float:
    """Smallest time at which at least a fraction q of requests have closed (KM estimate).

    Returns inf when the curve never gets that far, e.g. when most requests are still open.
    """
    if not 0 < q < 1:
        raise ValueError("q must be in (0, 1)")
    times, surv = kaplan_meier(durations, closed)
    hit = np.nonzero(surv <= 1 - q + 1e-12)[0]
    return float(times[hit[0]]) if hit.size else float("inf")
