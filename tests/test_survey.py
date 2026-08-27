"""Survey aggregation."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti.framework import METADATA, NO_BODY, SHELL, SSR, STATIC, PageProfile
from tti.survey import SiteResult, Survey, markdown


def r(url, posture, category="x", status=200, blocked=None, checked=12, ratio=0.05,
      stable=True, seen=None):
    p = PageProfile(framework="next-app" if posture == SSR else "unknown",
                    posture=posture, bytes_total=10_000,
                    visible_chars=int(10_000 * ratio))
    return SiteResult(url=url, category=category, status=status, prof=p,
                      robots_blocked=blocked or [], robots_checked=checked,
                      stable=stable, postures_seen=seen or [posture])


def test_unreachable_targets_are_excluded_from_every_rate():
    """A survey that counts failed fetches as unreadable pages is measuring
    its own network."""
    sv = Survey([r("https://a", STATIC), r("https://b", SHELL),
                 SiteResult(url="https://c", error="ProxyError"),
                 r("https://d", NO_BODY, status=200)])
    assert sv.readable_rate() == (1, 2)
    assert len(sv.unreachable) == 2


def test_readable_postures():
    sv = Survey([r("https://a", SSR), r("https://b", STATIC), r("https://c", SHELL)])
    assert sv.readable_rate() == (2, 3)
    assert sv.by_posture()[SHELL] == 1


def test_open_but_unreadable_is_the_headline_category():
    """A page that allows every AI crawler and serves them a shell. Nobody
    chose it; it falls out of a default, and the robots.txt records that the
    team wanted the opposite."""
    sv = Survey([
        r("https://open-shell", SHELL, blocked=[]),          # invites, serves nothing
        r("https://closed-shell", SHELL, blocked=["GPTBot", "CCBot"]),  # a choice
        r("https://open-ssr", SSR, blocked=[]),              # fine
    ])
    exposed = [x.url for x in sv.open_but_unreadable()]
    assert exposed == ["https://open-shell"]


def test_a_site_that_blocks_crawlers_is_not_counted_as_a_failure():
    sv = Survey([r("https://a", SHELL, blocked=["GPTBot"] * 12)])
    assert sv.open_but_unreadable() == []


def test_robots_never_checked_is_not_treated_as_permissive():
    sv = Survey([r("https://a", SHELL, blocked=[], checked=0)])
    assert sv.open_but_unreadable() == []


def test_breakdowns_and_markdown():
    sv = Survey([r("https://a", SSR, category="docs"),
                 r("https://b", SHELL, category="docs"),
                 r("https://c", STATIC, category="registry")])
    assert sv.by_category()["docs"] == (1, 2)
    assert sv.by_category()["registry"] == (1, 1)
    md = markdown(sv)
    assert "2 of 3 pages" in md and "client_shell" in md


def test_metadata_only_is_neither_readable_nor_counted_as_content():
    """A page that ships JSON-LD over a shell tells an agent what it is and
    not what it says. Counting it as readable would let a registry that hides
    its version table behind hydration score as fine."""
    sv = Survey([r("https://a", METADATA), r("https://b", STATIC)])
    assert sv.readable_rate() == (1, 2)
    assert [x.url for x in sv.metadata_only()] == ["https://a"]


def test_open_and_empty_excludes_pages_that_ship_metadata():
    """The strict headline claim. Overstating it by one site is how a survey
    stops being believed."""
    sv = Survey([
        r("https://empty", SHELL, blocked=[]),
        r("https://partial", METADATA, blocked=[]),
        r("https://fine", STATIC, blocked=[]),
    ])
    assert [x.url for x in sv.open_and_empty()] == ["https://empty"]
    assert {x.url for x in sv.open_but_unreadable()} == {"https://empty",
                                                         "https://partial"}


def test_a_site_that_answers_differently_across_fetches_is_excluded():
    """Observed in development: the same URL returned 5,056 bytes of client
    shell on one run and a zero-byte 404 on the next. A verdict about
    somebody's site must not rest on one request."""
    sv = Survey([
        r("https://flaky", SHELL, stable=False, seen=["client_shell", "HTTP404"]),
        r("https://solid", STATIC),
    ])
    assert sv.readable_rate() == (1, 1)
    assert [x.url for x in sv.unstable] == ["https://flaky"]
    assert sv.results[0].verdict == "unstable"
    assert "disagreed" in sv.results[0].why_unusable


def test_unstable_pages_cannot_reach_the_headline_claim():
    sv = Survey([r("https://flaky", SHELL, blocked=[], stable=False,
                   seen=["client_shell", "error"])])
    assert sv.open_and_empty() == []
    assert sv.open_but_unreadable() == []


# ---------------------------------------------------------------------------
# The rendered corpus page
# ---------------------------------------------------------------------------

def test_the_corpus_page_refuses_what_the_terminal_refuses():
    """Whatever the CLI declines to claim, the page must decline too.
    A rendered artifact is the version that gets screenshotted."""
    from tti import report
    from tti.framework import METADATA

    sv = Survey([
        r("https://good/a", STATIC, category="docs", ratio=0.2),
        r("https://shell/b", SHELL, category="docs", ratio=0.001, blocked=[]),
        r("https://meta/c", METADATA, category="registry", ratio=0.01, blocked=[]),
        SiteResult(url="https://dead/d", error="ProxyError"),
        r("https://flaky/e", SHELL, stable=False, seen=["client_shell", "error"]),
    ])
    sv.results[-1].body_sha = ""
    html = report.corpus_html(sv)

    assert ">1 of 3</span> pages were readable" in html
    # The shell page invites every crawler and ships nothing: the headline.
    assert "ship them nothing at all" in html
    assert "https://shell/b" in html
    # Excluded targets are named as excluded, never folded into the rate.
    assert "Excluded from" in html
    assert "measuring its own network" in html
    # Metadata is a third state, not a pardon.
    assert "metadata_only" in html


def test_the_corpus_page_does_not_overclaim_from_one_run():
    from tti import report
    from tti.watch import Coverage

    sv = Survey([r("https://a", STATIC)])
    cov = Coverage(urls=1, runs=2, first=0.0, last=3600.0, judged_rate=1.0)
    html = report.corpus_html(sv, {}, [], cov)
    assert "describes the observation window" in html


def test_the_corpus_page_escapes_hostile_urls():
    """URLs come from a corpus file and from sitemaps, so they are not
    trusted input. What matters is that no raw angle bracket from that data
    reaches the document — the payload appearing as escaped *text* is the
    correct outcome, not a failure."""
    from tti import report
    sv = Survey([r('https://x/"><img src=x onerror=alert(1)>', STATIC)])
    html = report.corpus_html(sv)
    assert "<img" not in html            # no element was created
    assert "&lt;img src=x onerror=alert(1)&gt;" in html   # it is inert text
