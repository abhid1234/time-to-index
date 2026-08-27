"""Clocks that disagree.

Every event's ladder is anchored to a timestamp the publisher wrote, not one
we observed. That is deliberate — it is the only clock that describes when
the fact entered the world — but it means the whole measurement inherits
whatever that clock says.

A publisher running a few seconds ahead is ordinary and harmless. One
running three days ahead anchors the ladder to a time that has not happened,
so every lag it produces describes nothing, and the event looks completely
normal on the way in.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti import config, scheduler
from tti.ledger import Ledger
from tti.models import Event, Probe

SETTINGS = {
    "sources": ["npm"], "max_detection_lag_seconds": 600,
    "max_clock_skew_seconds": 120, "ladder": [300, 900],
    "origin_control": False, "arms": [],
}


def source_of(offsets):
    """A collector whose events are published at now+offset."""
    now = time.time()

    class Src:
        name, source_class = "npm", "package_registry"
        errors, attempted, all_failed = [], len(offsets), False

        def collect(self, seen):
            return [Event(source="npm", source_class="package_registry",
                          subject=name, published_at=now + off,
                          discovered_at=now, question="q",
                          answer=f"{i}.0.1", predecessor=f"{i}.0.0")
                    for i, (name, off) in enumerate(offsets)]
    return Src()


def run(tmp_path, monkeypatch, offsets, settings=None):
    monkeypatch.setattr(scheduler.sources, "get",
                        lambda n: source_of(offsets))
    monkeypatch.setitem(config._cache, "settings", {**SETTINGS, **(settings or {})})
    led = Ledger(tmp_path)
    return led, scheduler.discover(led, verbose=False)


def test_ordinary_skew_is_accepted(tmp_path, monkeypatch):
    """A publisher a few seconds ahead of us is normal. Rejecting it would
    discard real events over nothing."""
    led, rep = run(tmp_path, monkeypatch, [("a", -30), ("b", 20), ("c", 100)])
    assert rep.new_events == 3 and rep.dropped_future == 0


def test_a_timestamp_far_in_the_future_is_dropped(tmp_path, monkeypatch):
    led, rep = run(tmp_path, monkeypatch, [("ok", -30), ("bad", 86_400 * 3)])
    assert rep.dropped_future == 1
    assert sorted(e.subject for e in led.events().values()) == ["ok"]


def test_the_boundary_is_the_configured_tolerance(tmp_path, monkeypatch):
    led, rep = run(tmp_path, monkeypatch, [("just-inside", 119), ("outside", 121)],
                   settings={"max_clock_skew_seconds": 120})
    assert rep.dropped_future == 1
    assert [e.subject for e in led.events().values()] == ["just-inside"]


def test_future_and_late_are_counted_separately(tmp_path, monkeypatch):
    """Different causes, different fixes. A late detection is our polling
    interval; a future timestamp is someone's clock."""
    led, rep = run(tmp_path, monkeypatch,
                   [("late", -5000), ("future", 86_400), ("ok", -10)])
    assert rep.dropped_late == 1
    assert rep.dropped_future == 1
    assert rep.new_events == 1


def test_a_zero_timestamp_is_not_treated_as_skew(tmp_path, monkeypatch):
    """published_at == 0 means the collector failed to parse a date, not
    that the fact was published in 1970."""
    monkeypatch.setattr(scheduler.sources, "get", lambda n: _ZeroSource())
    monkeypatch.setitem(config._cache, "settings", SETTINGS)
    led = Ledger(tmp_path)
    rep = scheduler.discover(led, verbose=False)
    assert rep.new_events == 0 and rep.dropped_late == 1


class _ZeroSource:
    name, source_class = "npm", "package_registry"
    errors, attempted, all_failed = [], 1, False

    def collect(self, seen):
        return [Event(source="npm", source_class="package_registry", subject="p",
                      published_at=0.0, discovered_at=time.time(), question="q",
                      answer="1.0.1")]


def test_a_probe_is_never_dispatched_before_its_event_was_published(tmp_path,
                                                                   monkeypatch):
    """The due-check is what makes a negative lag unreachable. If a clock
    correction moves time backwards mid-run, the probe simply is not due
    yet — it must not fire and record a negative elapsed time."""
    led = Ledger(tmp_path)
    now = time.time()
    ev = Event(source="npm", source_class="package_registry", subject="p",
               published_at=now + 3600, discovered_at=now + 3600, question="q",
               answer="1.0.1", predecessor="1.0.0")
    led.add_events([ev])
    led.add_probes([Probe(event_id=ev.event_id, provider="stub", mode="base",
                          rung=300, due_at=ev.published_at + 300)])

    class Stub:
        name = "stub"
        calls = 0
        def modes(self): return ["base"]
        def available(self): return True
        def search(self, *a, **k):
            Stub.calls += 1
            return {"results": []}

    monkeypatch.setattr(scheduler.providers, "get", lambda n: Stub())
    monkeypatch.setitem(config._cache, "settings", {
        "ladder": [300], "daily_usd_cap": 100.0, "max_results": 5,
        "max_chars_per_result": 500, "max_detection_lag_seconds": 10 ** 9,
        "max_rung_slip_seconds": 10 ** 9, "origin_control": False,
        "arms": [{"provider": "stub", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers", {"providers": {"stub": {"modes": {
        "base": {"usd_per_1k_requests": 1.0, "results_included": 5}}}}})

    rep = scheduler.run_due(led, now=now, verbose=False)
    assert rep.dispatched == 0 and Stub.calls == 0
    assert all(r.lag >= 0 for r in Ledger(tmp_path).results())


def test_skew_tolerance_is_validated_as_a_number():
    from tti.config import ConfigError, _validate_settings
    with pytest.raises(ConfigError, match="max_clock_skew_seconds"):
        _validate_settings("settings", {"ladder": [300], "daily_usd_cap": 1,
                                        "max_clock_skew_seconds": -5})
