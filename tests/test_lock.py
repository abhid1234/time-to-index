"""One writer at a time.

Cron fires on a schedule, not on completion. The moment a provider is slow
enough that `tti probe` outlasts its interval, the next run starts while the
first is still working, and both read the same due set. Measured before this
existed: six queued probes produced twelve provider calls, six duplicate
result rows, and exactly double the spend — with every rate computed
afterwards counting one observation twice.
"""
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti import config, lock, scheduler
from tti.cli import main
from tti.ledger import Ledger
from tti.models import Event, Probe

pytestmark = pytest.mark.skipif(not lock.SUPPORTED,
                                reason="advisory file locking needs fcntl")


def test_a_second_holder_is_refused_immediately(tmp_path):
    """Refused, not queued. A probe run that waits will find its rungs stale
    by the time it starts, and dropping them for slip is worse than not
    running."""
    with lock.exclusive(tmp_path, "probe"):
        started = time.perf_counter()
        with pytest.raises(lock.Busy), lock.exclusive(tmp_path, "probe"):
            pass
        assert time.perf_counter() - started < 0.5


def test_the_lock_is_released_after_the_block(tmp_path):
    with lock.exclusive(tmp_path, "probe"):
        pass
    with lock.exclusive(tmp_path, "probe"):
        pass          # must not raise


def test_the_lock_is_released_even_when_the_block_raises(tmp_path):
    with pytest.raises(ValueError), lock.exclusive(tmp_path, "probe"):
        raise ValueError("boom")
    with lock.exclusive(tmp_path, "probe"):
        pass


def test_different_names_do_not_block_each_other(tmp_path):
    """`discover` and `probe` write different files and may overlap."""
    with lock.exclusive(tmp_path, "probe"), lock.exclusive(tmp_path, "discover"):
        pass


def test_the_holder_is_named(tmp_path):
    import os
    with lock.exclusive(tmp_path, "probe"), \
            pytest.raises(lock.Busy, match=f"pid {os.getpid()}"), \
            lock.exclusive(tmp_path, "probe"):
        pass


def _seed(tmp_path, n=6):
    led = Ledger(tmp_path)
    now = time.time()
    evs = [Event(source="npm", source_class="package_registry", subject=f"p{i}",
                 published_at=now - 400, discovered_at=now - 390, question="q",
                 answer=f"1.0.{i}", predecessor=f"0.9.{i}") for i in range(n)]
    led.add_events(evs)
    led.add_probes([Probe(event_id=e.event_id, provider="stub", mode="base",
                          rung=300, due_at=e.published_at + 300) for e in evs])
    return led


def test_overlapping_probe_runs_do_not_double_spend(tmp_path, monkeypatch):
    """The measurement that motivated the lock, as a regression test."""
    _seed(tmp_path)
    calls, guard = [], threading.Lock()

    class Stub:
        name = "stub"
        def modes(self): return ["base"]
        def available(self): return True
        def search(self, q, m, *, max_results, max_chars):
            with guard:
                calls.append(q)
            time.sleep(0.2)          # slow enough for the next cron tick
            return {"results": [{"snippet": "nothing"}]}

    monkeypatch.setattr(scheduler.providers, "get", lambda n: Stub())
    monkeypatch.setitem(config._cache, "settings", {
        "ladder": [300], "daily_usd_cap": 100.0, "max_results": 5,
        "max_chars_per_result": 500, "max_detection_lag_seconds": 600,
        "max_rung_slip_seconds": 10 ** 9, "origin_control": False,
        "arms": [{"provider": "stub", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers", {"providers": {"stub": {"modes": {
        "base": {"usd_per_1k_requests": 1.0, "results_included": 5}}}}})

    def run():
        main(["--run-dir", str(tmp_path), "probe"])

    t1, t2 = threading.Thread(target=run), threading.Thread(target=run)
    t1.start()
    time.sleep(0.05)
    t2.start()
    t1.join()
    t2.join()

    results = Ledger(tmp_path).results()
    ids = [r.probe_id for r in results]
    assert len(calls) == 6, f"each probe must be dispatched once, got {len(calls)}"
    assert len(ids) == len(set(ids)) == 6
    assert sum(r.cost_usd for r in results) == pytest.approx(0.006)


def test_a_refused_run_exits_zero(tmp_path, capsys):
    """Early, not broken. A cron wrapper must not page anyone for it."""
    with lock.exclusive(tmp_path, "probe"):
        assert main(["--run-dir", str(tmp_path), "probe"]) == 0
    assert "already running" in capsys.readouterr().out


def test_a_dry_run_needs_no_lock(tmp_path):
    """It writes nothing, so it must remain usable while a real run is in
    flight — that is exactly when someone wants to look."""
    with lock.exclusive(tmp_path, "probe"):
        assert main(["--run-dir", str(tmp_path), "probe", "--dry-run"]) == 0


def test_duplicates_already_in_a_ledger_are_de_duplicated_and_reported(tmp_path):
    """A ledger written before the lock existed is not lost, but it must not
    silently count one observation twice."""
    from tti.models import FRESH, ProbeResult
    led = Ledger(tmp_path)
    row = ProbeResult(probe_id="dup", event_id="e", provider="stub", mode="base",
                      rung=300, requested_at=1.0, lag=300.0, verdict=FRESH,
                      cost_usd=0.005)
    led.add_results([row, row])
    fresh = Ledger(tmp_path)
    assert len(fresh.results()) == 1
    assert fresh.integrity()["results.jsonl"]["duplicates"] == 1
