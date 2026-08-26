"""End-to-end: discovery -> ladder -> grading -> survival estimate.

Runs against a scripted provider that indexes on a known schedule, so the
test can assert that the pipeline recovers a latency it was never told.
No network, no keys.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti import config, scheduler
from tti.ledger import Ledger
from tti.metrics import score
from tti.models import FRESH, SKIPPED, STALE, Event


class Clock:
    """Virtual time, so a 72-hour ladder can be exercised in milliseconds."""

    def __init__(self, t: float):
        self.t = t

    def set(self, t: float) -> float:
        self.t = t
        return t


class ScriptedProvider:
    """Returns the superseded answer until `indexes_after` seconds have passed
    since publication, then the new one. That is the exact shape of the
    failure the benchmark is built to catch, and driving it from a virtual
    clock lets the test assert a latency the pipeline was never told."""

    name = "scripted"

    def __init__(self, indexes_after: float, published_at: float, clock: "Clock"):
        self.indexes_after = indexes_after
        self.published_at = published_at
        self.clock = clock
        self.calls = 0

    def modes(self): return ["base"]
    def available(self): return True

    def search(self, question, mode, *, max_results, max_chars):
        self.calls += 1
        lag = self.clock.t - self.published_at
        answer = "9.9.9" if lag >= self.indexes_after else "9.9.8"
        return {"results": [{"url": "https://example.test/x", "title": "pkg",
                             "snippet": f"current release is {answer}"}]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    led = Ledger(tmp_path)
    published = time.time() - 100_000        # published ~28h ago
    ev = Event(source="npm", source_class="package_registry", subject="pkg",
               published_at=published, discovered_at=published + 10,
               question="What is the current latest published version of the npm package pkg?",
               answer="9.9.9", predecessor="9.9.8")
    led.add_events([ev])
    return led, ev, published


def _queue(led, ev, arms, ladder):
    from tti.models import Probe
    led.add_probes([Probe(event_id=ev.event_id, provider=p, mode=m, rung=r,
                          due_at=ev.published_at + r)
                    for p, m in arms for r in ladder])


def test_pipeline_recovers_the_indexing_latency(env, monkeypatch):
    led, ev, published = env
    ladder = [300, 900, 3600, 21600, 86400]
    clock = Clock(published)
    # Provider indexes 1 hour after publication. The ladder brackets that
    # between the 15-minute and 1-hour rungs.
    prov = ScriptedProvider(indexes_after=3600, published_at=published, clock=clock)
    monkeypatch.setattr(scheduler.providers, "get", lambda name: prov)
    monkeypatch.setitem(config._cache, "settings", {
        "ladder": ladder,
        "daily_usd_cap": 100.0, "max_results": 5, "max_chars_per_result": 500,
        "max_detection_lag_seconds": 600, "max_rung_slip_seconds": 600,
        "arms": [{"provider": "scripted", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers",
                        {"providers": {"scripted": {"modes": {"base": {
                            "usd_per_1k_requests": 1.0, "results_included": 5}}}}})

    _queue(led, ev, [("scripted", "base")], ladder)
    # Walk the ladder: each rung fires at its own due time, exactly as cron
    # would, so the recorded lag is the rung and not the wall clock.
    for rung in ladder:
        scheduler.run_due(led, now=clock.set(published + rung), verbose=False)

    results = {r.rung: r for r in led.results()}
    # Every rung before indexing must read STALE, not ABSENT: the provider was
    # returning a real, confident, wrong answer the whole time.
    assert results[300].verdict == STALE
    assert results[900].verdict == STALE
    assert results[3600].verdict == FRESH
    # Once FRESH, later rungs are skipped rather than paid for.
    assert results[21600].verdict == SKIPPED
    assert "carry-forward" in results[21600].note
    assert results[86400].verdict == SKIPPED

    sc = score(led.events(), led.results(), "scripted", "base")
    assert sc.n_events == 1 and sc.n_indexed == 1
    assert sc.curve.times[0] == pytest.approx(3600, abs=60)
    # Two stale opportunities out of two non-fresh probes.
    assert sc.n_stale == 2 and sc.n_stale_eligible == 2
    assert sc.staleness[0] == 1.0
    # Three paid calls: two stale rungs plus the fresh one. Skips cost nothing.
    assert prov.calls == 3
    assert sc.spend_usd == pytest.approx(0.003)


def test_budget_cap_refuses_rather_than_truncating(env, monkeypatch):
    led, ev, published = env
    clock = Clock(published)
    prov = ScriptedProvider(indexes_after=1e9, published_at=published, clock=clock)
    monkeypatch.setattr(scheduler.providers, "get", lambda name: prov)
    monkeypatch.setitem(config._cache, "settings", {
        "ladder": [300, 900, 3600], "daily_usd_cap": 0.002,   # affords 2 of 3
        "max_results": 5, "max_chars_per_result": 500,
        "max_detection_lag_seconds": 600, "max_rung_slip_seconds": 1e12,
        "arms": [{"provider": "scripted", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers",
                        {"providers": {"scripted": {"modes": {"base": {
                            "usd_per_1k_requests": 1.0, "results_included": 5}}}}})
    _queue(led, ev, [("scripted", "base")], [300, 900, 3600])
    rep = scheduler.run_due(led, now=clock.set(published + 3600), verbose=False)

    assert rep.dispatched == 2 and rep.skipped_budget == 1
    refused = [r for r in led.results() if r.verdict == SKIPPED]
    # The refusal is in the ledger with a reason. A cap that silently stops
    # probing is indistinguishable from a provider that silently stopped
    # indexing, and that is the one confusion this project cannot afford.
    assert len(refused) == 1 and "budget" in refused[0].note
    sc = score(led.events(), led.results(), "scripted", "base")
    assert sc.n_skipped_budget == 1
    assert sc.n_calls == 2      # refused probes are excluded from every rate


def test_rung_slip_is_dropped_not_misrecorded(env, monkeypatch):
    led, ev, published = env
    clock = Clock(published)
    prov = ScriptedProvider(indexes_after=1e9, published_at=published, clock=clock)
    monkeypatch.setattr(scheduler.providers, "get", lambda name: prov)
    monkeypatch.setitem(config._cache, "settings", {
        "ladder": [300], "daily_usd_cap": 100.0, "max_results": 5,
        "max_chars_per_result": 500, "max_detection_lag_seconds": 600,
        "max_rung_slip_seconds": 600,        # the probe is ~27h late
        "arms": [{"provider": "scripted", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers",
                        {"providers": {"scripted": {"modes": {"base": {
                            "usd_per_1k_requests": 1.0, "results_included": 5}}}}})
    _queue(led, ev, [("scripted", "base")], [300])
    rep = scheduler.run_due(led, verbose=False)
    assert rep.dispatched == 0 and rep.dropped_slip == 1
    assert prov.calls == 0
    assert "rung slip" in led.results()[0].note


def test_discover_drops_events_detected_too_late(tmp_path, monkeypatch):
    """A release we noticed 40 minutes after it shipped cannot be probed at
    the 5-minute rung, so it is dropped rather than recorded at a lag we
    caused ourselves."""
    led = Ledger(tmp_path)
    now = time.time()

    class LateSource:
        name, source_class = "late", "package_registry"
        errors, attempted, all_failed = [], 1, False
        def collect(self, seen):
            return [Event(source="late", source_class="package_registry", subject="p",
                          published_at=now - 2400, discovered_at=now,
                          question="q", answer="1.0.1", predecessor="1.0.0")]

    monkeypatch.setattr(scheduler.sources, "get", lambda n: LateSource())
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["late"], "max_detection_lag_seconds": 600, "ladder": [300],
        "arms": []})
    rep = scheduler.discover(led, verbose=False)
    assert rep.collected == 1 and rep.new_events == 0 and rep.dropped_late == 1


def test_demo_estimator_recovers_its_own_ground_truth(tmp_path):
    """The synthetic run is only worth shipping if it is a check.

    The generator draws each arm's indexing latency from a known
    distribution; the estimator sees only rung verdicts. If the recovered
    bracket does not contain the true median, the statistics are wrong and
    no number this repo publishes about a real vendor can be trusted.
    """
    from tti import demo
    from tti.metrics import score

    ladder = [300, 900, 3600, 21600, 86400, 259200]
    led, truth = demo.generate(tmp_path, ladder)
    events, results = led.events(), led.results()
    for provider, mode, *_ in demo.PROFILES:
        sc = score(events, results, provider, mode)
        actual = demo.true_median(truth[f"{provider}/{mode}"])
        lo, hi = sc.median_bracket
        assert (lo or 0) < actual <= (hi if hi is not None else float("inf")), (
            f"{provider}/{mode}: true median {actual:.0f}s outside "
            f"recovered bracket ({lo}, {hi}]")


def test_bracket_never_claims_more_precision_than_the_ladder():
    from tti.metrics import bracket, fmt_bracket
    rungs = [300, 900, 3600]
    assert bracket(rungs, 900.0) == (300.0, 900.0)     # seen at 15m => (5m, 15m]
    assert bracket(rungs, 300.0) == (0.0, 300.0)       # already indexed by 5m
    assert bracket(rungs, None) == (3600.0, None)      # never crossed 50%
    assert fmt_bracket(rungs, 300.0).startswith("≤")
    assert fmt_bracket(rungs, None).startswith(">")
