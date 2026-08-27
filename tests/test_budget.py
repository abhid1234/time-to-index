"""Spend accounting.

The cap is the only thing standing between an unattended job and an
unbounded bill, so it has to be exactly right in both directions: it must
never let a successful call through once the day is spent, and it must never
refuse a call over money that was never billed.

The second half was wrong. A provider having a bad hour consumed the entire
daily budget without spending a cent, and healthy probes were refused behind
it — measured as ten probes against a cap affording five: five errors, five
refused, $0.00 actually spent.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti import config, scheduler
from tti.budget import Budget, BudgetExceeded, utc_day
from tti.ledger import Ledger
from tti.models import Event, Probe

SETTINGS = {
    "ladder": [300], "max_results": 5, "max_chars_per_result": 500,
    "max_detection_lag_seconds": 600, "max_rung_slip_seconds": 10 ** 9,
    "origin_control": False, "arms": [{"provider": "stub", "mode": "base"}],
}
PRICES = {"providers": {"stub": {"modes": {
    "base": {"usd_per_1k_requests": 1.0, "results_included": 5}}}}}
PER_CALL = 0.001


def seed(tmp_path, n=10):
    led = Ledger(tmp_path)
    now = time.time()
    evs = [Event(source="npm", source_class="package_registry", subject=f"p{i}",
                 published_at=now - 400, discovered_at=now - 390, question="q",
                 answer=f"1.0.{i}", predecessor=f"0.9.{i}") for i in range(n)]
    led.add_events(evs)
    led.add_probes([Probe(event_id=e.event_id, provider="stub", mode="base",
                          rung=300, due_at=e.published_at + 300) for e in evs])
    return led


def wire(monkeypatch, cap, behaviour):
    class Stub:
        name = "stub"
        calls = 0
        def modes(self): return ["base"]
        def available(self): return True
        def search(self, q, m, *, max_results, max_chars):
            Stub.calls += 1
            return behaviour()

    monkeypatch.setattr(scheduler.providers, "get", lambda n: Stub())
    monkeypatch.setitem(config._cache, "settings", {**SETTINGS, "daily_usd_cap": cap})
    monkeypatch.setitem(config._cache, "providers", PRICES)
    return Stub


def ok():
    return {"results": [{"snippet": "nothing relevant"}]}


def boom():
    raise RuntimeError("provider 503")


# ---------------------------------------------------------------------------
# The cap must hold
# ---------------------------------------------------------------------------

def test_successful_calls_stop_at_the_cap(tmp_path, monkeypatch):
    """The refund path must not become a loophole."""
    seed(tmp_path, 10)
    Stub = wire(monkeypatch, cap=5 * PER_CALL, behaviour=ok)
    rep = scheduler.run_due(Ledger(tmp_path), verbose=False)
    assert Stub.calls == 5
    assert rep.dispatched == 5 and rep.skipped_budget == 5
    assert rep.spend_usd == pytest.approx(5 * PER_CALL)
    assert rep.refunded_usd == 0.0


def test_a_refusal_is_recorded_with_its_reason(tmp_path, monkeypatch):
    seed(tmp_path, 3)
    wire(monkeypatch, cap=1 * PER_CALL, behaviour=ok)
    scheduler.run_due(Ledger(tmp_path), verbose=False)
    refused = [r for r in Ledger(tmp_path).results() if r.verdict == "SKIPPED"]
    assert len(refused) == 2
    assert all("budget" in r.note for r in refused)


# ---------------------------------------------------------------------------
# ...but only over money that was actually billed
# ---------------------------------------------------------------------------

def test_failed_calls_do_not_consume_the_cap(tmp_path, monkeypatch):
    """Ten probes, a cap affording five, every call failing. Before the
    refund: five errors and five refused. A provider having a bad hour used
    to stop the whole day's collection for free."""
    seed(tmp_path, 10)
    Stub = wire(monkeypatch, cap=5 * PER_CALL, behaviour=boom)
    rep = scheduler.run_due(Ledger(tmp_path), verbose=False)
    assert Stub.calls == 10, "every probe should have been attempted"
    assert rep.errors == 10
    assert rep.skipped_budget == 0
    assert rep.spend_usd == 0.0
    assert rep.refunded_usd == pytest.approx(10 * PER_CALL)
    assert sum(r.cost_usd for r in Ledger(tmp_path).results()) == 0.0


def test_a_mix_of_failures_and_successes_charges_only_the_successes(tmp_path,
                                                                    monkeypatch):
    seed(tmp_path, 8)
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] % 2:
            raise RuntimeError("503")
        return ok()

    wire(monkeypatch, cap=100.0, behaviour=flaky)
    rep = scheduler.run_due(Ledger(tmp_path), verbose=False)
    assert rep.errors == 4
    assert rep.spend_usd == pytest.approx(4 * PER_CALL)
    assert rep.refunded_usd == pytest.approx(4 * PER_CALL)


# ---------------------------------------------------------------------------
# Budget object
# ---------------------------------------------------------------------------

def test_refund_is_clamped_at_zero():
    b = Budget(cap_usd=1.0, spent_today=0.10)
    b.refund(5.0)
    assert b.spent == 0.0 and b.refunded == 5.0


def test_charge_refuses_past_the_cap():
    b = Budget(cap_usd=0.010)
    for _ in range(10):
        b.charge(0.001)
    with pytest.raises(BudgetExceeded, match="daily cap"):
        b.charge(0.001)


def test_rolling_to_a_new_day_resets_the_tally():
    """A run that starts at 23:50 with the day nearly exhausted must not keep
    refusing after midnight, against a cap that has already reset."""
    b = Budget(cap_usd=1.0, spent_today=0.99, day="2026-08-26")
    assert not b.can_afford(0.05)
    b.roll_to("2026-08-27", 0.0)
    assert b.can_afford(0.05)
    assert b.day == "2026-08-27"


def test_rolling_to_the_same_day_is_a_no_op():
    b = Budget(cap_usd=1.0, spent_today=0.40, day="2026-08-26")
    b.roll_to("2026-08-26", 0.0)
    assert b.spent == 0.40


def test_utc_day_is_utc_not_local():
    """Two runs on different machines must agree on which day it is."""
    import datetime as dt
    ts = dt.datetime(2026, 8, 27, 3, 30, tzinfo=dt.timezone.utc).timestamp()
    assert utc_day(ts) == "2026-08-27"


def test_the_control_arm_is_never_refused_by_the_cap(tmp_path, monkeypatch):
    """It is a plain HTTP GET and costs nothing. Losing it would make every
    ABSENT from every paid provider ambiguous, which is the worst possible
    economy."""
    from tti.budget import unit_cost
    seed(tmp_path, 2)
    wire(monkeypatch, cap=0.0000001, behaviour=ok)
    b = Budget(cap_usd=0.0000001, spent_today=0.0)
    assert b.can_afford(0.0)          # the control's cost
    assert unit_cost("stub", "base", 5) > 0
