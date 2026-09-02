"""Which arm is asked first, and what clock each row carries."""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, scheduler
from tti.ledger import Ledger
from tti.models import Probe

ARMS = [("origin", "direct"), ("parallel", "advanced"), ("parallel", "fast"),
        ("exa", "auto"), ("tavily", "basic"), ("brave", "web"), ("serper", "search")]


def _due(n_events=24, rung=300):
    return [Probe(event_id=f"e{i:02d}", provider=p, mode=m, rung=rung, due_at=1000.0 + rung)
            for i in range(n_events) for (p, m) in ARMS]


def test_no_provider_is_always_asked_first_or_last():
    order = scheduler.dispatch_order(_due())
    firsts, lasts = [], []
    for i in range(24):
        group = [p for p in order if p.event_id == f"e{i:02d}"]
        assert group[0].provider == "origin"                 # the control leads each event
        firsts.append(group[1].provider + "/" + group[1].mode)
        lasts.append(group[-1].provider + "/" + group[-1].mode)
    assert len(set(firsts)) >= 4 and len(set(lasts)) >= 4    # not one arm every time


def test_the_order_is_a_function_of_the_ledger_not_of_the_run():
    a = [(p.event_id, p.provider, p.mode) for p in scheduler.dispatch_order(_due())]
    b = [(p.event_id, p.provider, p.mode) for p in scheduler.dispatch_order(list(reversed(_due())))]
    assert a == b


def test_due_time_still_comes_first():
    early = Probe(event_id="late-name", provider="serper", mode="search", rung=300, due_at=100.0)
    order = scheduler.dispatch_order(_due(3) + [early])
    assert order[0] is early


def test_each_row_carries_its_own_dispatch_time(tmp_path, monkeypatch, wired):
    """Seven arms take seconds to sweep; the last row should not claim the
    first row's clock."""
    now = time.time()
    wired.publish_npm("demo", [("1.0.0", now - 90_000), ("1.0.1", now - 400)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["demo"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 10 ** 6,
        "ladder": [300], "origin_control": True, "arms": [],
        "max_results": 5, "max_chars_per_result": 500,
        "max_rung_slip_seconds": 10 ** 9, "daily_usd_cap": 6.0})
    monkeypatch.setattr(scheduler.providers, "available_arms", lambda: [])
    led = Ledger(tmp_path)
    scheduler.discover(led, verbose=False)
    real_time = time.time
    ticks = iter([0.0, 2.5, 2.5, 2.5, 2.5, 2.5])
    monkeypatch.setattr(scheduler.time, "time", lambda: real_time() + next(ticks, 2.5))
    scheduler.run_due(led, now=now, verbose=False)
    rows = [r for r in led.results() if r.provider == "origin"]
    assert rows and all(abs(r.requested_at - (now + 2.5)) < 0.5 for r in rows)
