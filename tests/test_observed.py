"""The measured ladder, flattened for the page, must not invent absences.

The whole project rests on one distinction: a search index that has not
answered yet is not a search index that answered "I don't have it". Every
rendering of the ladder has to preserve that, and the flattening step is
where it would be easiest to lose -- a missing result is naturally an empty
cell, and an empty cell naturally reads as nothing found.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import observed
from tti.ledger import Ledger
from tti.models import ABSENT, FRESH, SKIPPED, STALE, Event, Probe, ProbeResult

NOW = 1_800_000_000.0
PUBLISHED = NOW - 3600.0     # one hour old: 5m/15m/1h are due, 6h+ are not
RUNGS = [300, 900, 3600, 21600, 86400, 259200]


def _event(subject: str = "astro", answer: str = "7.3.1",
           published: float = PUBLISHED) -> Event:
    return Event(source="npm", source_class="package_registry", subject=subject,
                 published_at=published, discovered_at=published + 120,
                 question=f"What is the current latest published version of {subject}?",
                 answer=answer, answer_aliases=[answer],
                 predecessor="7.2.4", predecessor_aliases=["7.2.4"],
                 url=f"https://www.npmjs.com/package/{subject}")


def _led(tmp_path, events, probes=(), results=()) -> Ledger:
    led = Ledger(tmp_path)
    led.add_events(list(events))
    if probes:
        led.add_probes(list(probes))
    if results:
        led.add_results(list(results))
    return led


def _probes(ev: Event, provider: str, mode: str, rungs=RUNGS) -> list[Probe]:
    return [Probe(event_id=ev.event_id, provider=provider, mode=mode, rung=r,
                  due_at=ev.published_at + r) for r in rungs]


def _result(ev: Event, pr: Probe, verdict: str, **kw) -> ProbeResult:
    return ProbeResult(probe_id=pr.probe_id, event_id=ev.event_id,
                       provider=pr.provider, mode=pr.mode, rung=pr.rung,
                       requested_at=ev.published_at + pr.rung,
                       lag=float(pr.rung), verdict=verdict, **kw)


def _cells(data, provider="exa"):
    arm = next(a for a in data["events"][0]["arms"] if a["provider"] == provider)
    return arm["cells"]


def test_a_rung_that_has_not_come_round_yet_is_not_an_absence(tmp_path):
    ev = _event()
    led = _led(tmp_path, [ev], _probes(ev, "exa", "auto"))
    cells = _cells(observed.build(led, now=NOW))
    # 6h, 24h and 72h are still in the future for an hour-old event.
    for c in cells[3:]:
        assert c["state"] == "scheduled"
        assert "verdict" not in c
        assert c["due_in"] > 0


def test_a_rung_that_is_due_and_unrun_says_so_rather_than_going_blank(tmp_path):
    """This is the state a stalled runner produces, and it must be legible."""
    ev = _event()
    led = _led(tmp_path, [ev], _probes(ev, "exa", "auto"))
    cells = _cells(observed.build(led, now=NOW))
    for c in cells[:3]:              # 5m, 15m, 1h have all come due
        assert c["state"] == "pending"
        assert c["overdue_by"] >= 0
        assert "verdict" not in c


def test_an_arm_that_was_never_scheduled_is_distinct_from_one_that_answered_nothing(tmp_path):
    """Keys attach at discovery, so an arm added later has no probes at all.

    Drawing that as ABSENT would credit the benchmark with measurements it
    never made -- and would make a provider look worse for having been
    configured late.
    """
    ev = _event()
    probes = _probes(ev, "exa", "auto")[:1]     # only the 5m rung exists
    led = _led(tmp_path, [ev], probes,
               [_result(ev, probes[0], ABSENT)])
    cells = _cells(observed.build(led, now=NOW))
    assert cells[0]["state"] == "graded"
    assert cells[0]["verdict"] == ABSENT
    assert all(c["state"] == "never_scheduled" for c in cells[1:])


def test_a_graded_cell_carries_the_verdict_verbatim(tmp_path):
    ev = _event()
    probes = _probes(ev, "exa", "auto")
    led = _led(tmp_path, [ev], probes, [
        _result(ev, probes[0], ABSENT, latency_ms=1516, n_results=5,
                cost_usd=0.007, cost_source="reported"),
        _result(ev, probes[1], STALE, matched_stale=["7.2.4"], n_results=5),
        _result(ev, probes[2], FRESH, matched_fresh=["7.3.1"], n_results=5),
    ])
    cells = _cells(observed.build(led, now=NOW))
    assert [c["verdict"] for c in cells[:3]] == [ABSENT, STALE, FRESH]
    assert cells[0]["cost_usd"] == 0.007
    assert cells[1]["stale_hits"] == 1
    assert cells[2]["fresh_hits"] == 1


def test_the_carry_forward_skip_stays_a_skip_and_never_becomes_an_absence(tmp_path):
    """Once an arm answers FRESH the later rungs are not asked.

    Rendering those as ABSENT would turn every success into five failures.
    """
    ev = _event()
    probes = _probes(ev, "exa", "auto")
    led = _led(tmp_path, [ev], probes, [
        _result(ev, probes[0], FRESH, matched_fresh=["7.3.1"]),
        *[_result(ev, p, SKIPPED, note="carry-forward") for p in probes[1:]],
    ])
    cells = _cells(observed.build(led, now=NOW))
    assert cells[0]["verdict"] == FRESH
    assert all(c["verdict"] == SKIPPED for c in cells[1:])
    assert cells[1]["note"] == "carry-forward"
    data = observed.build(led, now=NOW)
    assert data["totals"]["absent"] == 0


def test_the_first_fresh_rung_is_reported_so_a_page_need_not_recompute_it(tmp_path):
    ev = _event()
    probes = _probes(ev, "exa", "auto")
    led = _led(tmp_path, [ev], probes, [
        _result(ev, probes[0], ABSENT),
        _result(ev, probes[1], ABSENT),
        _result(ev, probes[2], FRESH, matched_fresh=["7.3.1"]),
    ])
    arm = observed.build(led, now=NOW)["events"][0]["arms"][0]
    assert arm["first_fresh_rung"] == 3600


def test_the_control_is_marked_and_excluded_from_the_provider_totals(tmp_path):
    """The origin arm answers by fetching the page; counting it as a search
    result would flatter the leaderboard with a hit nobody searched for."""
    ev = _event()
    exa = _probes(ev, "exa", "auto")[:1]
    org = _probes(ev, observed.ORIGIN, "direct")[:1]
    led = _led(tmp_path, [ev], exa + org, [
        _result(ev, exa[0], ABSENT),
        _result(ev, org[0], FRESH, matched_fresh=["7.3.1"]),
    ])
    data = observed.build(led, now=NOW)
    arms = {a["provider"]: a for a in data["events"][0]["arms"]}
    assert arms[observed.ORIGIN]["control"] is True
    assert arms["exa"]["control"] is False
    assert data["totals"]["fresh"] == 0      # the control's FRESH is not a provider's
    assert data["totals"]["absent"] == 1
    assert data["totals"]["provider_cells"] == 1


def test_a_probe_appended_twice_is_counted_once(tmp_path):
    """Two overlapping `tti probe` runs both append the same probe_id.

    The ledger resolves that first-occurrence-wins, and this reads through
    it: a repeated row must not become a second graded cell, or the page
    would report more measurements and more spend than were made. (A
    corrected verdict does not arrive this way -- `tti regrade --write`
    rewrites results.jsonl rather than appending to it.)
    """
    ev = _event()
    probes = _probes(ev, "exa", "auto")
    led = _led(tmp_path, [ev], probes, [
        _result(ev, probes[0], ABSENT, cost_usd=0.007),
        _result(ev, probes[0], ABSENT, cost_usd=0.007),
    ])
    data = observed.build(led, now=NOW)
    assert data["totals"]["provider_cells"] == 1
    assert data["totals"]["spend_usd"] == 0.007
    assert data["events"][0]["arms"][0]["spend_usd"] == 0.007


def test_rungs_come_from_the_data_not_from_the_current_config(tmp_path):
    """A plan edited after collection must not silently restate old events."""
    ev = _event()
    led = _led(tmp_path, [ev], _probes(ev, "exa", "auto", rungs=[300, 900]))
    e = observed.build(led, now=NOW)["events"][0]
    assert e["rungs"] == [300, 900]
    assert e["rung_labels"] == ["5m", "15m"]
    assert len(e["arms"][0]["cells"]) == 2


def test_events_are_newest_first_and_the_limit_keeps_the_newest(tmp_path):
    old = _event("react", "18.0.0", PUBLISHED - 86400)
    new = _event("astro", "7.3.1", PUBLISHED)
    led = _led(tmp_path, [old, new],
               _probes(old, "exa", "auto") + _probes(new, "exa", "auto"))
    data = observed.build(led, now=NOW)
    assert [e["subject"] for e in data["events"]] == ["astro", "react"]
    one = observed.build(led, now=NOW, limit=1)
    assert [e["subject"] for e in one["events"]] == ["astro"]
    # The ledger's true size is still reported, so a limited page cannot
    # imply the run is smaller than it is.
    assert one["totals"]["events_in_ledger"] == 2


def test_an_event_with_no_probes_at_all_is_dropped_rather_than_shown_empty(tmp_path):
    """An all-blank row is exactly the picture that reads as six absences."""
    led = _led(tmp_path, [_event()])
    assert observed.build(led, now=NOW)["events"] == []


def test_detection_lag_is_carried_because_the_clock_starts_at_publication(tmp_path):
    ev = _event()
    led = _led(tmp_path, [ev], _probes(ev, "exa", "auto"))
    e = observed.build(led, now=NOW)["events"][0]
    assert e["detection_lag"] == 120
    assert e["age_seconds"] == 3600


def test_the_whole_structure_survives_a_round_trip_through_json(tmp_path):
    """It is written to a file and fetched by a browser; anything that cannot
    serialise is a page that renders nothing."""
    import json

    ev = _event()
    probes = _probes(ev, "exa", "auto")
    led = _led(tmp_path, [ev], probes, [_result(ev, probes[0], ABSENT)])
    data = observed.build(led, now=NOW)
    assert json.loads(json.dumps(data)) == data


def test_a_limited_page_still_reports_the_whole_run(tmp_path):
    """`limit` caps what is drawn, never what is claimed.

    The page prints these totals under "across the whole run so far". If they
    shrank with the limit, a long-running collection would quietly understate
    its own sample size and its own spend -- and sample size is the number a
    reader most needs to be able to trust.
    """
    old = _event("react", "18.0.0", PUBLISHED - 86400)
    new = _event("astro", "7.3.1", PUBLISHED)
    op, np_ = _probes(old, "exa", "auto"), _probes(new, "exa", "auto")
    led = _led(tmp_path, [old, new], op + np_, [
        _result(old, op[0], ABSENT, cost_usd=0.007),
        _result(new, np_[0], ABSENT, cost_usd=0.007),
    ])
    everything = observed.build(led, now=NOW)["totals"]
    just_one = observed.build(led, now=NOW, limit=1)["totals"]

    assert just_one["events"] == 1 and everything["events"] == 2
    assert {k: v for k, v in just_one.items() if k != "events"} == \
           {k: v for k, v in everything.items() if k != "events"}
    assert just_one["provider_cells"] == 2
    assert just_one["spend_usd"] == 0.014


def test_the_default_limit_exists_so_the_file_cannot_grow_without_bound(tmp_path):
    """Every visitor downloads this file; a year of collection must not be
    a multi-megabyte page load."""
    assert observed.DEFAULT_LIMIT > 0
