"""`tti routes` must not characterise a site from one page.

First live run against pypi.org: seven of eight sampled routes were the same
3,036-byte "Client Challenge" interstitial, correctly excluded, and the line
beneath read "Uniformly readable across the sample". From one route.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti.cli import main
from tti.framework import PageProfile
from tti.routes import RouteSample
from tti.survey import SiteResult, Survey, _title


def _survey(n_usable: int, n_intercepted: int, title="Client Challenge") -> Survey:
    sv = Survey()
    for i in range(n_usable):
        sv.results.append(SiteResult(
            url=f"https://x.test/project/ok{i}/", category="route", status=200,
            prof=PageProfile(posture="static_html", bytes_total=9_000, visible_chars=900),
            body_sha=f"sha-ok-{i}", title=f"ok{i}"))
    for i in range(n_intercepted):
        sv.results.append(SiteResult(
            url=f"https://x.test/project/blocked{i}/", category="route", status=200,
            prof=PageProfile(posture="client_shell", bytes_total=3_036, visible_chars=20),
            body_sha="sha-challenge", title=title))
    sv.mark_identical_bodies()
    return sv


def _routes(n: int) -> RouteSample:
    """A real RouteSample, not a stub: `discovered` and `ok` are properties
    derived from `pages` and `sampled`, and a stub that set them as plain
    attributes was wrong in a way the real class cannot be."""
    pages = [f"https://x.test/project/p{i}/" for i in range(5000)]
    return RouteSample(site="https://x.test",
                       sitemap_urls=["https://x.test/sitemap.xml"],
                       pages=pages, sampled=pages[:n])


def _wire(monkeypatch, sv, n_sampled):
    # cmd_routes imports both modules inside the function, so patch the module
    # attributes; every import form resolves them at call time.
    import tti.routes as rt_mod
    import tti.survey as sv_mod
    monkeypatch.setattr(rt_mod, "discover", lambda site, **kw: _routes(n_sampled))
    monkeypatch.setattr(sv_mod, "run", lambda targets, **kw: sv)


def test_one_survivor_out_of_eight_is_not_a_site_wide_claim(monkeypatch, capsys):
    _wire(monkeypatch, _survey(1, 7), 8)
    assert main(["routes", "https://x.test", "--sample", "8"]) == 0
    out = capsys.readouterr().out
    assert "Uniformly readable" not in out
    assert "Only 1 of 8 sampled routes usable after exclusions" in out
    assert "too few to characterise the site" in out


def test_the_exclusion_line_names_the_body_size_and_title(monkeypatch, capsys):
    _wire(monkeypatch, _survey(1, 7), 8)
    main(["routes", "https://x.test", "--sample", "8"])
    out = capsys.readouterr().out
    assert "7 returned an identical 3,036-byte body titled 'Client Challenge'" in out
    assert "how this client was treated" in out


def test_three_usable_routes_still_get_a_verdict(monkeypatch, capsys):
    _wire(monkeypatch, _survey(3, 5), 8)
    main(["routes", "https://x.test", "--sample", "8"])
    out = capsys.readouterr().out
    assert "3/3 sampled routes readable" in out
    assert "Uniformly readable" in out
    assert "too few" not in out


def test_a_full_sample_with_nothing_excluded_is_unchanged(monkeypatch, capsys):
    _wire(monkeypatch, _survey(4, 0), 4)
    main(["routes", "https://x.test", "--sample", "4"])
    out = capsys.readouterr().out
    assert "4/4 sampled routes readable" in out
    assert "identical" not in out


def test_title_extraction_is_tolerant():
    assert _title("<html><head><title>  Client\n Challenge </title>") == "Client Challenge"
    assert _title("<TITLE lang=en>x</TITLE>") == "x"
    assert _title("<html><body>no title</body>") == ""
    assert _title("") == ""
    assert len(_title("<title>" + "y" * 500 + "</title>")) == 80


def test_intercepted_summary_omits_the_title_when_the_group_disagrees():
    sv = Survey()
    for i, t in enumerate(["A", "B"]):
        sv.results.append(SiteResult(
            url=f"https://x.test/{i}", category="route", status=200,
            prof=PageProfile(posture="client_shell", bytes_total=100, visible_chars=1),
            body_sha="same", title=t))
    sv.mark_identical_bodies()
    assert sv.intercepted_summary() == "2 returned an identical 100-byte body"
