"""Large packuments, found by the first live run against the npm registry.

The module-wide 8 MB response cap -- itself a guard, added after a 200 MB
response took memory to 432 MB -- refused twelve of the forty-six watched
packages, `next` among them, because the full packument is the only document
that carries the `time` map and big packages' packuments run 8 to 16 MB.

These tests pin the per-source bound that replaced it, the warning that fires
before the next crossing, and the reporting that names the subjects.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, sources
from tti.sources import npm as npm_mod


def _watch(monkeypatch, *pkgs):
    monkeypatch.setitem(config._cache, "watchlist", {"npm": list(pkgs), "pypi": []})


def _fresh(now):
    return [("1.0.0", now - 90_000), ("1.0.1", now - 20)]


def test_a_packument_over_the_old_module_cap_is_collected(wired, monkeypatch):
    """9 MB: over the 8 MB module default that refused `next`, under the
    per-source bound. Must collect, with no error and no warning."""
    now = time.time()
    wired.publish_npm("big", _fresh(now), pad_bytes=9_000_000)
    _watch(monkeypatch, "big")
    src = sources.get("npm")
    got = src.collect({})
    assert [e.subject for e in got] == ["big"]
    assert src.errors == []
    assert src.warnings == []


def test_a_packument_over_the_per_source_bound_is_still_refused(wired, monkeypatch):
    """The bound is real. Exercised with the constants lowered rather than by
    serving 33 MB in a unit test."""
    monkeypatch.setattr(npm_mod, "PACKUMENT_CAP", 200_000)
    monkeypatch.setattr(npm_mod, "PACKUMENT_WARN", 150_000)
    now = time.time()
    wired.publish_npm("huge", _fresh(now), pad_bytes=300_000)
    _watch(monkeypatch, "huge")
    src = sources.get("npm")
    assert src.collect({}) == []
    assert len(src.errors) == 1
    assert src.errors[0].startswith("huge: ResponseTooLarge")


def test_a_packument_approaching_the_bound_is_collected_and_warns(wired, monkeypatch):
    """Between the warning line and the bound: the event is real and is
    returned, and the subject is named so the bound gets raised before the
    day it starts failing."""
    monkeypatch.setattr(npm_mod, "PACKUMENT_CAP", 200_000)
    monkeypatch.setattr(npm_mod, "PACKUMENT_WARN", 150_000)
    now = time.time()
    wired.publish_npm("growing", _fresh(now), pad_bytes=170_000)
    _watch(monkeypatch, "growing")
    src = sources.get("npm")
    got = src.collect({})
    assert [e.subject for e in got] == ["growing"]
    assert src.errors == []
    assert len(src.warnings) == 1
    assert src.warnings[0].startswith("growing: packument is 0.2 MB")
    assert "PACKUMENT_CAP" in src.warnings[0]


def test_other_fetches_keep_the_module_default(wired, monkeypatch):
    """Only the packument fetch got the larger bound. PyPI still refuses at
    the module default, so the memory guard is not quietly loosened
    everywhere."""
    from tti import http as H
    now = time.time()
    wired.publish_pypi("fat", [("1.0.0", now - 90_000), ("1.0.1", now - 20)])
    wired.pypi["fat"]["info"]["description"] = "x" * (H.MAX_RESPONSE_BYTES + 1000)
    monkeypatch.setitem(config._cache, "watchlist", {"npm": [], "pypi": ["fat"]})
    src = sources.get("pypi")
    assert src.collect({}) == []
    assert src.errors and "ResponseTooLarge" in src.errors[0]


def test_subject_names_lists_who_failed_not_just_the_first():
    msgs = [f"pkg-{i}: ResponseTooLarge: body exceeded" for i in range(12)]
    out = sources.subject_names(msgs)
    assert out.startswith("pkg-0, pkg-1")
    assert out.endswith(", +4 more")
    assert sources.subject_names(msgs[:3]) == "pkg-0, pkg-1, pkg-2"
    assert sources.subject_names([]) == ""


def test_discover_names_the_failing_subjects(wired, monkeypatch, capsys):
    """The output that would have said `next` was broken on the first run,
    instead of "12/46 failed -- antd: ..." and eleven unknowns."""
    from tti import scheduler
    monkeypatch.setattr(npm_mod, "PACKUMENT_CAP", 200_000)
    monkeypatch.setattr(npm_mod, "PACKUMENT_WARN", 150_000)
    now = time.time()
    wired.publish_npm("ok", _fresh(now))
    wired.publish_npm("next", _fresh(now), pad_bytes=300_000)
    wired.publish_npm("vite", _fresh(now), pad_bytes=300_000)
    _watch(monkeypatch, "ok", "next", "vite")
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300], "origin_control": False, "arms": []})
    import tempfile

    from tti.ledger import Ledger
    scheduler.discover(Ledger(pathlib.Path(tempfile.mkdtemp())), verbose=True)
    out = capsys.readouterr().out
    assert "2/3 subjects failed" in out
    assert "next" in out and "vite" in out


# ---------------------------------------------------------------------------
# Change detection: the 300-byte question before the 30 MB document
# ---------------------------------------------------------------------------

def _spy(monkeypatch):
    """Record what the npm source fetches, classified by URL.

    Only `get_json_sized` is wrapped: `get_json` delegates to it, so wrapping
    both counts one dist-tags request twice. "tags" is the 300-byte question;
    "packument" is the document that runs to tens of megabytes.
    """
    calls: list[str] = []
    real = npm_mod.http.get_json_sized

    def sized(url, **kw):
        calls.append("tags" if url.endswith("/dist-tags") else "packument")
        return real(url, **kw)
    monkeypatch.setattr(npm_mod.http, "get_json_sized", sized)
    return calls


def test_an_unchanged_subject_never_fetches_the_packument(wired, monkeypatch):
    """The hot path. On a five-minute cadence almost every poll sees no
    change, and the full document -- 31 MB for `next` -- must not be asked
    for. Only dist-tags is."""
    now = time.time()
    wired.publish_npm("big", _fresh(now), pad_bytes=200_000)
    _watch(monkeypatch, "big")
    calls = _spy(monkeypatch)
    src = sources.get("npm")
    assert src.collect({("npm", "big"): "1.0.1"}) == []
    assert calls == ["tags"], calls


def test_a_prerelease_latest_is_skipped_before_the_packument_is_fetched(wired, monkeypatch):
    """prisma's dist-tags said latest=8.0.0-rc.12 on the live registry. The
    collector already skipped prereleases; it should do so without first
    downloading 44 MB to find out."""
    now = time.time()
    wired.publish_npm("rc", [("1.0.0", now - 90_000), ("2.0.0-rc.1", now - 20)])
    _watch(monkeypatch, "rc")
    calls = _spy(monkeypatch)
    assert sources.get("npm").collect({}) == []
    assert calls == ["tags"]


def test_a_changed_subject_fetches_the_packument_and_yields_the_event(wired, monkeypatch):
    now = time.time()
    wired.publish_npm("moved", _fresh(now))
    _watch(monkeypatch, "moved")
    calls = _spy(monkeypatch)
    got = sources.get("npm").collect({("npm", "moved"): "1.0.0"})
    assert [(e.answer, e.predecessor) for e in got] == [("1.0.1", "1.0.0")]
    assert calls == ["tags", "packument"]


# ---------------------------------------------------------------------------
# The high-water mark advances past late drops
# ---------------------------------------------------------------------------

def _stale_watch(wired, monkeypatch, now):
    wired.publish_npm("old", [("2.0.0", now - 400_000), ("2.0.1", now - 200_000)])
    _watch(monkeypatch, "old")
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300], "origin_control": False, "arms": []})


def test_a_late_drop_is_not_refetched_on_the_next_poll(wired, monkeypatch, tmp_path):
    """The bandwidth bug. Dropped-late events were never written anywhere, so
    the collector had no memory of them and asked for the same document on
    every poll. Against the live registry that was roughly a gigabyte per
    five-minute cycle on a stale watchlist."""
    from tti import scheduler
    from tti.ledger import Ledger
    now = time.time()
    _stale_watch(wired, monkeypatch, now)
    led = Ledger(tmp_path)

    first = scheduler.discover(led, verbose=False)
    assert (first.collected, first.dropped_late, first.new_events) == (1, 1, 0)
    assert led.seen_path.exists()
    assert led.seen_subjects() == {("npm", "old"): "2.0.1"}

    calls = _spy(monkeypatch)
    second = scheduler.discover(led, verbose=False)
    assert (second.collected, second.dropped_late) == (0, 0)
    # dist-tags asked, packument never touched
    assert calls == ["tags"]


def test_a_dry_run_does_not_advance_the_mark(wired, monkeypatch, tmp_path):
    from tti import scheduler
    from tti.ledger import Ledger
    now = time.time()
    _stale_watch(wired, monkeypatch, now)
    led = Ledger(tmp_path)
    rep = scheduler.discover(led, verbose=False, dry_run=True)
    assert rep.dropped_late == 1
    assert not led.seen_path.exists()
    assert led.seen_subjects() == {}


def test_marking_the_same_answer_twice_writes_once(tmp_path):
    from tti.ledger import Ledger
    from tti.models import Event
    led = Ledger(tmp_path)
    e = Event(source="npm", source_class="package_registry", subject="p",
              published_at=1.0, discovered_at=2.0, question="q", answer="1.0.0")
    assert led.mark_seen([e], "detected_late") == 1
    assert led.mark_seen([e], "detected_late") == 0
    with open(led.seen_path, encoding="utf-8") as fh:
        assert sum(1 for _ in fh) == 1


def test_a_future_clock_drop_is_not_marked(wired, monkeypatch, tmp_path):
    """Marking it would silently lose the event when its timestamp becomes
    valid. It is an error, and errors are not high-water marks."""
    from tti import scheduler
    from tti.ledger import Ledger
    now = time.time()
    wired.publish_npm("ahead", [("1.0.0", now - 90_000), ("1.0.1", now + 3600)])
    _watch(monkeypatch, "ahead")
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "max_clock_skew_seconds": 120,
        "ladder": [300], "origin_control": False, "arms": []})
    rep = scheduler.discover(Ledger(tmp_path), verbose=False)
    assert rep.dropped_future == 1
    assert not (tmp_path / "seen.jsonl").exists()


def test_the_later_record_wins_across_the_two_files(tmp_path):
    """events.jsonl and seen.jsonl are appended independently; file order
    says nothing about wall-clock order between them."""
    from tti.ledger import Ledger
    from tti.models import Event
    led = Ledger(tmp_path)
    older = Event(source="npm", source_class="package_registry", subject="p",
                  published_at=1.0, discovered_at=100.0, question="q", answer="1.0.0")
    led.add_events([older])
    newer = Event(source="npm", source_class="package_registry", subject="p",
                  published_at=2.0, discovered_at=200.0, question="q", answer="1.0.1")
    led.mark_seen([newer], "detected_late")
    assert led.seen_subjects()[("npm", "p")] == "1.0.1"
    # and the reverse: a newer real event outranks an older mark
    led2 = Ledger(tmp_path / "b")
    led2.mark_seen([older], "detected_late")
    import json as _j
    # force the mark's timestamp to be older than the event's discovered_at
    with open(led2.seen_path, encoding="utf-8") as fh:
        rows = [_j.loads(line) for line in fh]
    rows[0]["marked_at"] = 50.0
    led2.seen_path.write_text("\n".join(_j.dumps(r) for r in rows) + "\n")
    led2.add_events([newer])
    assert led2.seen_subjects()[("npm", "p")] == "1.0.1"
