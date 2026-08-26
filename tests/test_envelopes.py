"""Response-shape robustness for the grader's flattener.

Each provider wraps its results differently: Parallel returns excerpt arrays,
Brave nests under `web.results` with `description`, Serper uses `organic` with
`snippet`, Exa puts extracted text on `text`, Tavily on `content`. The
flattener walks for known content keys rather than matching a schema, so a
vendor changing its envelope degrades to "we found less text" instead of
crashing -- but that same tolerance is how query echo or a URL could sneak
into evidence, so both directions are pinned here.

These are shapes, not captured responses. They assert what *this repo's* code
does with a given structure, and nothing about any vendor's actual output.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti.grader import flatten_text, grade
from tti.models import ABSENT, FRESH, Event
from tti.scheduler import _count_results

TOKEN = "15.4.2"


def ev():
    return Event(source="npm", source_class="package_registry", subject="next",
                 published_at=0.0, discovered_at=1.0, question="q",
                 answer=TOKEN, predecessor="15.4.1")


SHAPES = {
    "excerpt-array": {"results": [
        {"url": "https://a", "title": "next", "excerpts": [f"released {TOKEN}", "more"]}]},
    "nested-web-results": {"web": {"results": [
        {"url": "https://a", "title": "next", "description": f"now at {TOKEN}"}]}},
    "organic-snippet": {"organic": [
        {"link": "https://a", "title": "next", "snippet": f"v{TOKEN} is out"}]},
    "flat-text": {"results": [{"url": "https://a", "title": "n", "text": f"tag {TOKEN}"}]},
    "content-field": {"results": [
        {"url": "https://a", "title": "n", "content": f"upgrade to {TOKEN}"}]},
    "contents-subobject": {"data": {"items": [
        {"contents": {"text": f"version {TOKEN}"}}]}},
    "highlights-list": {"results": [
        {"url": "https://a", "highlights": [f"bumped to {TOKEN}"]}]},
    "deeply-nested": {"a": {"b": {"c": {"d": {"e": [{"summary": TOKEN}]}}}}},
}


@pytest.mark.parametrize("name,payload", sorted(SHAPES.items()))
def test_every_envelope_shape_yields_the_token(name, payload):
    assert TOKEN in flatten_text(payload), name
    assert grade(ev(), payload)[0] == FRESH, name


LEAKS = {
    "url-only": {"results": [{"url": f"https://npmjs.com/next/v/{TOKEN}"}]},
    "query-echo": {"query": f"latest next {TOKEN}", "results": []},
    "objective-echo": {"objective": f"what version is {TOKEN}", "results": []},
    "id-field": {"results": [{"id": TOKEN, "title": "next"}]},
    "source-url": {"results": [{"source_url": f"https://x/{TOKEN}"}]},
    "request-id": {"request_id": TOKEN, "results": []},
}


@pytest.mark.parametrize("name,payload", sorted(LEAKS.items()))
def test_non_content_fields_are_never_evidence(name, payload):
    """A provider must not score on our own query coming back, or on a URL
    whose path carries a version the page body contradicts."""
    assert grade(ev(), payload)[0] == ABSENT, name


def test_unknown_envelope_degrades_instead_of_crashing():
    weird = {"totally": ["new", {"shape": None}, 42, 3.14, True]}
    assert flatten_text(weird) == ""
    assert grade(ev(), weird)[0] == ABSENT
    assert grade(ev(), None)[0] == ABSENT
    assert grade(ev(), [])[0] == ABSENT
    assert grade(ev(), "a bare string")[0] == ABSENT


def test_pathological_nesting_is_depth_capped_not_a_stack_overflow():
    """A provider response is not trusted input. Ten thousand levels under a
    *known content key* used to recurse without limit, because the depth cap
    lived in the tree walker and not in the value stringifier."""
    deep = cur = {}
    for _ in range(10_000):
        cur["content"] = {}
        cur = cur["content"]
    cur["text"] = TOKEN
    assert flatten_text(deep) == ""            # returns, does not blow the stack
    assert grade(ev(), deep)[0] == ABSENT


V_PREFIXED = {
    "bare": f"released {TOKEN}",
    "v-prefix": f"released v{TOKEN}",
    "capital-v": f"released V{TOKEN}",
    "at-sign": f"next@{TOKEN}",
    "parens": f"(next {TOKEN})",
    "tag-line": f"tag: v{TOKEN} published",
}


@pytest.mark.parametrize("name,text", sorted(V_PREFIXED.items()))
def test_version_prefixes_still_match(name, text):
    """`v15.4.2` is how half the web writes a release. A strict word-boundary
    lookbehind rejects it, which would score a response that plainly contains
    the answer as ABSENT."""
    assert grade(ev(), {"results": [{"snippet": text}]})[0] == FRESH, name


NEAR_MISSES = {
    "longer-patch": "shipped 15.4.20 today",
    "longer-prefix": "build 115.4.2 of the thing",
    "glued-suffix": "15.4.2x is not a version",
    "glued-dot": "15.4.25",
}


@pytest.mark.parametrize("name,text", sorted(NEAR_MISSES.items()))
def test_near_misses_still_rejected_after_loosening(name, text):
    """The `v` allowance must not reopen the substring trap it sits next to."""
    assert grade(ev(), {"results": [{"snippet": text}]})[0] == ABSENT, name


def test_result_counting_across_shapes():
    assert _count_results(SHAPES["excerpt-array"]) == 1
    assert _count_results(SHAPES["nested-web-results"]) == 1
    assert _count_results(SHAPES["organic-snippet"]) == 1
    assert _count_results({"nothing": True}) == 0
    assert _count_results("not a dict") == 0
