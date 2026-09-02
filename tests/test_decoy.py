"""The instrument measuring its own false-positive rate.

Every recall number rests on the assumption that a FRESH verdict means the
provider really surfaced the new fact. These tests attack that assumption from
both sides it can fail: a grader that matches version-shaped noise, and a
provider that invents a plausible version.

The load-bearing test is `test_a_provider_that_invents_a_version_is_caught`.
If that one passes for the wrong reason, the whole check is decorative.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, decoy
from tti.cli import main
from tti.ledger import Ledger
from tti.models import Event


def an_event(answer="1.4.2", predecessor="1.4.1", subject="pkg") -> Event:
    return Event(source="npm", source_class="package_registry", subject=subject,
                 published_at=1000.0, discovered_at=1005.0,
                 question=f"what is the latest version of {subject}?",
                 answer=answer, predecessor=predecessor)


# ---------------------------------------------------------------------------
# Minting a counterfactual
# ---------------------------------------------------------------------------

def test_the_counterfactual_has_the_same_shape_as_the_real_answer():
    """A decoy that does not look like a real answer measures the decoy. The
    grader would decline it for the wrong reason and the false-positive rate
    would be an artifact of the decoy's weirdness."""
    assert decoy.mint(an_event("1.4.2")) == "1.4.9"
    assert decoy.mint(an_event("15.4.10")) == "15.4.17"
    assert decoy.mint(an_event("0.0.1")) == "0.0.8"


def test_minting_is_deterministic():
    """Two people running this on the same ledger must get the same number,
    or it is not a measurement."""
    e = an_event("2.3.4")
    assert decoy.mint(e) == decoy.mint(e) == decoy.mint(an_event("2.3.4"))


def test_a_non_semver_answer_is_refused_rather_than_guessed():
    for bad in ("2026-08-31", "v-next", "10-Q", "abc"):
        with pytest.raises(decoy.Undecoyable):
            decoy.mint(an_event(bad))


def test_a_counterfactual_colliding_with_a_declared_alias_is_refused():
    e = an_event("1.4.2")
    e.answer_aliases.append("1.4.9")
    with pytest.raises(decoy.Undecoyable, match="already an alias"):
        decoy.mint(e)


def test_the_decoy_event_drops_the_real_aliases():
    """Carrying them over would let a payload match the *true* answer through
    an alias and be scored as a false positive."""
    e = an_event("1.4.2")
    e.answer_aliases.append("v1.4.2")
    d = decoy.as_decoy_event(e, "1.4.9")
    assert d.answer_aliases == ["1.4.9"]
    assert d.predecessor is None and d.predecessor_aliases == []
    assert d.subject == e.subject and d.question == e.question


# ---------------------------------------------------------------------------
# The measurement, end to end through a real collected run
# ---------------------------------------------------------------------------

def _collect(wired, tmp_path, monkeypatch, answers: dict[int, str]):
    """A real run: discover from the fixture registry, probe a stub provider
    whose text we control, store payloads."""
    from tti import scheduler

    now = time.time()
    wired.publish_npm("demo", [("9.9.8", now - 90_000), ("9.9.9", now - 5)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["demo"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300], "origin_control": False,
        "max_results": 5, "max_chars_per_result": 500,
        "max_rung_slip_seconds": 10 ** 9, "daily_usd_cap": 100.0,
        "arms": [{"provider": "stub", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers", {"providers": {"stub": {"modes": {
        "base": {"usd_per_1k_requests": 1.0, "results_included": 5}}}}})
    monkeypatch.setattr(scheduler.providers, "available_arms",
                        lambda: [("stub", "base")])

    from tests.test_integration import _stub_provider
    led = Ledger(tmp_path)
    scheduler.discover(led, verbose=False)
    ev = next(iter(led.events().values()))
    Stub = _stub_provider(monkeypatch, answers)
    Stub._rung = 300
    scheduler.run_due(led, now=ev.published_at + 300, verbose=False)
    return led, ev


def test_a_clean_payload_produces_no_false_positive(wired, tmp_path, monkeypatch):
    led, ev = _collect(wired, tmp_path, monkeypatch, {300: "the latest is 9.9.9"})
    rep = decoy.run(led, verify_absent=None, verbose=False)
    assert rep.events_decoyed == 1
    assert [a.hits for a in rep.arms] == [0]
    assert [a.graded for a in rep.arms] == [1]


def test_a_provider_that_invents_a_version_is_caught(wired, tmp_path, monkeypatch):
    """The whole point. The stub answers with a version that was never
    published — exactly what a generative answer layer does when it fills a
    gap — and the pipeline must notice it graded that as a hit."""
    led, ev = _collect(wired, tmp_path, monkeypatch,
                       {300: "the latest release is 9.9.16"})
    assert decoy.mint(ev) == "9.9.16", "fixture must match the minted decoy"

    rep = decoy.run(led, verify_absent=None, verbose=False)
    arm = rep.arms[0]
    assert (arm.graded, arm.hits) == (1, 1)
    assert arm.rate == 1.0
    subject, token, matched = arm.examples[0]
    assert token == "9.9.16" and subject == "demo"


def test_a_counterfactual_that_turns_out_to_exist_is_dropped(wired, tmp_path, monkeypatch):
    """A fixed offset will occasionally land on a real release. Grading
    against it would count true retrieval as a false positive, so it is
    dropped — and the drop is counted, not silent."""
    led, _ = _collect(wired, tmp_path, monkeypatch, {300: "the latest is 9.9.16"})
    rep = decoy.run(led, verify_absent=lambda ev, tok: False, verbose=False)
    assert rep.events_decoyed == 0
    assert rep.skip_reasons["counterfactual actually exists"] == 1
    assert not rep.any_graded


def test_an_unverifiable_counterfactual_is_used_but_counted_separately(
        wired, tmp_path, monkeypatch):
    """Weaker evidence than a verified one. Pretending otherwise would
    overstate the check that exists to keep us honest."""
    led, _ = _collect(wired, tmp_path, monkeypatch, {300: "the latest is 9.9.9"})
    rep = decoy.run(led, verify_absent=lambda ev, tok: None, verbose=False)
    assert rep.events_decoyed == 1 and rep.unverified == 1


def test_events_with_no_semver_answer_are_skipped_with_a_reason(tmp_path):
    led = Ledger(tmp_path)
    led.add_events([an_event("2026-08-31", subject="apple-10-Q")])
    rep = decoy.run(led, verify_absent=None, verbose=False)
    assert rep.events_decoyed == 0 and rep.events_skipped == 1
    assert rep.skip_reasons


# ---------------------------------------------------------------------------
# Through the CLI
# ---------------------------------------------------------------------------

def test_decoy_reports_a_rate_with_an_interval(wired, tmp_path, monkeypatch, capsys):
    _collect(wired, tmp_path, monkeypatch, {300: "the latest release is 9.9.16"})
    assert main(["--run-dir", str(tmp_path), "decoy", "--no-verify"]) == 0
    out = capsys.readouterr().out
    assert "false positives" in out
    assert "9.9.16" in out
    assert "never published" in out


def test_decoy_json_carries_the_interval_and_the_examples(
        wired, tmp_path, monkeypatch, capsys):
    _collect(wired, tmp_path, monkeypatch, {300: "the latest release is 9.9.16"})
    assert main(["--run-dir", str(tmp_path), "decoy", "--no-verify", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    arm = payload["arms"][0]
    assert arm["graded"] == 1 and arm["false_positives"] == 1
    assert arm["rate"] == 1.0
    assert arm["rate_ci"]["low"] is not None
    assert arm["examples"][0]["counterfactual"] == "9.9.16"


def test_zero_observed_false_positives_still_reports_a_nonzero_upper_bound(
        wired, tmp_path, monkeypatch, capsys):
    """The number that would be wrong to print is 0%. With one payload the
    honest upper bound is enormous, and the interval is what says so."""
    _collect(wired, tmp_path, monkeypatch, {300: "the latest is 9.9.9"})
    assert main(["--run-dir", str(tmp_path), "decoy", "--no-verify"]) == 0
    out = capsys.readouterr().out
    assert "No false positive was observed. That is not a 0% rate" in out
    assert "stub/base: up to 79% of its FRESH verdicts could be spurious." in out


def test_decoy_on_an_empty_ledger_says_so_rather_than_reporting_zero(tmp_path, capsys):
    assert main(["--run-dir", str(tmp_path), "decoy", "--no-verify"]) == 1
    assert "nothing to re-grade" in capsys.readouterr().out


def test_decoy_makes_no_provider_calls(wired, tmp_path, monkeypatch):
    """The property that makes this worth running on every published number:
    it costs nothing, so there is no budget argument for skipping it."""
    _collect(wired, tmp_path, monkeypatch, {300: "the latest is 9.9.9"})
    led = Ledger(tmp_path)
    spent_before = sum(r.cost_usd for r in led.results())

    from tti import providers as prov

    def refuse(*a, **kw):
        raise AssertionError("decoy dispatched a provider call")
    monkeypatch.setattr(prov, "get", refuse)

    decoy.run(led, verify_absent=None, verbose=False)
    assert sum(r.cost_usd for r in Ledger(tmp_path).results()) == spent_before


def test_a_synthetic_ledger_never_asks_a_registry(tmp_path, monkeypatch, capsys):
    """The demo's subjects exist nowhere. Verifying a counterfactual against
    npm for them is a network call to confirm something known by
    construction, and the demo now carries payloads so `tti decoy` on it is
    a thing people will do."""
    from tti import demo

    def boom(*a, **k):
        raise AssertionError("registry was asked on a synthetic ledger")
    monkeypatch.setattr(decoy, "npm_absent", boom)
    demo.generate(tmp_path, config.ladder())
    assert main(["--run-dir", str(tmp_path), "decoy"]) == 0
    out = capsys.readouterr().out
    assert "synthetic run" in out and "payloads re-graded" in out
    assert main(["--run-dir", str(tmp_path), "decoy", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["events_decoyed"] == 106 and payload["unverified_counterfactuals"] == 0
