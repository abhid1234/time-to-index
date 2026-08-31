"""Correcting for the number of comparisons a leaderboard invites.

The tests that matter are the ones where the correction changes the answer. A
multiplicity procedure that never flips a verdict is not being exercised — and
this repository shipped fifteen uncorrected pairwise tests, so the flip is
exactly the behaviour that was missing.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti.multiplicity import family_error_rate, holm, note


def adj(pairs):
    return {a.label: a.adjusted for a in holm(pairs)}


# ---------------------------------------------------------------------------
# The procedure itself
# ---------------------------------------------------------------------------

def test_holm_matches_the_textbook_worked_example():
    """The canonical five-p-value example. Every raw value is under 0.05 and
    not one survives the correction — which is the entire point."""
    got = holm([("a", 0.01), ("b", 0.02), ("c", 0.03), ("d", 0.04), ("e", 0.05)])
    expected = {"a": 0.05, "b": 0.08, "c": 0.09, "d": 0.09, "e": 0.09}
    for x in got:
        assert abs(x.adjusted - expected[x.label]) < 1e-12, (x.label, x.adjusted)
    assert not any(x.significant() for x in got)


def test_a_single_comparison_is_left_alone():
    """With a family of one there is no multiplicity, and inflating the only
    p-value would cost power for nothing."""
    out = holm([("solo", 0.03)])
    assert out[0].adjusted == 0.03 and out[0].significant()


def test_adjusted_values_never_decrease_with_the_raw_ordering():
    """The step-down's running maximum. Without it an adjusted value could
    come out below one for a *more* significant raw p-value, violating the
    ordering the whole procedure is built on."""
    out = sorted(holm([("a", 0.001), ("b", 0.04), ("c", 0.045), ("d", 0.9)]),
                 key=lambda x: x.raw)
    seq = [x.adjusted for x in out]
    assert seq == sorted(seq), seq


def test_holm_is_never_more_conservative_than_bonferroni():
    ps = [("a", 0.001), ("b", 0.006), ("c", 0.02), ("d", 0.3)]
    m = len(ps)
    for x in holm(ps):
        assert x.adjusted <= min(1.0, m * x.raw) + 1e-12


def test_adjusted_values_are_capped_at_one():
    assert all(x.adjusted <= 1.0 for x in holm([("a", 0.6), ("b", 0.7), ("c", 0.9)]))


def test_input_order_is_preserved():
    labels = [x.label for x in holm([("z", 0.9), ("a", 0.001), ("m", 0.4)])]
    assert labels == ["z", "a", "m"]


def test_an_uncomputable_comparison_does_not_penalise_the_others():
    """A NaN p-value means the comparison could not be evaluated — too few
    events, an arm with nothing in it. Counting it as a test would shrink
    everyone else's adjusted value for a test that was never run."""
    with_nan = adj([("a", 0.01), ("b", 0.02), ("bad", float("nan"))])
    without = adj([("a", 0.01), ("b", 0.02)])
    assert math.isnan(with_nan["bad"])
    assert with_nan["a"] == without["a"]
    assert with_nan["b"] == without["b"]


def test_an_all_nan_family_produces_no_numbers_rather_than_zeroes():
    out = holm([("a", float("nan")), ("b", float("nan"))])
    assert all(math.isnan(x.adjusted) for x in out)
    assert not any(x.significant() for x in out)


def test_the_empty_family_is_not_an_error():
    assert holm([]) == []


# ---------------------------------------------------------------------------
# The number that makes the argument
# ---------------------------------------------------------------------------

def test_the_family_error_rate_for_six_arms():
    """Six arms make fifteen pairwise comparisons. This is the number the
    uncorrected code was implicitly accepting."""
    assert round(family_error_rate(15), 2) == 0.54
    assert family_error_rate(1) == pytest.approx(0.05)
    assert family_error_rate(0) == 0.0


def test_the_note_is_silent_for_a_family_of_one():
    assert note(1) == "" and note(0) == ""
    assert "54%" in note(15)


# ---------------------------------------------------------------------------
# Where it bites: the verdict changes
# ---------------------------------------------------------------------------

def test_the_correction_flips_a_borderline_verdict_in_power():
    """The regression this whole module exists for. A p-value of 0.03 across
    fifteen comparisons is not evidence of anything, and the old code called
    it `distinguishable`."""
    from tti.metrics import Observation
    from tti.power import analyse

    a = [Observation(float(i), True) for i in range(1, 40)]
    b = [Observation(float(i) * 2, True) for i in range(1, 40)]

    raw_only = analyse("a/x", a, "b/y", b, 0.03)
    assert raw_only.verdict == "distinguishable"

    corrected = analyse("a/x", a, "b/y", b, 0.03, p_adjusted=0.45)
    assert corrected.verdict != "distinguishable"


def test_analyse_falls_back_to_the_raw_value_when_there_is_no_family():
    """`analyse` is also called for one pair on its own, where inventing a
    correction would be wrong."""
    from tti.metrics import Observation
    from tti.power import analyse

    a = [Observation(float(i), True) for i in range(1, 30)]
    b = [Observation(float(i) * 3, True) for i in range(1, 30)]
    r = analyse("a/x", a, "b/y", b, 0.001)
    assert math.isnan(r.p_adjusted)
    assert r.verdict == "distinguishable"


def test_power_json_and_text_agree_on_every_verdict(tmp_path, capsys):
    """There were two copies of the pairwise loop — the JSON branch and the
    text branch — and a correction applied to one would have produced two
    different verdicts for the same data depending on which flag was passed."""
    from tti import demo
    from tti.cli import main

    demo.generate(tmp_path, [300, 900, 3600, 21600, 86400, 259200])

    assert main(["--run-dir", str(tmp_path), "power", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    from_json = {(c["a"], c["b"]): c["verdict"] for c in payload["comparisons"]}

    assert main(["--run-dir", str(tmp_path), "power"]) == 0
    text = capsys.readouterr().out
    for (a, b), verdict in from_json.items():
        line = next(ln for ln in text.splitlines() if f"{a} vs {b}" in ln)
        assert verdict in line, (a, b, verdict, line)

    assert payload["multiplicity"]["method"] == "holm-bonferroni"
    assert payload["multiplicity"]["comparisons"] == len(from_json)


def test_power_json_reports_both_the_raw_and_the_adjusted_value(tmp_path, capsys):
    """Both, not just the adjusted one. A reader recomputing the correction
    needs the input, and hiding the raw value would make the adjustment
    unauditable."""
    from tti import demo
    from tti.cli import main

    demo.generate(tmp_path, [300, 900, 3600, 21600, 86400, 259200])
    assert main(["--run-dir", str(tmp_path), "power", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    for c in payload["comparisons"]:
        assert "p_value" in c and "p_value_adjusted" in c
        if c["p_value"] is not None and c["p_value_adjusted"] is not None:
            assert c["p_value_adjusted"] >= c["p_value"] - 1e-12


def test_the_dashboard_shows_the_adjusted_column_and_says_why(tmp_path):
    from tti import demo
    from tti.cli import main

    demo.generate(tmp_path, [300, 900, 3600, 21600, 86400, 259200])
    out_dir = tmp_path / "site"
    out_dir.mkdir()
    assert main(["--run-dir", str(tmp_path), "report", "--out-dir", str(out_dir)]) == 0

    page = (out_dir / "index.html").read_text()
    assert "Holm" in page
    assert "p adjusted" in page
    assert "the adjusted column is the one to read" in page
    assert "The <b>read</b> column uses the adjusted value." in page
