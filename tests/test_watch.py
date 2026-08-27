"""Crawlability over time.

A single scan says a page is unreadable today. It cannot say the page used to
be readable, which is the actionable statement — nobody decides to become
invisible to agents, they ship a refactor and no signal turns red.

The pairing rules are what these tests protect. Compare the wrong pairs and
the report fills with transitions that describe the network rather than the
web, which is the same failure this project keeps guarding against.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


from tti import watch as w
from tti.framework import STATIC, PageProfile
from tti.survey import SiteResult, Survey

DAY = 86_400.0


def write(tmp_path, rows):
    with open(w.path(tmp_path), "w", encoding="utf-8") as fh:
        for url, at, judged, posture, chars in rows:
            fh.write(json.dumps({
                "at": at, "url": url, "judged": judged, "posture": posture,
                "visible_chars": chars}) + "\n")
    return w.history(tmp_path)


def test_a_posture_regression_is_detected(tmp_path):
    hist = write(tmp_path, [
        ("https://a", 0 * DAY, True, "static_html", 9000),
        ("https://a", 1 * DAY, True, "static_html", 9100),
        ("https://a", 2 * DAY, True, "client_shell", 40),
    ])
    ch = w.changes(hist)
    assert len(ch) == 1
    assert (ch[0].kind, ch[0].before, ch[0].after) == ("posture", "static_html",
                                                       "client_shell")
    assert ch[0].worsened


def test_an_unreachable_run_does_not_create_two_transitions(tmp_path):
    """readable -> unreachable -> readable is not two changes. Pairing
    unjudged observations fills the report with the network's behaviour."""
    hist = write(tmp_path, [
        ("https://b", 0 * DAY, True, "static_html", 5000),
        ("https://b", 1 * DAY, False, "no_body", 0),
        ("https://b", 2 * DAY, True, "static_html", 5200),
    ])
    assert w.changes(hist) == []


def test_a_text_collapse_without_a_posture_change_is_reported(tmp_path):
    """What a partial migration looks like: the label holds, the content
    leaves."""
    hist = write(tmp_path, [
        ("https://c", 0 * DAY, True, "server_rendered", 40_000),
        ("https://c", 1 * DAY, True, "server_rendered", 1_200),
    ])
    ch = w.changes(hist)
    assert len(ch) == 1 and ch[0].kind == "text_drop" and ch[0].worsened
    assert "40,000 to 1,200" in ch[0].describe()


def test_ordinary_editing_is_not_a_regression(tmp_path):
    """Pages get rewritten constantly. Only a collapse counts."""
    hist = write(tmp_path, [
        ("https://d", 0 * DAY, True, "static_html", 9000),
        ("https://d", 1 * DAY, True, "static_html", 6000),
        ("https://d", 2 * DAY, True, "static_html", 11_000),
    ])
    assert w.changes(hist) == []


def test_a_tiny_page_getting_tinier_is_not_flagged(tmp_path):
    """Below the floor, ratios are noise: 60 characters to 10 is not a
    finding, it is a page that never had content."""
    hist = write(tmp_path, [
        ("https://e", 0 * DAY, True, "client_shell", 60),
        ("https://e", 1 * DAY, True, "client_shell", 10),
    ])
    assert w.changes(hist) == []


def test_an_improvement_is_recorded_but_not_a_regression(tmp_path):
    hist = write(tmp_path, [
        ("https://f", 0 * DAY, True, "client_shell", 40),
        ("https://f", 1 * DAY, True, "static_html", 9000),
    ])
    ch = w.changes(hist)
    assert len(ch) == 1 and not ch[0].worsened


def test_metadata_only_counts_as_a_regression_from_readable(tmp_path):
    hist = write(tmp_path, [
        ("https://g", 0 * DAY, True, "static_html", 9000),
        ("https://g", 1 * DAY, True, "metadata_only", 300),
    ])
    assert w.changes(hist)[0].worsened


def test_coverage_reports_the_window_so_a_report_cannot_overclaim(tmp_path):
    """Two runs an hour apart show no change, and 'no site changed posture'
    from that describes the window, not the web."""
    hist = write(tmp_path, [
        ("https://h", 0.0, True, "static_html", 900),
        ("https://h", 3600.0, True, "static_html", 900),
    ])
    cov = w.coverage(hist)
    assert cov.runs == 2 and cov.span_days < 1 and cov.judged_rate == 1.0


def test_urls_never_judged_are_named(tmp_path):
    hist = write(tmp_path, [
        ("https://ok", 0.0, True, "static_html", 900),
        ("https://never", 0.0, False, "no_body", 0),
        ("https://never", DAY, False, "no_body", 0),
    ])
    assert w.coverage(hist).never_judged == ["https://never"]


def test_record_round_trips_a_survey(tmp_path):
    prof = PageProfile(framework="next-app", posture=STATIC, bytes_total=1000,
                       visible_chars=800, body_sha="abc")
    sv = Survey([
        SiteResult(url="https://a", category="docs", status=200, prof=prof,
                   body_sha="abc"),
        SiteResult(url="https://b", error="ProxyError"),
    ])
    assert w.record(sv, tmp_path, now=DAY) == 2
    hist = w.history(tmp_path)
    assert hist["https://a"][0].judged is True
    assert hist["https://a"][0].posture == STATIC
    assert hist["https://b"][0].judged is False
    assert "ProxyError" in hist["https://b"][0].why_unusable


def test_history_survives_a_corrupt_line(tmp_path):
    """An unattended appender will eventually be interrupted mid-write. One
    torn line must not discard the series."""
    p = w.path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"at": 0.0, "url": "https://a", "judged": True,
                    "posture": "static_html", "visible_chars": 10}) + "\n"
        + '{"at": 1.0, "url": "https:/' + "\n"
        + json.dumps({"at": 2.0, "url": "https://a", "judged": True,
                      "posture": "client_shell", "visible_chars": 5}) + "\n")
    hist = w.history(tmp_path)
    assert len(hist["https://a"]) == 2
    assert w.changes(hist)[0].worsened


def test_records_append_across_runs(tmp_path):
    prof = PageProfile(posture=STATIC, bytes_total=1000, visible_chars=800)
    sv = Survey([SiteResult(url="https://a", status=200, prof=prof)])
    w.record(sv, tmp_path, now=0.0)
    w.record(sv, tmp_path, now=DAY)
    assert len(w.history(tmp_path)["https://a"]) == 2


def test_cli_watch_reports_and_refuses_to_overclaim(tmp_path, origin, capsys):
    from tti.cli import main
    rc = main(["--run-dir", str(tmp_path), "watch",
               origin.base + "/page/ssr", "--repeat", "1", "--workers", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "recorded 1 observations" in out
    assert "One run is not a series" in out


def test_cli_watch_report_only_needs_history(tmp_path, capsys):
    from tti.cli import main
    assert main(["--run-dir", str(tmp_path), "watch", "--report"]) == 1
    assert "no history yet" in capsys.readouterr().out
