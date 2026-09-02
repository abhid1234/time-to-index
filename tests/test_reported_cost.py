"""Recording the vendor's stated charge instead of a list price.

The list price is this repository's reading of a page that changes. Exa's
table here was 29% low for a week. Where the response says what was charged,
that is the better evidence, and the cap must never understate it.
"""
from __future__ import annotations

import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, scheduler
from tti.budget import Budget, BudgetExceeded
from tti.ledger import Ledger


def _wire(wired, tmp_path, monkeypatch, provider_cls, price_per_1k=1.0, cap=100.0):
    now = time.time()
    wired.publish_npm("demo", [("9.9.8", now - 90_000), ("9.9.9", now - 5)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["demo"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300], "origin_control": False,
        "max_results": 5, "max_chars_per_result": 500,
        "max_rung_slip_seconds": 10 ** 9, "daily_usd_cap": cap,
        "arms": [{"provider": "stub", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers", {"providers": {"stub": {"modes": {
        "base": {"usd_per_1k_requests": price_per_1k, "results_included": 5}}}}})
    monkeypatch.setattr(scheduler.providers, "available_arms", lambda: [("stub", "base")])
    inst = provider_cls()
    real_get = scheduler.providers.get
    monkeypatch.setattr(scheduler.providers, "get",
                        lambda n: inst if n == "stub" else real_get(n))
    led = Ledger(tmp_path)
    scheduler.discover(led, verbose=False)
    ev = next(iter(led.events().values()))
    return led, ev


class _ListOnly:
    name = "stub"
    def modes(self): return ["base"]
    def available(self): return True
    def search(self, q, mode, *, max_results, max_chars):
        return {"results": [{"text": "now at 9.9.9"}]}


class _Reports(_ListOnly):
    def __init__(self, total): self.total = total
    def search(self, q, mode, *, max_results, max_chars):
        return {"results": [{"text": "now at 9.9.9"}],
                "costDollars": {"total": self.total}}
    @staticmethod
    def reported_cost(payload):
        t = (payload.get("costDollars") or {}).get("total")
        return float(t) if isinstance(t, (int, float)) else None


def test_a_provider_without_the_hook_is_priced_from_the_list(wired, tmp_path, monkeypatch):
    led, ev = _wire(wired, tmp_path, monkeypatch, _ListOnly, price_per_1k=1.0)
    scheduler.run_due(led, now=ev.published_at + 300, verbose=False)
    r, = led.results()
    assert r.cost_usd == pytest.approx(0.001)
    assert r.cost_source == "list"
    assert "cost:" not in r.note


def test_a_reported_charge_replaces_the_list_price(wired, tmp_path, monkeypatch):
    led, ev = _wire(wired, tmp_path, monkeypatch, lambda: _Reports(0.007), price_per_1k=5.0)
    rep = scheduler.run_due(led, now=ev.published_at + 300, verbose=False)
    r, = led.results()
    assert r.cost_usd == pytest.approx(0.007)
    assert r.cost_source == "reported"
    assert rep.spend_usd == pytest.approx(0.007)
    # 0.007 vs list 0.005 is a 40% gap: under the note threshold.
    assert "cost:" not in r.note


def test_a_large_disagreement_is_written_on_the_result(wired, tmp_path, monkeypatch):
    """List says $0.001, vendor says $0.007. The cost column is now right
    and the note says the table is not."""
    led, ev = _wire(wired, tmp_path, monkeypatch, lambda: _Reports(0.007), price_per_1k=1.0)
    scheduler.run_due(led, now=ev.published_at + 300, verbose=False)
    r, = led.results()
    assert r.cost_usd == pytest.approx(0.007)
    assert "cost: reported $0.0070 vs list $0.0010" in r.note


def test_settlement_over_the_cap_is_recorded_not_refused():
    """The call happened. The vendor billed it. A cap that refuses to record
    money already spent is understating spend, which is the one thing it
    must never do."""
    b = Budget(cap_usd=0.010, spent_today=0.0)
    b.charge(0.005)                 # dispatch gate: fine
    b.settle(0.005, 0.020)          # vendor charged four times the estimate
    assert b.spent == pytest.approx(0.020)
    assert b.reconciled_delta == pytest.approx(0.015)
    assert b.settled == 1
    with pytest.raises(BudgetExceeded):
        b.charge(0.001)             # and the next dispatch is now refused


def test_settlement_below_the_estimate_frees_budget():
    b = Budget(cap_usd=1.0, spent_today=0.0)
    b.charge(0.010)
    b.settle(0.010, 0.004)
    assert b.spent == pytest.approx(0.004)
    assert b.reconciled_delta == pytest.approx(-0.006)


def test_a_failed_call_still_refunds_the_estimate_and_reports_nothing(wired, tmp_path, monkeypatch):
    class Boom(_Reports):
        def search(self, *a, **kw): raise RuntimeError("503")
    led, ev = _wire(wired, tmp_path, monkeypatch, lambda: Boom(0.007), price_per_1k=1.0)
    rep = scheduler.run_due(led, now=ev.published_at + 300, verbose=False)
    r, = led.results()
    assert r.verdict == "ERROR" and r.cost_usd == 0.0 and r.cost_source == "list"
    assert rep.spend_usd == 0.0


def test_old_ledger_rows_without_cost_source_still_load(tmp_path):
    """The field has a default so a ledger written before it existed reads
    as list-priced rather than as wrong-shape."""
    from tti.models import ProbeResult, dumps
    row = ProbeResult(probe_id="p", event_id="e", provider="x", mode="m", rung=300,
                      requested_at=1.0, lag=300.0, verdict="ABSENT").to_dict()
    del row["cost_source"]
    (tmp_path / "results.jsonl").write_text(dumps(row) + "\n")
    led = Ledger(tmp_path)
    r, = led.results()
    assert r.cost_source == "list"
    assert led.integrity() == {}
