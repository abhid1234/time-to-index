"""Every module that reads an npm packument goes through one bounded fetch.

The bound was raised in the collector and not in `forecast` or `decoy`. The
first live forecast then excluded the twelve largest packages from the
event-rate estimate the stopping rule depends on, and the decoy check quietly
downgraded those same packages to "unverified". This test calls all three
entry points and asserts the bound reached the wire each time.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, decoy, forecast, sources
from tti.http import MAX_RESPONSE_BYTES
from tti.models import Event
from tti.sources import npm as npm_mod


def _record(monkeypatch):
    calls: list[tuple[str, int]] = []

    def sized(url, **kw):
        calls.append((url, kw.get("max_bytes", MAX_RESPONSE_BYTES)))
        if url.endswith("/dist-tags"):
            return {"latest": "1.0.1"}, 20
        if "pypi.org" in url:
            return {"releases": {"1.0.1": []}}, 30
        return {"dist-tags": {"latest": "1.0.1"},
                "time": {"1.0.0": "2026-01-01T00:00:00.000Z",
                         "1.0.1": "2026-09-01T00:00:00.000Z"},
                "versions": {"1.0.0": {}, "1.0.1": {}}}, 100
    monkeypatch.setattr(npm_mod.http, "get_json_sized", sized)
    return calls


def _packument_calls(calls):
    return [(u, b) for u, b in calls
            if "registry.npmjs.org" in u and not u.endswith("/dist-tags")]


def test_the_collector_uses_the_bound(monkeypatch):
    calls = _record(monkeypatch)
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["pkg"], "pypi": []})
    sources.get("npm").collect({})
    assert [b for _, b in _packument_calls(calls)] == [npm_mod.PACKUMENT_CAP]


def test_the_forecast_uses_the_bound(monkeypatch):
    calls = _record(monkeypatch)
    row = forecast._npm("pkg")
    assert row.error == "" and row.releases >= 0
    assert [b for _, b in _packument_calls(calls)] == [npm_mod.PACKUMENT_CAP]


def test_the_decoy_check_uses_the_bound_for_npm(monkeypatch):
    calls = _record(monkeypatch)
    ev = Event(source="npm", source_class="package_registry", subject="pkg",
               published_at=1.0, discovered_at=2.0, question="q", answer="1.0.1")
    assert decoy.npm_absent(ev, "1.0.8") is True
    assert [b for _, b in _packument_calls(calls)] == [npm_mod.PACKUMENT_CAP]


def test_pypi_keeps_the_module_default(monkeypatch):
    """The larger bound is for packuments only. PyPI JSON is small and the
    memory guard stays at its default there."""
    calls = _record(monkeypatch)
    ev = Event(source="pypi", source_class="package_registry", subject="pkg",
               published_at=1.0, discovered_at=2.0, question="q", answer="1.0.1")
    assert decoy.npm_absent(ev, "1.0.8") is True
    pypi = [(u, b) for u, b in calls if "pypi.org" in u]
    assert pypi and all(b == MAX_RESPONSE_BYTES for _, b in pypi)


def test_no_module_fetches_a_packument_around_the_helper():
    """Static: the URL template appears in exactly one place."""
    import re
    root = pathlib.Path(__file__).resolve().parent.parent / "tti"
    hits = [str(f.relative_to(root)) for f in root.rglob("*.py")
            if re.search(r'registry\.npmjs\.org/\{', f.read_text())]
    assert hits == ["sources/npm.py"], hits
