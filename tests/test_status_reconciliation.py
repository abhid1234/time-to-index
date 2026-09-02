"""`tti status` shows how far vendor-reported charges drift from the table."""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config
from tti.cli import main
from tti.ledger import Ledger
from tti.models import ProbeResult, dumps


def _row(pid, provider, cost, source, verdict="ABSENT"):
    return dumps(ProbeResult(
        probe_id=pid, event_id="e", provider=provider, mode="m", rung=300,
        requested_at=1.0, lag=300.0, verdict=verdict, cost_usd=cost,
        cost_source=source).to_dict())


def _price(monkeypatch, per_1k):
    monkeypatch.setitem(config._cache, "providers", {"providers": {
        "v": {"modes": {"m": {"usd_per_1k_requests": per_1k, "results_included": 10}}}}})
    monkeypatch.setitem(config._cache, "settings", {
        "arms": [{"provider": "v", "mode": "m"}], "ladder": [300],
        "max_results": 5, "daily_usd_cap": 6.0})


def test_reconciliation_sums_reported_minus_list(tmp_path, monkeypatch, capsys):
    _price(monkeypatch, per_1k=5.0)                      # list: $0.005
    (tmp_path / "results.jsonl").write_text(
        _row("a", "v", 0.007, "reported") + "\n" +        # +0.002
        _row("b", "v", 0.007, "reported") + "\n" +        # +0.002
        _row("c", "v", 0.005, "list") + "\n" +
        _row("d", "v", 0.0, "list", verdict="ERROR") + "\n")
    assert main(["--run-dir", str(tmp_path), "status", "--json"]) == 0
    rec = json.loads(capsys.readouterr().out)["cost_reconciliation"]
    assert rec == {"reported_rows": 2, "list_rows": 1, "drift_usd": 0.004}


def test_an_empty_ledger_reports_zeros_not_a_missing_key(tmp_path, monkeypatch, capsys):
    _price(monkeypatch, per_1k=5.0)
    assert main(["--run-dir", str(tmp_path), "status", "--json"]) == 0
    rec = json.loads(capsys.readouterr().out)["cost_reconciliation"]
    assert rec == {"reported_rows": 0, "list_rows": 0, "drift_usd": 0.0}


def test_the_human_line_appears_only_when_something_was_reported(tmp_path, monkeypatch, capsys):
    _price(monkeypatch, per_1k=5.0)
    (tmp_path / "results.jsonl").write_text(_row("c", "v", 0.005, "list") + "\n")
    assert main(["--run-dir", str(tmp_path), "status"]) == 0
    assert "vendor-reported" not in capsys.readouterr().out

    (tmp_path / "results.jsonl").write_text(_row("a", "v", 0.010, "reported") + "\n")
    Ledger(tmp_path)  # fresh read
    assert main(["--run-dir", str(tmp_path), "status"]) == 0
    out = capsys.readouterr().out
    assert "1 vendor-reported row(s)" in out
    assert "reported minus list = +$0.0050" in out
    assert "has drifted" in out
