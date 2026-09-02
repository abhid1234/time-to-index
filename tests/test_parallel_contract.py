"""The Parallel adapter against the published v1 contract.

This file exists because the adapter was wrong for a week and nothing could
have told anyone: it targeted a retired endpoint, used a field name from a
different product, and offered two modes that were Task API processors.
Every probe would have returned 403. No test looked at the request body.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, providers
from tti.providers import parallel as par


def _capture(monkeypatch):
    sent = {}

    def post(url, *, json, headers, **kw):
        sent.update(url=url, json=json, headers=headers)
        return {"search_id": "s", "results": []}
    monkeypatch.setattr(par.http, "post_json", post)
    monkeypatch.setenv("PARALLEL_API_KEY", "k")
    return sent


def test_the_request_matches_the_v1_contract(monkeypatch):
    sent = _capture(monkeypatch)
    par.Parallel().search("what is the latest version of next?", "fast",
                          max_results=5, max_chars=1500)
    assert sent["url"] == "https://api.parallel.ai/v1/search"
    assert sent["headers"]["x-api-key"] == "k"
    body = sent["json"]
    assert body["mode"] == "fast"
    assert "processor" not in body
    assert body["objective"] == "what is the latest version of next?"
    assert body["search_queries"] == ["what is the latest version of next?"]
    assert body["advanced_settings"] == {
        "max_results": 5,
        "excerpt_settings": {"max_chars_per_result": 1500},
    }
    assert "max_results" not in body and "max_chars_per_result" not in body


def test_search_queries_stay_within_the_hard_limits(monkeypatch):
    """Five queries, 200 chars each. Ours is one sentence, so this is a
    guard against a future question template growing past the limit."""
    sent = _capture(monkeypatch)
    long_but_legal = "What is the current latest published version of the npm package " \
                     "@some-scope/some-fairly-long-package-name-here?"
    par.Parallel().search(long_but_legal, "advanced", max_results=5, max_chars=1500)
    qs = sent["json"]["search_queries"]
    assert len(qs) <= 5 and all(len(x) <= 200 for x in qs)


@pytest.mark.parametrize("bad", ["base", "pro", "one-shot", "agentic", "BASIC"])
def test_an_invalid_mode_is_refused_locally_not_by_a_403(monkeypatch, bad):
    """`base` and `pro` are Task API processors. Sending them yields
    'Forbidden: invalid processor in request', which would be graded as an
    ERROR indistinguishable from an outage. Refuse before the wire."""
    sent = _capture(monkeypatch)
    with pytest.raises(ValueError, match="not one of"):
        par.Parallel().search("q", bad, max_results=5, max_chars=100)
    assert sent == {}, "nothing must have been sent"


def test_modes_are_exactly_the_documented_four():
    assert par.Parallel().modes() == ["turbo", "fast", "basic", "advanced"]


def test_every_configured_arm_is_a_mode_its_adapter_declares():
    """Generic, across providers. The check that would have caught
    parallel/base and parallel/pro before a single probe was queued."""
    for arm in config.settings().get("arms", []):
        prov = providers.get(arm["provider"])
        assert arm["mode"] in prov.modes(), (
            f"{arm['provider']}/{arm['mode']} is not a mode the adapter "
            f"declares: {prov.modes()}")


def test_every_configured_arm_is_priced():
    """A mode with no price line means $0.00 in the cost column, which is
    the cheapest way to win a benchmark."""
    priced = config.providers_config()["providers"]
    for arm in config.settings().get("arms", []):
        modes = priced.get(arm["provider"], {}).get("modes", {})
        assert arm["mode"] in modes, f"{arm['provider']}/{arm['mode']} has no price"
        assert modes[arm["mode"]]["usd_per_1k_requests"] > 0


def test_the_response_envelope_is_counted_and_read():
    """The documented shape: results[].excerpts[] plus url and title."""
    from tti.grader import flatten_text
    from tti.scheduler import _count_results
    payload = {"search_id": "s", "results": [
        {"url": "https://x", "title": "T", "publish_date": None,
         "excerpts": ["next 16.3.4 was released", "second excerpt"]}]}
    assert _count_results(payload) == 1
    text = flatten_text(payload)
    assert "16.3.4" in text and "second excerpt" in text
