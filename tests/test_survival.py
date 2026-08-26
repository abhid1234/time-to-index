"""Turnbull NPMLE checks.

The load-bearing one is `test_reduces_to_kaplan_meier_on_right_censored_data`.
Turnbull's estimator provably collapses to Kaplan-Meier when every
observation is either an exact event or right-censored, so running it on the
Freireich 1963 data -- whose Kaplan-Meier values are published and already
checked in test_metrics.py -- ties the new estimator to a known-good one
rather than to my own arithmetic.
"""
import pathlib, sys, math
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti.metrics import Observation, kaplan_meier
from tti.survival import INF, Interval, fit, intervals_from_ladder

FREIREICH_T = [6, 6, 6, 6, 7, 9, 10, 10, 11, 13, 16, 17, 19, 20, 22, 23, 25, 32, 32, 34, 35]
FREIREICH_C = [0, 0, 0, 1, 0, 1,  0,  1,  1,  0,  0,  1,  1,  1,  0,  0,  1,  1,  1,  1,  1]


def test_reduces_to_kaplan_meier_on_right_censored_data():
    eps = 1e-6
    obs = [Interval(t - eps, float(t)) if not c else Interval(float(t), INF)
           for t, c in zip(FREIREICH_T, FREIREICH_C)]
    est = fit(obs)
    km = kaplan_meier([Observation(float(t), not c)
                       for t, c in zip(FREIREICH_T, FREIREICH_C)])
    km_at = dict(zip(km.times, km.survival))
    for t in (6, 7, 10, 13, 22, 23):
        s_turnbull = 1.0 - est.cdf_upper(float(t))
        assert abs(s_turnbull - km_at[float(t)]) < 1e-6, (
            t, s_turnbull, km_at[float(t)])


def test_exact_observations_give_the_empirical_distribution():
    eps = 1e-9
    obs = [Interval(t - eps, float(t)) for t in (1, 1, 2, 3, 3, 3)]
    est = fit(obs)
    got = {round(hi): m for (lo, hi), m in zip(est.support, est.mass)}
    assert got == {1: pytest.approx(2 / 6), 2: pytest.approx(1 / 6),
                   3: pytest.approx(3 / 6)}


def test_log_likelihood_is_not_decreased_by_em():
    """EM is a monotone ascent on the likelihood. A run where it falls means
    the update is wrong, and would be invisible in the fitted numbers."""
    obs = ([Interval(0, 300)] * 7 + [Interval(300, 900)] * 11 +
           [Interval(900, 3600)] * 5 + [Interval(3600, INF)] * 9)
    prev = -math.inf
    for it in (1, 2, 3, 5, 10, 50, 500):
        est = fit(obs, max_iter=it, tol=0.0)
        assert est.loglik >= prev - 1e-9, (it, est.loglik, prev)
        prev = est.loglik


def test_a_missing_rung_widens_rather_than_invents():
    """The whole reason for this estimator.

    Two arms index identically. One had its 15m and 1h probes dropped (budget
    cap, say). A point estimator must either discard that arm's event or
    record it at a rung nobody observed. Turnbull records the honest wider
    interval, and the resulting bracket is wider -- not shifted.
    """
    full = intervals_from_ladder([(300, False), (900, False), (3600, True)])
    gappy = intervals_from_ladder([(300, False), (3600, True)])
    assert full == Interval(900, 3600)
    assert gappy == Interval(300, 3600)

    lo_f, hi_f = fit([full] * 20).quantile_bracket(0.5)
    lo_g, hi_g = fit([gappy] * 20).quantile_bracket(0.5)
    assert (lo_f, hi_f) == (900, 3600)
    assert (lo_g, hi_g) == (300, 3600)      # wider, same upper bound
    assert lo_g < lo_f and hi_g == hi_f


def test_support_includes_the_already_indexed_bucket():
    """Endpoint-ordering bug guard.

    If upper bounds do not sort before lower bounds at equal values, the
    (0, first_rung] support interval silently disappears and every arm that
    indexed before the first probe is misplaced. That is the fastest,
    most interesting bucket."""
    obs = [Interval(0, 300)] * 3 + [Interval(300, 900)] * 3
    est = fit(obs)
    assert (0.0, 300.0) in est.support
    assert est.mass[est.support.index((0.0, 300.0))] == pytest.approx(0.5)


def test_censored_mass_is_not_redistributed_into_the_observed_window():
    """An arm that never indexed must not have its probability quietly moved
    into the observed range to make the curve look complete."""
    obs = [Interval(0, 300)] * 3 + [Interval(259200, INF)] * 7
    est = fit(obs)
    assert est.cdf_upper(259_200) == pytest.approx(0.3)
    lo, hi = est.quantile_bracket(0.5)
    assert hi is None       # median is not reached inside the window


def test_recovers_a_known_mixture():
    """60% index inside (0, 300], 40% inside (3600, 21600]."""
    obs = [Interval(0, 300)] * 60 + [Interval(3600, 21600)] * 40
    est = fit(obs)
    assert est.cdf_upper(300) == pytest.approx(0.6)
    assert est.cdf_upper(21_600) == pytest.approx(1.0)
    assert est.quantile_bracket(0.5) == (0.0, 300.0)
    assert est.quantile_bracket(0.9) == (3600.0, 21600.0)


def test_builder_handles_out_of_order_and_missing_probes():
    assert intervals_from_ladder([]) is None
    # Fresh at the very first rung: lower bound is 0, not the rung.
    assert intervals_from_ladder([(300, True)]) == Interval(0, 300)
    # Unsorted input must not change the answer.
    assert intervals_from_ladder([(3600, True), (300, False)]) == Interval(300, 3600)
    # A FRESH at a later rung does not override the first one.
    assert intervals_from_ladder(
        [(300, False), (900, True), (3600, True)]) == Interval(300, 900)


def test_bootstrap_is_deterministic_and_straddles_a_rung_when_it_should():
    """A confidence interval that moves when you re-render the page is not a
    confidence interval."""
    from tti.survival import bootstrap_quantile
    obs = [Interval(300, 900)] * 18 + [Interval(900, 3600)] * 14 + [Interval(3600, INF)] * 8
    a = bootstrap_quantile(obs, 0.5, resamples=200)
    b = bootstrap_quantile(obs, 0.5, resamples=200)
    assert a == b
    lo, hi, unreached = a
    # The median sits near the 900s boundary, so the interval must not claim
    # to pin it to one rung.
    assert lo == 900.0 and hi == 3600.0 and unreached == 0.0


def test_bootstrap_reports_unreached_rather_than_inventing_a_median():
    from tti.survival import bootstrap_quantile
    obs = [Interval(300, 900)] * 5 + [Interval(259200, INF)] * 35
    lo, hi, unreached = bootstrap_quantile(obs, 0.5, resamples=200)
    assert lo is None and hi is None and unreached == 1.0


def test_bootstrap_interval_tightens_as_n_grows():
    from tti.survival import bootstrap_quantile
    base = [Interval(300, 900)] * 9 + [Interval(900, 3600)] * 11
    small = bootstrap_quantile(base, 0.5, resamples=200)
    large = bootstrap_quantile(base * 20, 0.5, resamples=200)
    small_w = (small[1] or 0) - (small[0] or 0)
    large_w = (large[1] or 0) - (large[0] or 0)
    assert large_w <= small_w
