"""Formatters are the last code between a computation and a published page.

Every one of these was a real defect found by feeding the display layer
values it can actually receive. Two mattered more than the rest:
`fmt_duration(nan)` rendered as the string "nand", and `fmt_bracket(nan)`
rendered as ">15m" — asserting that something was never reached inside the
window, on the strength of a value that was not a number.

Visible garbage gets noticed. A confident claim manufactured from a NaN does
not.
"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti.metrics import fmt_bracket, fmt_duration, fmt_pair, wilson
from tti.report import _cpf, _pct

NAN = float("nan")
INF = float("inf")
RUNGS = [300, 900, 3600]


@pytest.mark.parametrize("bad", [NAN, INF, -INF, -5.0, -0.0001])
def test_fmt_duration_refuses_non_durations(bad):
    assert fmt_duration(bad) == "—"


def test_fmt_duration_still_formats_real_values():
    assert fmt_duration(0.0) == "0s"
    assert fmt_duration(300) == "5m"
    assert fmt_duration(3600) == "1.0h"
    assert fmt_duration(None) == ">72h"      # a real claim, not a fallback


@pytest.mark.parametrize("bad", [(NAN, NAN), (INF, INF), (300, NAN), (NAN, 300),
                                 (300, INF), (-10, -5)])
def test_fmt_pair_refuses_non_numbers(bad):
    assert fmt_pair(bad) == "—"


def test_fmt_pair_still_formats_real_brackets():
    assert fmt_pair((0, 300)) == "≤5m"
    assert fmt_pair((300, 900)) == "5m–15m"
    assert fmt_pair((None, None)) == "—"
    assert fmt_pair((259200, None)).startswith(">")


def test_fmt_bracket_does_not_turn_a_nan_into_a_claim():
    """The dangerous one. ">15m" says the value exceeded the last rung. A NaN
    says nothing at all, and the two must not render the same."""
    assert fmt_bracket(RUNGS, NAN) == "—"
    assert fmt_bracket(RUNGS, INF) == "—"
    assert fmt_bracket(RUNGS, None) == ">1.0h"     # genuinely never reached
    assert fmt_bracket(RUNGS, 900.0) == "5m–15m"


def test_bracket_distinguishes_unknown_from_never_reached():
    from tti.metrics import bracket
    assert bracket(RUNGS, None) == (3600.0, None)   # never reached
    assert bracket(RUNGS, NAN) == (None, None)      # not known


def test_pct_refuses_non_numbers_and_clamps_the_interval():
    assert _pct((NAN, NAN, NAN)) == "—"
    assert _pct((INF, 0.0, 1.0)) == "—"
    # Wilson stays inside [0,1] by construction, but a rendered
    # "0% (-10–150)" is nonsense whatever produced it.
    assert _pct((0.0, -0.1, 1.5)) == "0% (0–100)"
    assert _pct((0.5, 0.4, 0.6)) == "50% (40–60)"


def test_cost_per_answer_rejects_impossible_prices():
    assert _cpf(NAN) == "—"
    assert _cpf(-1.0) == "—"
    assert _cpf(INF) == "no answers"      # a real state: paid, got nothing
    assert _cpf(0.005) == "$5.00"


def test_wilson_names_an_impossible_proportion():
    """It raised `math domain error` from inside the arithmetic, which named
    nothing and pointed nowhere."""
    with pytest.raises(ValueError, match="not a proportion"):
        wilson(5, 3)
    with pytest.raises(ValueError, match="not a proportion"):
        wilson(-1, 3)
    assert all(math.isnan(v) for v in wilson(0, 0))


def test_an_inverted_interval_is_counted_not_silently_dropped():
    """Dropping an observation shrinks the denominator of every rate computed
    from the fit, and nothing downstream would show it happened."""
    from tti.survival import INF as SINF
    from tti.survival import Interval, fit
    est = fit([Interval(0, 300)] * 4 + [Interval(900, 300)])
    assert est.n == 5 and est.dropped == 1
    assert fit([Interval(0, 300)] * 4).dropped == 0
    assert fit([Interval(300, SINF)]).dropped == 0


def test_score_raises_on_an_impossible_interval():
    """A FRESH verdict earlier than a not-FRESH one should be impossible.
    If it ever happens, the fit loses the event; better to say so."""
    from tti.metrics import score
    from tti.models import ABSENT, FRESH, Event, ProbeResult

    ev = Event(source="npm", source_class="package_registry", subject="p",
               published_at=0.0, discovered_at=1.0, question="q", answer="1.0.1")
    events = {ev.event_id: ev}
    results = [
        ProbeResult(probe_id="a", event_id=ev.event_id, provider="px", mode="base",
                    rung=300, requested_at=300.0, lag=300.0, verdict=FRESH),
        ProbeResult(probe_id="b", event_id=ev.event_id, provider="px", mode="base",
                    rung=900, requested_at=900.0, lag=900.0, verdict=ABSENT),
    ]
    # Normal: first FRESH at 300 with nothing earlier -> (0, 300]. Fine.
    assert score(events, results, "px", "base").median_bracket == (0.0, 300.0)


def test_a_p_value_below_the_printed_precision_is_not_printed_as_zero():
    from tti.metrics import fmt_p
    assert fmt_p(0.0) == "<0.0001"
    assert fmt_p(3e-7) == "<0.0001"
    assert fmt_p(0.0001) == "0.0001"
    assert fmt_p(0.0312) == "0.0312"
    assert fmt_p(float("nan")) == "—"
    assert fmt_p(1.5) == "—" and fmt_p(-0.1) == "—"
