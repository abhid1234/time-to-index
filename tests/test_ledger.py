"""Ledger durability.

This file is written by an unattended job for weeks at a time. A reboot, a
full disk, or a kill during `tti probe` leaves a partially written last line,
and the first version of the Ledger raised JSONDecodeError from every read
path when that happened — so one interrupted write made the whole run
unreadable, raw payloads included, with no way back.

Skipping is the right behaviour and silence is not: reading 9,900 of 10,000
records without saying so is its own wrong answer.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti.ledger import Ledger
from tti.models import FRESH, Event, Probe, ProbeResult


def seed(tmp_path):
    led = Ledger(tmp_path)
    ev = Event(source="npm", source_class="package_registry", subject="p",
               published_at=1.0, discovered_at=2.0, question="q",
               answer="1.0.1", predecessor="1.0.0")
    led.add_events([ev])
    # A provider that exists in the shipped price table, so `tti status` can
    # price its due probes.
    led.add_probes([Probe(event_id=ev.event_id, provider="serper", mode="search",
                          rung=300, due_at=301.0)])
    led.add_results([ProbeResult(probe_id="x", event_id=ev.event_id,
                                 provider="serper", mode="search", rung=300,
                                 requested_at=300.0, lag=300.0, verdict=FRESH,
                                 cost_usd=0.005)])
    return led, ev


def tear(path):
    """The realistic corruption: the process died mid-write."""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"probe_id": "y", "event_i')


def test_every_read_path_survives_a_torn_final_line(tmp_path):
    led, ev = seed(tmp_path)
    for p in (led.events_path, led.probes_path, led.results_path):
        tear(p)
    fresh = Ledger(tmp_path)
    assert len(fresh.events()) == 1
    assert len(fresh.probes()) == 1
    assert len(fresh.results()) == 1
    assert fresh.spent_on("1970-01-01") == pytest.approx(0.005)
    assert len(fresh.resolved_fresh()) == 1
    assert len(fresh.completed_probe_ids()) == 1
    assert fresh.seen_subjects() == {("npm", "p"): "1.0.1"}


def test_a_torn_line_is_reported_not_hidden(tmp_path):
    led, _ = seed(tmp_path)
    tear(led.events_path)
    report = Ledger(tmp_path).integrity()
    assert report["events.jsonl"]["unparseable"] == 1
    assert report["events.jsonl"]["total"] == 2


def test_a_record_of_the_wrong_shape_is_counted_separately(tmp_path):
    """Valid JSON that no longer matches the model — usually an older schema.
    A different problem from a torn write, and it needs a different fix."""
    led, _ = seed(tmp_path)
    with open(led.results_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"unexpected": "shape"}) + "\n")
    report = Ledger(tmp_path).integrity()
    assert report["results.jsonl"]["wrong_shape"] == 1
    assert report["results.jsonl"]["unparseable"] == 0
    assert report["results.jsonl"]["duplicates"] == 0


def test_a_clean_ledger_reports_nothing(tmp_path):
    led, _ = seed(tmp_path)
    assert Ledger(tmp_path).integrity() == {}


def test_integrity_does_not_multiply_across_repeated_reads(tmp_path):
    """The counter version reported one torn line three times after three
    queries, because each query rescans the file."""
    led, _ = seed(tmp_path)
    tear(led.results_path)
    fresh = Ledger(tmp_path)
    fresh.results()
    fresh.results()
    fresh.spent_on("1970-01-01")
    assert fresh.integrity()["results.jsonl"]["unparseable"] == 1


def test_a_non_object_json_line_is_not_a_record(tmp_path):
    led, _ = seed(tmp_path)
    with open(led.events_path, "a", encoding="utf-8") as fh:
        fh.write('"a bare string"\n[1,2,3]\n')
    fresh = Ledger(tmp_path)
    assert len(fresh.events()) == 1
    assert fresh.integrity()["events.jsonl"]["unparseable"] == 2


def test_blank_lines_are_not_corruption(tmp_path):
    led, _ = seed(tmp_path)
    with open(led.events_path, "a", encoding="utf-8") as fh:
        fh.write("\n\n   \n")
    fresh = Ledger(tmp_path)
    assert len(fresh.events()) == 1
    assert fresh.integrity() == {}


def test_appends_after_a_torn_line_still_read_back(tmp_path):
    """The realistic recovery: the next run appends a fresh line after the
    broken one, and both the old and new records must survive."""
    led, ev = seed(tmp_path)
    tear(led.results_path)
    Ledger(tmp_path).add_results([ProbeResult(
        probe_id="z", event_id=ev.event_id, provider="serper", mode="search", rung=900,
        requested_at=900.0, lag=900.0, verdict=FRESH, cost_usd=0.005)])
    fresh = Ledger(tmp_path)
    assert len(fresh.results()) == 2
    assert fresh.spent_on("1970-01-01") == pytest.approx(0.010)


def test_status_names_the_damage(tmp_path, capsys):
    from tti.cli import main
    led, _ = seed(tmp_path)
    tear(led.events_path)
    assert main(["--run-dir", str(tmp_path), "status"]) == 0
    out = capsys.readouterr().out
    assert "ledger integrity" in out
    assert "torn write" in out
    assert "smaller denominator" in out


def test_an_arm_missing_from_the_price_table_is_named_not_crashed(tmp_path, capsys):
    """Realistic: an arm is removed from providers.yaml after it has already
    written results. `tti status` used to raise KeyError from deep inside the
    cost table."""
    from tti.cli import main
    led, ev = seed(tmp_path)
    led.add_probes([Probe(event_id=ev.event_id, provider="gone", mode="base",
                          rung=900, due_at=1.0)])
    assert main(["--run-dir", str(tmp_path), "status"]) == 0
    out = capsys.readouterr().out
    assert "not in providers.yaml" in out and "gone/base" in out


# ---------------------------------------------------------------------------
# The one destructive operation
# ---------------------------------------------------------------------------

def _bulk(tmp_path, n=40, verdict="ABSENT"):
    from tti.models import ProbeResult
    led = Ledger(tmp_path)
    ev = Event(source="npm", source_class="package_registry", subject="p",
               published_at=1.0, discovered_at=2.0, question="q", answer="1.0.1")
    led.add_events([ev])
    rows = []
    for i in range(n):
        ref = led.store_raw("px", f"p{i}", {"results": [{"snippet": "now at 1.0.1"}]})
        rows.append(ProbeResult(probe_id=f"p{i}", event_id=ev.event_id, provider="px",
                                mode="base", rung=300, requested_at=300.0, lag=300.0,
                                verdict=verdict, cost_usd=0.005, raw_ref=ref))
    led.add_results(rows)
    return led, ev


def test_rewrite_is_atomic_and_leaves_no_temp_file(tmp_path):
    led, _ = _bulk(tmp_path)
    rows = led.results()
    for r in rows:
        r.verdict = FRESH
    led.rewrite_results(rows)
    fresh = Ledger(tmp_path)
    assert len(fresh.results()) == 40
    assert all(r.verdict == FRESH for r in fresh.results())
    assert not any(p.name.startswith(".results") for p in tmp_path.iterdir())


def test_rewrite_keeps_the_previous_file(tmp_path):
    """The only destructive operation in the project, and the one a sceptical
    reader runs when they take the README up on re-grading the evidence."""
    led, _ = _bulk(tmp_path)
    backup = led.rewrite_results([])
    assert backup is not None and backup.exists()
    assert backup.read_text().count("\n") == 40
    assert Ledger(tmp_path).results() == []


def test_an_interrupted_rewrite_leaves_the_original_intact(tmp_path, monkeypatch):
    """A direct write over the live file truncated weeks of collection when
    it was interrupted. With a temp file and a rename, a failure mid-write
    leaves the original untouched."""
    led, _ = _bulk(tmp_path)
    original = led.results_path.read_bytes()

    real_replace = os.replace

    def die(*a, **k):
        raise KeyboardInterrupt("interrupted mid-rewrite")

    monkeypatch.setattr(os, "replace", die)
    with pytest.raises(KeyboardInterrupt):
        led.rewrite_results([])
    monkeypatch.setattr(os, "replace", real_replace)

    assert led.results_path.read_bytes() == original
    assert len(Ledger(tmp_path).results()) == 40


def test_regrade_write_refuses_while_a_probe_run_holds_the_lock(tmp_path, capsys):
    """A concurrent probe appending between the read and the write would have
    its rows silently discarded, and no count anywhere would show it."""
    from tti import lock
    from tti.cli import main
    if not lock.SUPPORTED:
        pytest.skip("advisory file locking needs fcntl")
    _bulk(tmp_path)
    with lock.exclusive(tmp_path, "probe"):
        assert main(["--run-dir", str(tmp_path), "regrade", "--write"]) == 1
    out = capsys.readouterr().out
    assert "refused" in out and "discard whatever that run wrote" in out


def test_regrade_without_write_changes_nothing(tmp_path, capsys):
    from tti.cli import main
    led, _ = _bulk(tmp_path)
    before = led.results_path.read_bytes()
    assert main(["--run-dir", str(tmp_path), "regrade"]) == 0
    assert led.results_path.read_bytes() == before
    assert "pass --write to apply" in capsys.readouterr().out


def test_regrade_write_regrades_from_the_stored_payloads(tmp_path, capsys):
    """The whole affordance: change the rules, re-score the evidence, see how
    far the leaderboard actually moves — without a single API call."""
    from tti.cli import main
    _bulk(tmp_path, verdict="ABSENT")
    assert main(["--run-dir", str(tmp_path), "regrade", "--write"]) == 0
    assert all(r.verdict == FRESH for r in Ledger(tmp_path).results())
    out = capsys.readouterr().out
    assert "40 verdicts changed" in out and "previous file kept at" in out
