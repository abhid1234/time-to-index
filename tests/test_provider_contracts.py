"""Every paid adapter's request, pinned against its vendor's published spec.

Written the night the Parallel adapter turned out to target a retired
endpoint with another product's field names. None of these adapters had ever
been called, and none had a test that looked at the request they would send.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, providers
from tti.providers import brave, exa, serper, tavily

Q = "What is the current latest published version of the npm package next?"


def _post(monkeypatch, mod, env):
    sent = {}

    def post(url, *, json, headers, **kw):
        sent.update(url=url, json=json, headers=headers)
        return {"results": []}
    monkeypatch.setattr(mod.http, "post_json", post)
    monkeypatch.setenv(env, "k")
    return sent


def _get(monkeypatch, mod, env):
    sent = {}

    def get(url, *, params, headers, **kw):
        sent.update(url=url, params=params, headers=headers)
        return {"web": {"results": []}}
    monkeypatch.setattr(mod.http, "get_json", get)
    monkeypatch.setenv(env, "k")
    return sent


def test_brave_sends_no_recency_filter(monkeypatch):
    """`freshness=pd` was there for a week. A last-24-hours filter in a
    freshness benchmark removes stale competitors at short rungs and the
    correct document at 72 hours. No arm gets a vendor-specific filter."""
    sent = _get(monkeypatch, brave, "BRAVE_API_KEY")
    brave.Brave().search(Q, "web", max_results=5, max_chars=1500)
    assert sent["url"] == "https://api.search.brave.com/res/v1/web/search"
    assert sent["headers"]["X-Subscription-Token"] == "k"
    assert sent["params"] == {"q": Q, "count": 5}
    assert "freshness" not in sent["params"]


def test_exa_request_matches_the_spec(monkeypatch):
    sent = _post(monkeypatch, exa, "EXA_API_KEY")
    exa.Exa().search(Q, "auto", max_results=5, max_chars=1500)
    assert sent["url"] == "https://api.exa.ai/search"
    assert sent["headers"]["x-api-key"] == "k"
    assert sent["json"] == {
        "query": Q, "type": "auto", "numResults": 5,
        "contents": {"text": {"maxCharacters": 1500}},
    }


@pytest.mark.parametrize("stale", ["keyword", "neural"])
def test_exa_refuses_types_that_are_no_longer_documented(monkeypatch, stale):
    sent = _post(monkeypatch, exa, "EXA_API_KEY")
    with pytest.raises(ValueError, match="not one of"):
        exa.Exa().search(Q, stale, max_results=5, max_chars=100)
    assert sent == {}


def test_exa_reported_cost_reads_the_vendors_own_number():
    assert exa.Exa.reported_cost({"costDollars": {"total": 0.007}}) == 0.007
    assert exa.Exa.reported_cost({"results": []}) is None
    assert exa.Exa.reported_cost(None) is None
    assert exa.Exa.reported_cost({"costDollars": {"total": -1}}) is None
    assert exa.Exa.reported_cost({"costDollars": {"total": True}}) is None


def test_tavily_request_matches_the_spec(monkeypatch):
    sent = _post(monkeypatch, tavily, "TAVILY_API_KEY")
    tavily.Tavily().search(Q, "basic", max_results=5, max_chars=1500)
    assert sent["url"] == "https://api.tavily.com/search"
    assert sent["headers"]["Authorization"] == "Bearer k"
    body = sent["json"]
    assert body["query"] == Q and body["search_depth"] == "basic"
    assert body["max_results"] == 5
    assert body["include_answer"] is False
    for banned in ("time_range", "start_date", "end_date", "topic"):
        assert banned not in body


def test_serper_request_matches_the_spec(monkeypatch):
    sent = _post(monkeypatch, serper, "SERPER_API_KEY")
    serper.Serper().search(Q, "search", max_results=5, max_chars=1500)
    assert sent["url"] == "https://google.serper.dev/search"
    assert sent["headers"]["X-API-KEY"] == "k"
    assert sent["json"] == {"q": Q, "num": 5}


def test_every_declared_mode_of_every_provider_is_priced():
    """Stronger than checking configured arms. Exa declared `neural` with no
    price line for a week; had anyone configured it, the cost column would
    have read $0.00 -- the cheapest way to win a benchmark."""
    priced = config.providers_config()["providers"]
    for name in ("parallel", "exa", "tavily", "brave", "serper"):
        prov = providers.get(name)
        modes = priced[name]["modes"]
        for m in prov.modes():
            assert m in modes, f"{name}/{m} is declared but not priced"
            assert modes[m]["usd_per_1k_requests"] > 0, f"{name}/{m} priced at zero"


def test_no_priced_mode_is_undeclared():
    """The mirror: a price line for a mode the adapter cannot send is a
    stale entry waiting to mislead the next reader of the table."""
    priced = config.providers_config()["providers"]
    for name in ("parallel", "exa", "tavily", "brave", "serper"):
        declared = set(providers.get(name).modes())
        for m in priced[name]["modes"]:
            assert m in declared, f"{name}/{m} is priced but the adapter cannot send it"


def test_the_same_question_reaches_every_paid_arm_unaltered(monkeypatch):
    """The stimulus is identical across arms. Any adapter that rewrites,
    truncates or decorates the question is measuring its own tuning.

    All four adapters share one `tti.http` module, so the recorder is keyed
    by endpoint URL -- patching "per module" in a loop overwrites the same
    function four times and the last closure wins."""
    from tti import http as H
    seen = {}

    def rec(url, *, json=None, params=None, **kw):
        seen[url] = json or params
        return {"results": []}
    monkeypatch.setattr(H, "post_json", rec)
    monkeypatch.setattr(H, "get_json", rec)
    for env in ("EXA_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY", "BRAVE_API_KEY"):
        monkeypatch.setenv(env, "k")
    exa.Exa().search(Q, "auto", max_results=5, max_chars=1500)
    tavily.Tavily().search(Q, "basic", max_results=5, max_chars=1500)
    serper.Serper().search(Q, "search", max_results=5, max_chars=1500)
    brave.Brave().search(Q, "web", max_results=5, max_chars=1500)
    assert seen[exa.ENDPOINT]["query"] == Q
    assert seen[tavily.ENDPOINT]["query"] == Q
    assert seen[serper.ENDPOINT]["q"] == Q
    assert seen[brave.ENDPOINT]["q"] == Q
