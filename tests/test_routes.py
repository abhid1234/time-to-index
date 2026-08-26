"""Route sampling and interception detection.

The interception tests are the important ones. Six different PyPI project
URLs returned byte-identical 3,036-byte bodies with HTTP 200 during
development, and without a guard the tool reported that PyPI is entirely
client-rendered — which is false, and would have been false in public. CDN
challenge pages, WAF blocks and soft-404s all behave exactly this way.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti.framework import SSR, STATIC, PageProfile
from tti.routes import stratified
from tti.survey import SiteResult, Survey


def res(url, sha, status=200, ratio=0.05):
    p = PageProfile(posture=STATIC, bytes_total=10_000,
                    visible_chars=int(10_000 * ratio), body_sha=sha)
    return SiteResult(url=url, status=status, prof=p, body_sha=sha)


def test_identical_bodies_across_distinct_urls_are_all_excluded():
    """Not all-but-one. Keeping a representative assumes one of them is the
    real page, and in the interception case none of them is."""
    sv = Survey([res("https://s/a", "SAME"), res("https://s/b", "SAME"),
                 res("https://s/c", "SAME"), res("https://s/real", "DIFFERENT")])
    flagged = sv.mark_identical_bodies()
    assert flagged == 3
    assert len(sv.intercepted) == 3
    assert sv.readable_rate() == (1, 1)
    assert all(r.verdict == "intercepted" for r in sv.intercepted)


def test_the_same_url_fetched_twice_is_not_an_interception():
    """Repeat fetches of one URL share a hash by design."""
    sv = Survey([res("https://s/a", "SAME"), res("https://s/a", "SAME")])
    assert sv.mark_identical_bodies() == 0
    assert sv.intercepted == []


def test_distinct_bodies_are_left_alone():
    sv = Survey([res("https://s/a", "A"), res("https://s/b", "B")])
    assert sv.mark_identical_bodies() == 0
    assert sv.readable_rate() == (2, 2)


def test_non_200_responses_are_not_grouped():
    """A shared 404 body is already excluded for being a 404; grouping it
    would double-count the reason."""
    sv = Survey([res("https://s/a", "SAME", status=404),
                 res("https://s/b", "SAME", status=404)])
    assert sv.mark_identical_bodies() == 0


def test_why_unusable_names_the_peer():
    sv = Survey([res("https://s/a", "S"), res("https://s/b", "S")])
    sv.mark_identical_bodies()
    assert "byte-identical body to" in sv.results[0].why_unusable


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def test_stratified_sampling_is_deterministic_and_spread():
    urls = [f"https://s/{c}/{i:03d}" for c in "abcde" for i in range(100)]
    a = stratified(urls, 10)
    b = stratified(list(reversed(urls)), 10)
    assert a == b, "sample must not depend on input order"
    assert len(a) == 10
    # Spread across directories rather than 10 pages from one of them, which
    # is what urls[:n] gives on almost every sitemap.
    assert len({u.split("/")[3] for u in a}) >= 4


def test_stratified_handles_small_and_empty_inputs():
    assert stratified([], 5) == []
    assert stratified(["https://s/a"], 5) == ["https://s/a"]
    assert stratified(["https://s/a", "https://s/b"], 0) == []


def test_stratified_deduplicates():
    assert stratified(["https://s/a", "https://s/a", "https://s/b"], 5) == \
        ["https://s/a", "https://s/b"]


# ---------------------------------------------------------------------------
# Sitemap discovery, against the local origin
# ---------------------------------------------------------------------------

def test_discovery_reports_when_a_site_declares_nothing(origin):
    from tti import routes
    rs = routes.discover(origin.base)
    assert not rs.ok
    assert rs.pages == []
    assert "no sitemap" in rs.note


def test_sample_of_a_site_without_a_sitemap_is_empty_not_guessed(origin):
    """No sitemap means no route list. Guessing paths would invent a sample
    frame and quietly make the resulting rate meaningless."""
    from tti import routes
    rs = routes.sample(origin.base, 5)
    assert rs.sampled == []
