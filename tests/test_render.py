"""Render classification.

The control arm already fetches every page, so classifying where the fact
sits costs nothing. What it buys is the difference between "provider X is
slow" and "provider X does not execute JavaScript" — two conclusions a
pooled recall number cannot tell apart.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti import control
from tti.control import (
    RENDER_API,
    RENDER_HTML,
    RENDER_JSON,
    RENDER_NONE,
    classify_render,
    visible_text,
)
from tti.metrics import recall_by_render
from tti.models import ABSENT, FRESH, Event, ProbeResult

PAGE = """<html><head><title>next</title>
<script type="application/json" id="__NEXT_DATA__">{"version":"9.9.9"}</script>
<style>.v::after{content:"7.7.7"}</style>
</head><body><h1>Release 15.4.2</h1></body></html>"""


def test_visible_text_drops_scripts_styles_and_tags():
    t = visible_text(PAGE)
    assert "15.4.2" in t
    assert "9.9.9" not in t and "7.7.7" not in t
    assert "<h1>" not in t


@pytest.mark.parametrize("token,rank,expected", [
    ("15.4.2", 0, RENDER_HTML),
    ("9.9.9", 0, RENDER_JSON),     # only inside a script blob
    ("7.7.7", 0, RENDER_JSON),     # only inside a style block
    ("15.4.2", 1, RENDER_API),     # an API fallback answered, not the page
    ("1.2.3", 0, RENDER_NONE),
])
def test_classification(token, rank, expected):
    assert classify_render(PAGE, [token], rank) == expected


def test_v_prefix_rule_matches_the_grader():
    """If the control and the grader disagree about what counts as a match,
    the control's denominator stops describing the grader's numerator."""
    assert classify_render("<p>v15.4.2 shipped</p>", ["15.4.2"], 0) == RENDER_HTML
    assert classify_render("<p>115.4.2 shipped</p>", ["15.4.2"], 0) == RENDER_NONE
    assert classify_render("<p>15.4.20 shipped</p>", ["15.4.2"], 0) == RENDER_NONE


def test_api_rank_wins_even_when_the_token_is_visible():
    """Rank > 0 means the crawler-facing page did not answer, so no claim
    about its rendering is available."""
    assert classify_render("<h1>15.4.2</h1>", ["15.4.2"], 2) == RENDER_API


def _ev(i):
    return Event(source="npm", source_class="package_registry", subject=f"p{i}",
                 published_at=0.0, discovered_at=1.0, question="q",
                 answer=f"1.{i}.2", predecessor=f"1.{i}.1")


def _r(eid, provider, verdict, rung=3600, render=""):
    return ProbeResult(probe_id=f"{eid}{provider}{rung}", event_id=eid,
                       provider=provider, mode="base" if provider != "origin" else "direct",
                       rung=rung, requested_at=float(rung), lag=float(rung),
                       verdict=verdict, render=render)


def test_recall_splits_by_render_class():
    events = {}
    results = []
    # Three server-rendered facts (provider gets 2), two script-embedded (gets 0).
    for i, (cls, hit) in enumerate([(RENDER_HTML, True), (RENDER_HTML, True),
                                    (RENDER_HTML, False), (RENDER_JSON, False),
                                    (RENDER_JSON, False)]):
        e = _ev(i)
        events[e.event_id] = e
        results.append(_r(e.event_id, "origin", FRESH, render=cls))
        results.append(_r(e.event_id, "px", FRESH if hit else ABSENT))
    got = recall_by_render(events, results, "px", "base")
    assert got[RENDER_HTML] == (2, 3)
    assert got[RENDER_JSON] == (0, 2)


def test_unconfirmed_origins_are_excluded_from_the_denominator():
    """An origin that was blocked tells us nothing, so its event must not
    land in any render bucket."""
    e = _ev(0)
    events = {e.event_id: e}
    results = [_r(e.event_id, "origin", "ERROR", render=""),
               _r(e.event_id, "px", ABSENT)]
    assert recall_by_render(events, results, "px", "base") == {}


def test_phrasing_probes_do_not_inflate_render_recall():
    e = _ev(0)
    events = {e.event_id: e}
    base = [_r(e.event_id, "origin", FRESH, render=RENDER_HTML),
            _r(e.event_id, "px", ABSENT)]
    extra = ProbeResult(probe_id="ph", event_id=e.event_id, provider="px", mode="base",
                        rung=3600, requested_at=3600.0, lag=3600.0, verdict=FRESH,
                        phrasing=1)
    assert recall_by_render(events, base, "px", "base") == {RENDER_HTML: (0, 1)}
    assert recall_by_render(events, base + [extra], "px", "base") == {RENDER_HTML: (0, 1)}


def test_page_bodies_never_reach_the_stored_payload(monkeypatch):
    """The ledger must stay clonable. Bodies are used for classification and
    dropped; only the excerpt and a hash are kept."""
    monkeypatch.setattr(control, "robots_allows", lambda url, agent="*": True)
    monkeypatch.setattr(control.http, "get_text", lambda url, **kw: PAGE)
    e = Event(source="npm", source_class="package_registry", subject="p",
              published_at=0.0, discovered_at=1.0, question="q", answer="15.4.2",
              url="https://page.test/p")
    out = control.probe_origin(e)
    assert out["render"] == RENDER_HTML
    assert "body" not in out
    assert all("body" not in a for a in out["attempts"])
