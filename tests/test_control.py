"""Origin control arm.

The distinctions under test all collapse into "the provider missed it" if
they are got wrong, which is the single easiest way for this benchmark to
publish a number that blames a vendor for the open web.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti import control, http
from tti.models import Event


@pytest.fixture(autouse=True)
def no_robots(monkeypatch):
    monkeypatch.setattr(control, "robots_allows", lambda url, agent="*": True)
    control._robots_cache.clear()


def ev(**kw):
    base = dict(source="npm", source_class="package_registry", subject="p",
                published_at=0.0, discovered_at=1.0, question="q", answer="15.4.2",
                url="https://page.test/p")
    base.update(kw)
    return Event(**base)


def serve(mapping, monkeypatch):
    def fake(url, **kw):
        v = mapping.get(url)
        if isinstance(v, Exception):
            raise v
        if v is None:
            raise http.HttpError("404 not found")
        return v
    monkeypatch.setattr(control.http, "get_text", fake)


def test_found_records_an_excerpt_around_the_match(monkeypatch):
    serve({"https://page.test/p": "x" * 5000 + " release 15.4.2 shipped " + "y" * 5000},
          monkeypatch)
    r = control.probe_origin(ev())
    assert r["state"] == control.FOUND
    assert r["origin_rank"] == 0
    assert "15.4.2" in r["content"]
    assert len(r["content"]) < 1200          # a window, not the whole body
    assert r["attempts"][0]["sha256"]


def test_page_fetched_without_the_fact_is_not_found_not_error(monkeypatch):
    """A real page that does not contain the fact is a finding: nobody can
    index it from there. It must not be confused with a fetch failure."""
    serve({"https://page.test/p": "<html>loading…</html>"}, monkeypatch)
    r = control.probe_origin(ev())
    assert r["state"] == control.NOT_FOUND
    assert "loading" in r["content"]


def test_403_is_blocked_not_absent(monkeypatch):
    """The load-bearing distinction.

    An origin that refuses our client says nothing about whether a search
    crawler can fetch it. Recording that as "the fact was not on the web"
    would let a bot-walled origin make every provider look slow."""
    serve({"https://page.test/p": http.HttpError("403 Forbidden")}, monkeypatch)
    r = control.probe_origin(ev())
    assert r["state"] == control.BLOCKED


def test_robots_disallow_short_circuits_before_any_fetch(monkeypatch):
    monkeypatch.setattr(control, "robots_allows", lambda url, agent="*": False)
    calls = []
    monkeypatch.setattr(control.http, "get_text",
                        lambda url, **kw: calls.append(url) or "15.4.2")
    r = control.probe_origin(ev())
    assert r["state"] == control.DISALLOWED
    assert calls == []          # we did not fetch what we were told not to


def test_fallback_origin_is_used_and_its_rank_recorded(monkeypatch):
    """npm is the real case: the crawler-facing page 403s, the registry
    answers. The fallback is allowed, but it answers a weaker question and
    the record must say so."""
    serve({"https://page.test/p": http.HttpError("403 Forbidden"),
           "https://api.test/p": '{"version":"15.4.2"}'}, monkeypatch)
    r = control.probe_origin(ev(origins=["https://page.test/p", "https://api.test/p"]))
    assert r["state"] == control.FOUND
    assert r["origin_rank"] == 1
    assert r["origin_used"] == "https://api.test/p"
    assert [a["state"] for a in r["attempts"]] == [control.BLOCKED, control.FOUND]


def test_all_origins_failing_reports_blocked_over_error(monkeypatch):
    serve({"https://page.test/p": http.HttpError("403 Forbidden"),
           "https://api.test/p": http.HttpError("connection reset")}, monkeypatch)
    r = control.probe_origin(ev(origins=["https://page.test/p", "https://api.test/p"]))
    assert r["state"] == control.BLOCKED    # a policy statement beats a network blip


def test_boundary_matching_applies_to_the_origin_too(monkeypatch):
    serve({"https://page.test/p": "shipped 15.4.20 today"}, monkeypatch)
    r = control.probe_origin(ev(answer="15.4.2"))
    assert r["state"] == control.NOT_FOUND


def test_conditional_recall_excludes_unconfirmed_origins():
    from tti.models import ProbeResult

    def res(eid, provider, verdict, rung=3600):
        return ProbeResult(probe_id=f"{eid}{provider}{rung}", event_id=eid,
                           provider=provider, mode="direct" if provider == "origin" else "base",
                           rung=rung, requested_at=0.0, lag=float(rung), verdict=verdict)

    results = [
        res("a", "origin", "FRESH"), res("a", "px", "FRESH"),
        res("b", "origin", "FRESH"), res("b", "px", "ABSENT"),
        # Origin blocked: this event must not enter the denominator at all,
        # even though the provider missed it.
        res("c", "origin", "ERROR"), res("c", "px", "ABSENT"),
    ]
    hits, eligible = control.conditional_recall({}, results, "px", "base", 3600)
    assert (hits, eligible) == (1, 2)
