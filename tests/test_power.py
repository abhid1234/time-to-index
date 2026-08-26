"""Power analysis.

The Schoenfeld checks are against values that appear in every survival
textbook, which is the point: the arithmetic here decides whether the repo
says "A is faster than B" or "not yet", and it should be checkable against
something other than itself.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti.metrics import Observation, logrank
from tti.power import (achieved_power, analyse, events_for_power, hazard_ratio,
                       proportions_n, _ppf)


def test_schoenfeld_matches_published_values():
    # Two-sided alpha=0.05, power=0.80. These three appear in the standard
    # tables; if this drifts, every "days needed" number in the repo is wrong.
    assert events_for_power(2.0) == pytest.approx(66, abs=1)
    assert events_for_power(1.5) == pytest.approx(191, abs=1)
    assert events_for_power(1.2) == pytest.approx(945, abs=2)


def test_power_and_sample_size_are_inverses():
    for hr in (1.3, 1.75, 2.5):
        n = events_for_power(hr)
        assert achieved_power(hr, round(n)) == pytest.approx(0.8, abs=0.01)


def test_no_effect_needs_infinite_events():
    assert events_for_power(1.0) is None
    assert analyse("a", [], "b", [], float("nan")).verdict == "no difference to detect"


def test_normal_quantile_approximation():
    assert _ppf(0.975) == pytest.approx(1.959964, abs=1e-4)
    assert _ppf(0.8) == pytest.approx(0.841621, abs=1e-4)
    assert _ppf(0.5) == pytest.approx(0.0, abs=1e-9)


def test_hazard_ratio_agrees_with_the_log_rank_direction():
    """A ratio estimated some other way could disagree with the test about
    which arm is ahead, and a rendered table would never show it."""
    fast = [Observation(float(10 + i), True) for i in range(30)]
    slow = [Observation(float(400 + i), True) for i in range(30)]
    hr, n = hazard_ratio(fast, slow)
    assert hr > 1 and n == 60
    _, p = logrank(fast, slow)
    assert p < 0.001
    hr_rev, _ = hazard_ratio(slow, fast)
    assert hr_rev < 1


def test_small_run_is_reported_as_underpowered_not_as_a_tie():
    """Six events with a real difference must not read as 'no difference'."""
    a = [Observation(100.0, True)] * 3 + [Observation(259200.0, False)] * 1
    b = [Observation(150.0, True)] * 3 + [Observation(259200.0, False)] * 1
    _, p = logrank(a, b)
    r = analyse("a", a, "b", b, p, events_per_day=4.0)
    assert r.verdict.startswith("underpowered")
    assert r.events_needed and r.events_needed > 0
    assert r.days_needed and r.days_needed > 0


def test_days_needed_scales_with_the_observed_event_rate():
    a = [Observation(100.0, True)] * 10
    b = [Observation(160.0, True)] * 10
    _, p = logrank(a, b)
    slow = analyse("a", a, "b", b, p, events_per_day=2.0)
    fast = analyse("a", a, "b", b, p, events_per_day=20.0)
    if slow.days_needed and fast.days_needed:
        assert slow.days_needed == pytest.approx(fast.days_needed * 10, rel=1e-6)


def test_proportion_sample_size_is_sane():
    # Distinguishing 30% from 45% staleness needs a few hundred probes per arm.
    n = proportions_n(0.30, 0.45)
    assert 140 < n < 200
    # A tiny difference needs a lot more.
    assert proportions_n(0.30, 0.32) > 5000
    assert proportions_n(0.3, 0.3) is None
