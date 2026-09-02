"""HTTP 200 with an error body and no results is not a search that found
nothing. It is a call that never searched, and grading it would charge the
vendor a recall failure for its own rate limit."""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, scheduler
from tti.ledger import Ledger
from tti.models import ABSENT, ERROR, Event, Probe


class Answers:
    name = "stub"

    def __init__(self, payload):
        self.payload = payload

    def modes(self): return ["base"]
    def available(self): return True

    def search(self, question, mode, *, max_results, max_chars):
        return self.payload


def _run(tmp_path, monkeypatch, payload):
    led = Ledger(tmp_path)
    published = time.time() - 400
    ev = Event(source="npm", source_class="package_registry", subject="pkg",
               published_at=published, discovered_at=published + 10,
               question="latest version of pkg?", answer="9.9.9", predecessor="9.9.8")
    led.add_events([ev])
    led.add_probes([Probe(event_id=ev.event_id, provider="stub", mode="base", rung=300,
                          due_at=published + 300)])
    monkeypatch.setattr(scheduler.providers, "get", lambda name: Answers(payload))
    monkeypatch.setitem(config._cache, "settings", {
        "ladder": [300], "daily_usd_cap": 100.0, "max_results": 5,
        "max_chars_per_result": 500, "max_detection_lag_seconds": 600,
        "max_rung_slip_seconds": 10 ** 6, "arms": [{"provider": "stub", "mode": "base"}]})
    monkeypatch.setitem(config._cache, "providers", {"providers": {"stub": {"modes": {
        "base": {"usd_per_1k_requests": 5.0, "results_included": 5}}}}})
    rep = scheduler.run_due(led, verbose=False)
    return led, led.results()[0], rep


def test_an_error_body_with_http_200_is_an_error_not_an_absent(tmp_path, monkeypatch):
    led, r, rep = _run(tmp_path, monkeypatch,
                       {"error": {"type": "rate_limit_exceeded", "message": "slow down"}})
    assert r.verdict == ERROR
    assert "error body with HTTP 200" in r.note and "rate_limit_exceeded" in r.note
    assert r.cost_usd == 0.0 and rep.errors == 1
    assert r.raw_ref and led.load_raw(r.raw_ref)["error"]["type"] == "rate_limit_exceeded"


def test_a_message_only_body_is_also_an_error(tmp_path, monkeypatch):
    _, r, _ = _run(tmp_path, monkeypatch, {"message": "Insufficient credits", "code": 402})
    assert r.verdict == ERROR and "Insufficient credits" in r.note


def test_an_empty_result_set_is_still_absent(tmp_path, monkeypatch):
    """`results: []` is a search that found nothing. That is the grader's."""
    _, r, rep = _run(tmp_path, monkeypatch, {"results": [], "search_id": "s"})
    assert r.verdict == ABSENT and rep.errors == 0 and r.cost_usd > 0


def test_a_results_container_with_a_warning_is_graded(tmp_path, monkeypatch):
    """A response that carries both results and a message is a response."""
    _, r, _ = _run(tmp_path, monkeypatch,
                   {"results": [{"snippet": "now 9.9.9"}], "message": "deprecated field"})
    assert r.verdict == "FRESH"


def test_error_body_helper_edges():
    assert scheduler.error_body(None) == ""
    assert scheduler.error_body({}) == ""
    assert scheduler.error_body({"error": None}) == ""
    assert scheduler.error_body({"error": ""}) == ""
    assert scheduler.error_body({"errors": ["a", "b"]}).startswith("errors=")
    assert scheduler.error_body({"web": {"results": []}}) == ""
