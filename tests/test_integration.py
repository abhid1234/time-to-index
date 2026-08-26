"""The whole pipeline, offline, through the real CLI.

Every layer here was unit-tested and a real bug still shipped: `tti report`
referenced an undefined name, and the suite did not notice because nothing
ran the CLI. These tests drive `main(argv)` through the actual argument
parser against a local origin, so the wiring is covered and not just the
parts.
"""
from __future__ import annotations

import json
import time

import pytest

from tti import config
from tti.cli import main
from tti.ledger import Ledger
from tti.models import FRESH, STALE

# ---------------------------------------------------------------------------
# Collection against a local registry
# ---------------------------------------------------------------------------

def test_discover_collects_a_freshly_published_release(wired, tmp_path, monkeypatch):
    now = time.time()
    wired.publish_npm("demo", [("1.0.0", now - 90_000), ("1.0.1", now - 20)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["demo"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300, 900], "origin_control": False, "arms": []})

    from tti import scheduler
    led = Ledger(tmp_path)
    rep = scheduler.discover(led, verbose=False)
    assert rep.new_events == 1
    ev = next(iter(led.events().values()))
    assert (ev.answer, ev.predecessor) == ("1.0.1", "1.0.0")
    assert "demo" in ev.question


def test_a_release_published_long_ago_is_dropped_not_probed(wired, tmp_path, monkeypatch):
    """Cold start. On the first poll every watched package looks new but
    shipped days ago, and its ladder cannot be honoured."""
    now = time.time()
    wired.publish_npm("stale", [("2.0.0", now - 400_000), ("2.0.1", now - 200_000)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["stale"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300], "origin_control": False, "arms": []})

    from tti import scheduler
    led = Ledger(tmp_path)
    rep = scheduler.discover(led, verbose=False)
    assert (rep.collected, rep.new_events, rep.dropped_late) == (1, 0, 1)


def test_an_unreachable_source_is_reported_not_silently_empty(tmp_path, monkeypatch):
    from tti import scheduler
    from tti.sources import npm as npm_mod
    monkeypatch.setattr(npm_mod, "API", "http://127.0.0.1:1/npm/{pkg}")
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["a", "b"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300], "origin_control": False, "arms": []})

    rep = scheduler.discover(Ledger(tmp_path), verbose=False)
    assert rep.broken_sources == ["npm"]
    assert rep.new_events == 0


# ---------------------------------------------------------------------------
# Probing end to end, including the origin control
# ---------------------------------------------------------------------------

def _stub_provider(monkeypatch, answers: dict[int, str]):
    """A provider that returns `answers[rung]` as its snippet."""
    from tti import scheduler

    class Stub:
        name = "stub"
        calls: list[tuple[str, int]] = []

        def modes(self): return ["base"]
        def available(self): return True

        def search(self, question, mode, *, max_results, max_chars):
            rung = Stub._rung
            Stub.calls.append((question, rung))
            return {"results": [{"url": "https://x", "snippet": answers.get(rung, "")}]}

    stub = Stub()
    real_get = scheduler.providers.get
    monkeypatch.setattr(scheduler.providers, "get",
                        lambda n: stub if n == "stub" else real_get(n))
    return Stub


def test_full_ladder_with_origin_control(wired, tmp_path, monkeypatch):
    """Discover, walk the ladder, grade, and score — with the control arm on
    and a real HTTP origin behind it."""
    from tti import scheduler
    from tti.metrics import score

    now = time.time()
    # Versions match the fixture page at /page/ssr, so the control arm is
    # looking for the same token the collector produced.
    wired.publish_npm("demo", [("9.9.8", now - 90_000), ("9.9.9", now - 5)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["demo"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300, 900, 3600], "origin_control": True,
        "max_results": 5, "max_chars_per_result": 500,
        "max_rung_slip_seconds": 10 ** 9, "daily_usd_cap": 100.0,
        "arms": [{"provider": "stub", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers", {"providers": {"stub": {"modes": {
        "base": {"usd_per_1k_requests": 1.0, "results_included": 5}}}}})
    monkeypatch.setattr(scheduler.providers, "available_arms", lambda: [("stub", "base")])

    led = Ledger(tmp_path)
    rep = scheduler.discover(led, verbose=False)
    assert rep.new_events == 1
    ev = next(iter(led.events().values()))
    # Point the control arm at a page that contains the new version.
    ev.origins = [wired.base + "/page/ssr"]
    led.events_path.write_text(json.dumps(ev.to_dict()) + "\n")

    Stub = _stub_provider(monkeypatch, {300: "still on 9.9.8", 900: "still on 9.9.8",
                                        3600: "now at 9.9.9"})
    for rung in (300, 900, 3600):
        Stub._rung = rung
        scheduler.run_due(led, now=ev.published_at + rung, verbose=False)

    by = {(r.provider, r.rung): r for r in led.results()}
    assert by[("stub", 300)].verdict == STALE
    assert by[("stub", 900)].verdict == STALE
    assert by[("stub", 3600)].verdict == FRESH
    # The control fetched a real page over HTTP and found the answer in it.
    assert by[("origin", 300)].verdict == FRESH
    assert by[("origin", 300)].render == "server_html"
    assert by[("origin", 300)].cost_usd == 0.0

    sc = score(led.events(), led.results(), "stub", "base")
    assert sc.n_events == 1 and sc.n_indexed == 1
    assert sc.median_bracket == (900.0, 3600.0)
    assert sc.n_stale == 2


def test_a_blocked_origin_is_an_error_not_an_absent(wired, tmp_path, monkeypatch):
    """The control must never assert 'the fact was not on the web' from a
    fetch it could not make."""
    from tti import control
    from tti.models import Event

    ev = Event(source="npm", source_class="package_registry", subject="demo",
               published_at=time.time(), discovered_at=time.time(),
               question="q", answer="9.9.9",
               origins=["http://127.0.0.1:1/nope"])
    out = control.probe_origin(ev)
    assert out["state"] in (control.BLOCKED, control.ERROR)
    assert out["state"] != control.NOT_FOUND


# ---------------------------------------------------------------------------
# The CLI, through its real parser
# ---------------------------------------------------------------------------

def test_cli_status_and_probe_dry_run_on_an_empty_ledger(tmp_path, capsys):
    assert main(["--run-dir", str(tmp_path), "status"]) == 0
    assert main(["--run-dir", str(tmp_path), "probe", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "events" in out and "budget" in out


def test_cli_score_and_report_refuse_an_empty_ledger(tmp_path, capsys):
    """A report over no data must decline rather than render an empty
    leaderboard that looks like a result."""
    assert main(["--run-dir", str(tmp_path), "score"]) == 1
    assert main(["--run-dir", str(tmp_path), "report",
                 "--out-dir", str(tmp_path / "out")]) == 1
    assert "no results" in capsys.readouterr().out


def test_cli_demo_renders_and_checks_the_estimator(capsys, tmp_path):
    """`tti demo` is a CI step precisely because it fails when the statistics
    stop recovering their own ground truth."""
    assert main(["demo", "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "MISS" not in out
    assert out.count("OK ") == 3


def test_cli_report_writes_a_dashboard_after_a_run(tmp_path, monkeypatch, capsys):
    from tti import demo
    demo.generate(tmp_path, [300, 900, 3600, 21600, 86400, 259200])
    assert main(["--run-dir", str(tmp_path), "score"]) == 0
    assert "median TTI" in capsys.readouterr().out
    assert main(["--run-dir", str(tmp_path), "report",
                 "--out-dir", str(tmp_path / "out")]) == 0
    assert main(["--run-dir", str(tmp_path), "power"]) == 0
    # sensitivity succeeds and reports honestly that it had nothing to
    # re-grade, rather than failing or claiming perfect agreement.
    assert main(["--run-dir", str(tmp_path), "sensitivity"]) == 0
    out = capsys.readouterr().out
    assert "index.html" in out and "hazard ratio" in out
    assert "no stored payloads to re-grade" in out


def test_cli_placeholder_page_says_no_run_has_happened(capsys, tmp_path):
    assert main(["placeholder", "--out-dir", str(tmp_path)]) == 0
    page = (tmp_path / "index.html").read_text()
    assert "No run has happened yet" in page
    assert "<!doctype html>" in page.lower()


def test_cli_crawlability_against_each_posture(origin, capsys):
    rc = main(["crawlability", origin.base + "/page/ssr",
               origin.base + "/page/shell", origin.base + "/page/metadata",
               "--find", "9.9.9"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "READABLE" in out and "NOT READABLE" in out and "PARTIAL" in out
    assert "is in the readable HTML" in out


def test_cli_crawlability_json_is_machine_readable(origin, capsys):
    assert main(["crawlability", origin.base + "/page/ssr", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["verdict"] == "readable"
    assert rows[0]["posture"] == "static_html"
    assert rows[0]["robots"]["GPTBot"] is True


def test_cli_crawlability_reports_a_bad_fetch_as_a_fetch_failure(origin, capsys):
    """A 404 is not a verdict about a site's rendering."""
    assert main(["crawlability", origin.base + "/definitely-missing"]) == 0
    assert "could not fetch" in capsys.readouterr().out


def test_cli_survey_excludes_a_target_that_answers_differently(origin, capsys):
    """`/flaky` alternates 200 and 404 — exactly what broke single-fetch
    verdicts against the real web."""
    rc = main(["survey", origin.base + "/page/ssr", origin.base + "/flaky",
               "--repeat", "2", "--workers", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 of 1 pages readable" in out
    assert "unstable" in out


def test_cli_survey_respects_a_robots_block(origin, capsys):
    from tests.conftest import ROBOTS_BLOCK_AI
    origin.robots = ROBOTS_BLOCK_AI
    assert main(["survey", origin.base + "/page/shell", "--repeat", "1"]) == 0
    out = capsys.readouterr().out
    # It blocks AI agents, so it is not in the "invites them and ships
    # nothing" category. That is a choice, and choices are not failures.
    assert "ship them nothing at all" not in out


@pytest.mark.parametrize("cmd", [
    ["status"], ["probe", "--dry-run"], ["score"], ["regrade"], ["sensitivity"],
])
def test_every_ledger_command_survives_an_empty_run_dir(cmd, tmp_path):
    """No command may traceback on a fresh clone."""
    rc = main(["--run-dir", str(tmp_path), *cmd])
    assert rc in (0, 1)


def test_the_test_suite_does_not_write_into_the_repo(tmp_path):
    """A suite that dirties the working tree makes `git status` useless as a
    signal and will eventually commit a rendered page by accident."""
    import pathlib
    import subprocess
    root = pathlib.Path(__file__).resolve().parent.parent
    if not (root / ".git").exists():
        pytest.skip("not a git checkout")
    dirty = subprocess.run(["git", "status", "--porcelain", "docs", "RESULTS.md"],
                           cwd=root, capture_output=True, text=True).stdout.strip()
    assert dirty == "", f"tests modified tracked files:\n{dirty}"
