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


from tti.framework import STATIC, PageProfile
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


# ---------------------------------------------------------------------------
# Sitemap parsing, over real HTTP
# ---------------------------------------------------------------------------

def test_a_plain_sitemap_is_discovered_and_sampled(origin):
    from tti import routes
    origin.serve_sitemap = True
    rs = routes.sample(origin.base, 6)
    assert rs.discovered == 40
    assert len(rs.sampled) == 6
    assert all(u.startswith(origin.base + "/page/r") for u in rs.sampled)


def test_a_gzipped_sitemap_is_transparently_decompressed(origin):
    """Large sites commonly serve sitemap.xml.gz, often with no `.gz` in the
    declared URL and no helpful Content-Type. Read as text it parses as
    nothing, which is indistinguishable from a site that declares no routes."""
    from tti import routes
    origin.serve_gzip_sitemap = True          # only the .gz path answers
    rs = routes.sample(origin.base, 5)
    assert rs.discovered == 40, "gzipped sitemap was not decompressed"
    assert len(rs.sampled) == 5


def test_decode_handles_garbage_without_raising():
    from tti.routes import _decode_sitemap
    assert _decode_sitemap(b"\x1f\x8bnot actually gzip") == ""
    assert "hello" in _decode_sitemap(b"hello")
    assert _decode_sitemap(b"\xff\xfe\x00bad utf8") != ""     # replaced, not raised


def test_a_sitemap_index_is_expanded_one_level(origin, monkeypatch):
    from tti import routes
    origin.serve_index = True
    monkeypatch.setattr(routes, "_sitemaps_from_robots",
                        lambda base: [base + "/sitemap-index.xml"])
    rs = routes.discover(origin.base)
    # The child lists one foreign host and one same-host page; only the
    # same-host one may be kept.
    assert rs.pages == [origin.base + "/page/ssr"]


def test_foreign_hosts_in_a_sitemap_are_dropped(origin, monkeypatch):
    """A sitemap may legitimately list a CDN or a docs subdomain. Judging
    those pages as this site's would attribute someone else's rendering."""
    from tti import routes
    origin.serve_index = True
    monkeypatch.setattr(routes, "_sitemaps_from_robots",
                        lambda base: [base + "/sitemap-child.xml"])
    rs = routes.discover(origin.base)
    assert all("cdn.example.net" not in u for u in rs.pages)


def test_routes_of_a_site_with_distinct_pages_are_all_judged(origin, capsys):
    """End-to-end: sitemap -> sample -> profile, with genuinely distinct
    bodies so the interception guard does not fire."""
    from tti.cli import main
    origin.serve_sitemap = True
    assert main(["routes", origin.base, "--sample", "4", "--repeat", "1"]) == 0
    out = capsys.readouterr().out
    assert "4/4 sampled routes readable" in out
    assert "Uniformly readable" in out
    assert "identical to another route" not in out
