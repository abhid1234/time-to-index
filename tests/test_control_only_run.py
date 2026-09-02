"""A ledger with control results and no provider arm is not "no results".

It is the state anyone is in before the first provider key arrives, and the
first real ledger this project produced was exactly that. `score` and
`report` both said "no results yet" on 36 results.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, scheduler
from tti.cli import main
from tti.ledger import Ledger


def _control_only_ledger(wired, tmp_path, monkeypatch):
    now = time.time()
    wired.publish_npm("demo", [("9.9.8", now - 90_000), ("9.9.9", now - 5)])
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["demo"], "pypi": []})
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300, 900], "origin_control": True, "arms": [],
        "max_results": 5, "max_chars_per_result": 500,
        "max_rung_slip_seconds": 10 ** 9, "daily_usd_cap": 6.0})
    monkeypatch.setattr(scheduler.providers, "available_arms", lambda: [])
    led = Ledger(tmp_path)
    scheduler.discover(led, verbose=False)
    ev = next(iter(led.events().values()))
    ev.origins = [wired.base + "/page/ssr"]
    led.events_path.write_text(json.dumps(ev.to_dict()) + "\n")
    scheduler.run_due(led, now=ev.published_at + 300, verbose=False)
    assert [r.provider for r in led.results()] == ["origin"]
    return led


def test_score_describes_the_control_only_state_and_exits_zero(wired, tmp_path, monkeypatch, capsys):
    _control_only_ledger(wired, tmp_path, monkeypatch)
    assert main(["--run-dir", str(tmp_path), "score"]) == 0
    out = capsys.readouterr().out
    assert "no results yet" not in out
    assert "Only the origin control has results" in out
    assert "| found | 1 |" in out
    assert "1/1 found the answer" in out
    assert "yardstick, not a result about any provider" in out


def test_score_json_carries_the_control_summary(wired, tmp_path, monkeypatch, capsys):
    _control_only_ledger(wired, tmp_path, monkeypatch)
    assert main(["--run-dir", str(tmp_path), "score", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["arms"] == []
    assert payload["control"]["graded"] == 1
    assert payload["control"]["states"] == {"found": 1}
    assert payload["control"]["render"] == {"server_html": 1}
    assert "only the origin control" in payload["note"]


def test_report_renders_the_control_panel_with_the_right_banner(wired, tmp_path, monkeypatch):
    _control_only_ledger(wired, tmp_path, monkeypatch)
    out_dir = tmp_path / "site"
    out_dir.mkdir()
    assert main(["--run-dir", str(tmp_path), "report", "--out-dir", str(out_dir)]) == 0
    page = (out_dir / "index.html").read_text()
    assert "<h2>The control arm</h2>" in page
    assert "Only the origin control" in page
    assert "Every probe in this run errored" not in page


def test_a_truly_empty_ledger_keeps_the_old_contract(tmp_path, capsys):
    assert main(["--run-dir", str(tmp_path), "score"]) == 1
    assert "no results yet" in capsys.readouterr().out
    assert main(["--run-dir", str(tmp_path), "score", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"arms": [], "note": "no results yet"}
    assert main(["--run-dir", str(tmp_path), "report", "--out-dir", str(tmp_path)]) == 1


def test_sensitivity_says_provider_arm_not_no_results(wired, tmp_path, monkeypatch, capsys):
    _control_only_ledger(wired, tmp_path, monkeypatch)
    assert main(["--run-dir", str(tmp_path), "sensitivity"]) == 1
    out = capsys.readouterr().out
    assert "no provider-arm results to re-grade" in out
    assert "1 control-arm result(s) exist" in out
    assert "no results to re-grade" not in out



def test_power_names_the_control_results_it_is_not_counting(wired, tmp_path, monkeypatch, capsys):
    _control_only_ledger(wired, tmp_path, monkeypatch)
    assert main(["--run-dir", str(tmp_path), "power"]) == 1
    out = capsys.readouterr().out
    assert "need at least two provider arms with results" in out
    assert "1 control-arm result(s) exist" in out
    capsys.readouterr()
    assert main(["--run-dir", str(tmp_path), "power", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["comparisons"] == [] and payload["control_results"] == 1
