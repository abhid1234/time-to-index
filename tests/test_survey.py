"""Survey aggregation."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti.framework import NO_BODY, SHELL, SSR, STATIC, PageProfile
from tti.survey import SiteResult, Survey, markdown


def r(url, posture, category="x", status=200, blocked=None, checked=12, ratio=0.05):
    p = PageProfile(framework="next-app" if posture == SSR else "unknown",
                    posture=posture, bytes_total=10_000,
                    visible_chars=int(10_000 * ratio))
    return SiteResult(url=url, category=category, status=status, prof=p,
                      robots_blocked=blocked or [], robots_checked=checked)


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
