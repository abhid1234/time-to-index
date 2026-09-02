"""Collectors against the publishers' own terms, not against a comment.

arXiv: one request every three seconds, single connection. EDGAR and the
Federal Register: Eastern time is a zone, not an offset. GitHub: enough of
the page to see past a run of prereleases.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, sources
from tti.sources import arxiv as ax
from tti.sources import edgar as ed
from tti.sources import federal_register as fr
from tti.sources import github_releases as gh

# ----------------------------------------------------------------- arXiv

def test_arxiv_requests_are_sequential_and_spaced(monkeypatch):
    """Timed, not asserted from the attribute. The attribute said the right
    thing before and the pool ignored it."""
    starts: list[float] = []
    live = {"n": 0, "max": 0}
    lock = threading.Lock()

    def fake_get_text(url, **kw):
        with lock:
            live["n"] += 1
            live["max"] = max(live["max"], live["n"])
        starts.append(time.monotonic())
        time.sleep(0.02)
        with lock:
            live["n"] -= 1
        return '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    monkeypatch.setattr(ax.http, "get_text", fake_get_text)
    monkeypatch.setitem(config._cache, "watchlist",
                        {"arxiv": ["cs.AI", "cs.CL", "cs.LG"], "npm": [], "pypi": []})
    src = sources.get("arxiv")
    src.min_interval = 0.15          # scaled down; the shape is what matters
    src.collect({})
    assert len(starts) == 3
    assert live["max"] == 1, "two arXiv connections were open at once"
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert all(g >= 0.15 for g in gaps), gaps


def test_arxiv_declares_the_rule_it_follows():
    src = sources.get("arxiv")
    assert src.workers == 1
    assert src.min_interval == 3.0


def test_the_spaced_path_keeps_the_same_error_accounting(monkeypatch):
    """A subject that fails on the sequential path must be counted exactly as
    it would be on the pool path: named in errors, others still collected."""
    calls = {"n": 0}

    def flaky(url, **kw):
        calls["n"] += 1
        if kw["params"]["search_query"] == "cat:cs.CL":
            raise RuntimeError("503")
        return '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    monkeypatch.setattr(ax.http, "get_text", flaky)
    monkeypatch.setitem(config._cache, "watchlist",
                        {"arxiv": ["cs.AI", "cs.CL", "cs.LG"], "npm": [], "pypi": []})
    src = sources.get("arxiv")
    src.min_interval = 0.0
    src.collect({})
    assert calls["n"] == 3
    assert src.attempted == 3
    assert [e.split(":")[0] for e in src.errors] == ["cs.CL"]
    assert not src.all_failed


# ------------------------------------------------------ Eastern time is a zone

def test_edgar_naive_eastern_stamps_follow_daylight_saving():
    """January is UTC-5, July is UTC-4. A fixed -4 was an hour wrong in
    January."""
    jan = ed._accept_ts("2026-01-15T16:00:00.000")
    jul = ed._accept_ts("2026-07-15T16:00:00.000")
    assert dt.datetime.fromtimestamp(jan, dt.timezone.utc).hour == 21
    assert dt.datetime.fromtimestamp(jul, dt.timezone.utc).hour == 20


def test_edgar_zulu_stamps_are_taken_as_given():
    z = ed._accept_ts("2026-01-15T16:00:00.000Z")
    assert dt.datetime.fromtimestamp(z, dt.timezone.utc).hour == 16


def test_federal_register_issue_time_is_eight_eastern_year_round(monkeypatch):
    def fake(url, **kw):
        return {"results": [
            {"document_number": "2026-00001", "title": "Winter rule",
             "publication_date": "2026-01-15", "html_url": "https://x/1",
             "agencies": [{"name": "A"}], "type": "Rule"},
            {"document_number": "2026-00002", "title": "Summer rule",
             "publication_date": "2026-07-15", "html_url": "https://x/2",
             "agencies": [{"name": "A"}], "type": "Rule"}]}
    monkeypatch.setattr(fr.http, "get_json", fake)
    got = {e.subject: e.published_at for e in sources.get("federal_register").collect({})}
    winter = dt.datetime.fromtimestamp(got["2026-00001"], dt.timezone.utc)
    summer = dt.datetime.fromtimestamp(got["2026-00002"], dt.timezone.utc)
    assert (winter.hour, summer.hour) == (13, 12)    # 08:00 EST, 08:00 EDT


# ---------------------------------------------------------------- GitHub

def test_github_asks_for_thirty_releases_and_pins_the_api_version(monkeypatch):
    sent = {}

    def fake(url, *, headers, **kw):
        sent.update(url=url, headers=headers)
        return []
    monkeypatch.setattr(gh.http, "get_json", fake)
    monkeypatch.setitem(config._cache, "watchlist", {"github": ["vercel/next.js"]})
    sources.get("github_release").collect({})
    assert sent["url"].endswith("/repos/vercel/next.js/releases?per_page=30")
    assert sent["headers"]["X-GitHub-Api-Version"] == gh.API_VERSION
    assert sent["headers"]["Accept"] == "application/vnd.github+json"


def test_github_finds_the_stable_release_behind_a_run_of_canaries(monkeypatch):
    """Six prereleases newer than the stable. With per_page=5 the stable was
    not on the page and the repo produced nothing."""
    def rel(tag, when, pre):
        return {"tag_name": tag, "draft": False, "prerelease": pre,
                "published_at": when, "html_url": f"https://gh/{tag}"}
    page = [rel(f"v16.4.0-canary.{i}", f"2026-09-0{9 - i}T00:00:00Z", True) for i in range(6)]
    page += [rel("v16.3.4", "2026-08-30T00:00:00Z", False),
             rel("v16.3.3", "2026-08-20T00:00:00Z", False)]
    monkeypatch.setattr(gh.http, "get_json", lambda url, **kw: page)
    monkeypatch.setitem(config._cache, "watchlist", {"github": ["vercel/next.js"]})
    got = sources.get("github_release").collect({})
    assert [(e.answer, e.predecessor) for e in got] == [("v16.3.4", "v16.3.3")]
