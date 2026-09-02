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


def test_a_dry_discover_reports_what_a_real_one_would_do_and_writes_nothing(
        wired, tmp_path, monkeypatch):
    """The test that matters is not "the files are empty" -- it is that the
    real run afterwards is unchanged. A dry run that quietly advanced the
    per-subject high-water mark would leave the files empty too, and the
    event it described would never be collected."""
    now = time.time()
    wired.publish_npm("demo", [("1.0.0", now - 90_000), ("1.0.1", now - 20)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["demo"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300, 900], "origin_control": False,
        "arms": [{"provider": "stub", "mode": "base"}]})

    from tti import scheduler
    monkeypatch.setattr(scheduler.providers, "available_arms",
                        lambda: [("stub", "base")])
    led = Ledger(tmp_path)
    dry = scheduler.discover(led, verbose=False, dry_run=True)
    assert dry.dry_run is True
    assert (dry.collected, dry.new_events, dry.probes_queued) == (1, 1, 2)
    assert [(src, subj, ans) for src, subj, ans, _ in dry.preview] \
        == [("npm", "demo", "1.0.1")]

    # Nothing on disk, and nothing remembered.
    assert led.events() == {}
    assert led.probes() == {}
    assert led.seen_subjects() == {}

    real = scheduler.discover(led, verbose=False)
    assert (real.collected, real.new_events, real.probes_queued) == \
        (dry.collected, dry.new_events, dry.probes_queued)
    assert real.dry_run is False and real.preview == []


def test_a_dry_discover_does_not_re_offer_events_already_in_the_ledger(
        wired, tmp_path, monkeypatch):
    """`new_events` in a dry run means "new to the ledger", the same thing it
    means in a real one. If it counted everything collected, a second dry run
    would claim work that a real run would skip."""
    now = time.time()
    wired.publish_npm("demo", [("1.0.0", now - 90_000), ("1.0.1", now - 20)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["demo"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300], "origin_control": False,
        "arms": [{"provider": "stub", "mode": "base"}]})

    from tti import scheduler
    monkeypatch.setattr(scheduler.providers, "available_arms",
                        lambda: [("stub", "base")])
    led = Ledger(tmp_path)
    assert scheduler.discover(led, verbose=False).new_events == 1
    again = scheduler.discover(led, verbose=False, dry_run=True)
    assert (again.new_events, again.probes_queued) == (0, 0)
    assert again.preview == []


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
    # Each row now carries the moment its own call went out, so the bracket
    # edges are the observed lags (a few ms past the rung here), not the rungs.
    lo, hi = sc.median_bracket
    assert abs(lo - 900.0) < 1.0 and abs(hi - 3600.0) < 1.0
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
    # payloads=False: a ledger whose raw payloads are missing is a state a
    # real run can be in (disk pruned, directory copied without runs/raw/).
    demo.generate(tmp_path, [300, 900, 3600, 21600, 86400, 259200], payloads=False)
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


def test_the_default_demo_ledger_evaluates_every_variant(tmp_path, capsys):
    from tti import demo
    demo.generate(tmp_path, [300, 900, 3600, 21600, 86400, 259200])
    assert (tmp_path / "raw" / "provider-a").is_dir()
    assert main(["--run-dir", str(tmp_path), "sensitivity"]) == 0
    out = capsys.readouterr().out
    assert "no stored payloads" not in out
    assert "snippet-window" in out and "titles-only" in out


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

    from conftest import WORKING_TREE_AT_COLLECTION, _porcelain
    root = pathlib.Path(__file__).resolve().parent.parent
    if not (root / ".git").exists():
        pytest.skip("not a git checkout")
    now = _porcelain()
    if now == WORKING_TREE_AT_COLLECTION:
        return
    before = set(WORKING_TREE_AT_COLLECTION.splitlines())
    added = [ln for ln in now.splitlines() if ln not in before]
    assert not added, (
        "tests modified tracked files under docs/ or RESULTS.md:\n"
        + "\n".join(added))


def test_the_control_arm_never_appears_in_the_leaderboard(tmp_path, capsys):
    """It fetches the canonical URL directly, so it has near-perfect recall
    at zero cost by construction. Listing it beside the providers invites the
    exact comparison it exists to make unnecessary.

    This exclusion was written once and silently lost to a later edit, and
    nothing caught it: the demo filters its own arms, so only a real run
    would have shown the control sitting at the top of the table.
    """
    import json as _json

    from tti import demo
    demo.generate(tmp_path, [300, 900, 3600, 21600, 86400, 259200])

    assert main(["--run-dir", str(tmp_path), "score", "--json"]) == 0
    arms = _json.loads(capsys.readouterr().out)["arms"]
    assert arms, "expected some provider arms"
    assert not any(a["provider"] == "origin" for a in arms)

    out_dir = tmp_path / "pages"
    assert main(["--run-dir", str(tmp_path), "report",
                 "--out-dir", str(out_dir)]) == 0
    html = (out_dir / "index.html").read_text()
    assert "origin/direct</td>" not in html
    # ...but the control's own panel must still be there.
    assert "The control arm" in html


def test_score_json_is_strictly_parseable(tmp_path, capsys):
    """`json.dumps` emits bare NaN and Infinity by default. Python reads them
    back happily and almost nothing else does, so a consumer gets a parse
    error or a silently coerced token."""
    import json as _json

    from tti import demo
    demo.generate(tmp_path, [300, 900, 3600, 21600, 86400, 259200])
    assert main(["--run-dir", str(tmp_path), "score", "--json"]) == 0
    raw = capsys.readouterr().out
    assert "NaN" not in raw and "Infinity" not in raw
    doc = _json.loads(raw)          # strict by default in most other languages
    arm = doc["arms"][0]
    assert set(arm["median_time_to_index"]) == {"low_seconds", "high_seconds"}
    assert set(arm["recall_24h"]) == {"point", "low", "high"}


def test_status_json_reports_integrity(tmp_path, capsys):
    import json as _json

    from tti.models import FRESH, Event, ProbeResult
    led = Ledger(tmp_path)
    ev = Event(source="npm", source_class="package_registry", subject="p",
               published_at=1.0, discovered_at=2.0, question="q", answer="1.0.1")
    led.add_events([ev])
    led.add_results([ProbeResult(probe_id="x", event_id=ev.event_id, provider="serper",
                                 mode="search", rung=300, requested_at=300.0,
                                 lag=300.0, verdict=FRESH, cost_usd=0.005)])
    with open(led.events_path, "a", encoding="utf-8") as fh:
        fh.write('{"torn": tru')
    assert main(["--run-dir", str(tmp_path), "status", "--json"]) == 0
    doc = _json.loads(capsys.readouterr().out)
    assert doc["integrity"]["events.jsonl"]["unparseable"] == 1
    assert doc["budget"]["cap_usd"] > 0


def test_a_report_rendered_from_a_real_collected_run(wired, tmp_path, monkeypatch,
                                                     capsys):
    """Discover from a live registry response, walk the ladder, fetch the
    origin over HTTP, then render the dashboard — the whole path, with no
    demo data anywhere.

    The demo generates its own arms and filters them itself, so it cannot
    catch a bug in how a real run reaches the report. That is exactly where
    the origin control once ended up sitting at the top of the leaderboard.
    """
    from tti import scheduler

    now = time.time()
    wired.publish_npm("demo", [("9.9.8", now - 90_000), ("9.9.9", now - 5)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["demo"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "max_clock_skew_seconds": 120,
        "ladder": [300, 900, 3600], "origin_control": True,
        "max_results": 5, "max_chars_per_result": 500,
        "max_rung_slip_seconds": 10 ** 9, "daily_usd_cap": 100.0,
        "arms": [{"provider": "stub", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers", {"providers": {"stub": {"modes": {
        "base": {"usd_per_1k_requests": 1.0, "results_included": 5}}}}})
    monkeypatch.setattr(scheduler.providers, "available_arms",
                        lambda: [("stub", "base")])

    led = Ledger(tmp_path)
    assert scheduler.discover(led, verbose=False).new_events == 1
    ev = next(iter(led.events().values()))
    ev.origins = [wired.base + "/page/ssr"]
    led.events_path.write_text(json.dumps(ev.to_dict()) + "\n")

    Stub = _stub_provider(monkeypatch, {300: "still on 9.9.8", 900: "still on 9.9.8",
                                        3600: "now at 9.9.9"})
    for rung in (300, 900, 3600):
        Stub._rung = rung
        scheduler.run_due(led, now=ev.published_at + rung, verbose=False)

    out_dir = tmp_path / "pages"
    assert main(["--run-dir", str(tmp_path), "report",
                 "--out-dir", str(out_dir)]) == 0
    html = (out_dir / "index.html").read_text()

    # The paid arm is on the leaderboard; the control is not.
    assert "stub/base</td>" in html
    assert "origin/direct</td>" not in html
    # ...but the control's own panel is, with its outcome counted.
    assert "The control arm" in html
    # The page renders class names with underscores replaced, so assert what
    # a reader actually sees.
    assert "server html" in html, "the render class the origin actually returned"
    assert "Where the fact lived" in html
    # The staleness the run really produced, not a placeholder.
    assert "Staleness" in html
    assert "<!doctype html>" in html.lower()

    results_md = (out_dir / "RESULTS.md").read_text()
    assert "stub/base" in results_md and "origin" not in results_md


def test_a_report_from_a_run_where_every_probe_failed(wired, tmp_path, monkeypatch):
    """A provider that was down for the whole window must render a page that
    says so, not one that quietly reports perfect freshness over zero
    observations."""
    from tti import scheduler

    now = time.time()
    wired.publish_npm("demo", [("9.9.8", now - 90_000), ("9.9.9", now - 5)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["demo"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "max_clock_skew_seconds": 120, "ladder": [300], "origin_control": False,
        "max_results": 5, "max_chars_per_result": 500,
        "max_rung_slip_seconds": 10 ** 9, "daily_usd_cap": 100.0,
        "arms": [{"provider": "stub", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers", {"providers": {"stub": {"modes": {
        "base": {"usd_per_1k_requests": 1.0, "results_included": 5}}}}})
    monkeypatch.setattr(scheduler.providers, "available_arms",
                        lambda: [("stub", "base")])

    class Dead:
        name = "stub"
        def modes(self): return ["base"]
        def available(self): return True
        def search(self, *a, **k):
            raise RuntimeError("provider 503")

    monkeypatch.setattr(scheduler.providers, "get", lambda n: Dead())

    led = Ledger(tmp_path)
    scheduler.discover(led, verbose=False)
    ev = next(iter(led.events().values()))
    rep = scheduler.run_due(led, now=ev.published_at + 300, verbose=False)
    assert rep.errors == 1 and rep.spend_usd == 0.0

    # Every observation errored. The page is still drawn — "every probe
    # failed" is itself the finding, and withholding the report would hide it
    # — but it must say plainly that the table is a list of arms rather than
    # a set of results.
    out_dir = tmp_path / "pages"
    assert main(["--run-dir", str(tmp_path), "report",
                 "--out-dir", str(out_dir)]) == 0
    html = (out_dir / "index.html").read_text()
    assert "No arm produced a scoreable observation" in html
    assert "a list of arms, not a set of results" in html
