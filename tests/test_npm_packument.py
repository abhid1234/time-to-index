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
