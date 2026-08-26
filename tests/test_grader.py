import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti.grader import flatten_text, grade
from tti.models import ABSENT, FRESH, STALE, Event


def ev(answer="15.4.2", predecessor="15.4.1"):
    return Event(
        source="npm", source_class="package_registry", subject="next",
        published_at=0.0, discovered_at=1.0,
        question="What is the latest version of the next npm package?",
        answer=answer, predecessor=predecessor,
    )


def payload(*snippets):
    return {"results": [{"url": "https://x/y", "title": "t", "snippet": s} for s in snippets]}


def test_fresh():
    assert grade(ev(), payload("next 15.4.2 is out"))[0] == FRESH


def test_stale_is_not_absent():
    assert grade(ev(), payload("the latest release is 15.4.1"))[0] == STALE


def test_absent():
    assert grade(ev(), payload("Next.js is a React framework"))[0] == ABSENT


def test_substring_trap():
    # 15.4.10 must not be read as evidence of 15.4.1.
    v, fresh, stale, _ = grade(ev(answer="15.4.11", predecessor="15.4.1"),
                               payload("shipped 15.4.10 today"))
    assert v == ABSENT, (v, fresh, stale)


def test_changelog_containing_both_is_fresh():
    v, _, stale, _ = grade(ev(), payload("15.4.2 (latest) 15.4.1 15.4.0"))
    assert v == FRESH and stale == ["15.4.1"]


def test_url_is_not_evidence():
    # A URL carrying the version must not count; only returned content does.
    p = {"results": [{"url": "https://npmjs.com/next/v/15.4.2", "title": "next"}]}
    assert grade(ev(), p)[0] == ABSENT


def test_query_echo_is_not_evidence():
    p = {"query": "latest version of next 15.4.2", "results": []}
    assert grade(ev(), p)[0] == ABSENT


def test_flatten_reaches_nested_content():
    p = {"data": {"items": [{"contents": {"text": "version 15.4.2"}}]}}
    assert "15.4.2" in flatten_text(p)


def test_no_predecessor_never_stale():
    e = Event(source="arxiv", source_class="preprint", subject="p", published_at=0.0,
              discovered_at=1.0, question="q", answer="2608.01234")
    assert grade(e, payload("unrelated"))[0] == ABSENT
