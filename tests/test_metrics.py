import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti.metrics import Observation, fmt_duration, kaplan_meier, logrank, wilson


def test_wilson_bounds_stay_sane_at_extremes():
    p, lo, hi = wilson(10, 10)
    assert p == 1.0 and lo > 0.6 and hi == pytest.approx(1.0)
    p, lo, hi = wilson(0, 10)
    assert p == 0.0 and lo == 0.0 and hi < 0.35


def test_km_matches_textbook_freireich():
    # Freireich 1963 6-MP arm, the canonical worked example for the
    # product-limit estimator. + marks censoring.
    times = [6, 6, 6, 6, 7, 9, 10, 10, 11, 13, 16, 17, 19, 20, 22, 23, 25, 32, 32, 34, 35]
    cens  = [0, 0, 0, 1, 0, 1,  0,  1,  1,  0,  0,  1,  1,  1,  0,  0,  1,  1,  1,  1,  1]
    obs = [Observation(float(t), not c) for t, c in zip(times, cens, strict=False)]
    km = kaplan_meier(obs)
    # Published values: S(6)=0.857, S(7)=0.807, S(10)=0.753, S(13)=0.690, S(22)=0.538, S(23)=0.448
    got = dict(zip(km.times, km.survival, strict=True))
    for t, expected in [(6, 0.857), (7, 0.807), (10, 0.753), (13, 0.690), (22, 0.538), (23, 0.448)]:
        assert abs(got[float(t)] - expected) < 0.002, (t, got[float(t)], expected)
    assert km.quantile(0.5) == 23.0   # published median survival is 23 weeks


def test_censoring_bias_is_the_thing_we_avoid():
    # Ten events: two indexed at 60s, eight still un-indexed at the 72h wall.
    obs = [Observation(60.0, True)] * 2 + [Observation(259200.0, False)] * 8
    km = kaplan_meier(obs)
    # Naive "median over the indexed ones" would report 60 seconds.
    assert km.quantile(0.5) is None      # correct answer: we cannot say
    assert abs(km.at(60.0) - 0.2) < 1e-9


def test_km_confidence_band_stays_in_unit_interval():
    obs = [Observation(float(i), i % 3 != 0) for i in range(1, 40)]
    km = kaplan_meier(obs)
    assert all(0.0 <= lo <= hi <= 1.0 for lo, hi in zip(km.lower, km.upper, strict=True))


def test_logrank_separates_obvious_and_not_subtle():
    fast = [Observation(10.0, True) for _ in range(25)]
    slow = [Observation(1000.0, True) for _ in range(25)]
    chi2, p = logrank(fast, slow)
    assert p < 1e-6
    same_a = [Observation(float(10 + i), True) for i in range(25)]
    same_b = [Observation(float(10 + i), True) for i in range(25)]
    _, p2 = logrank(same_a, same_b)
    assert p2 > 0.5


def test_fmt():
    assert fmt_duration(45) == "45s"
    assert fmt_duration(600) == "10m"
    assert fmt_duration(None) == ">72h"
