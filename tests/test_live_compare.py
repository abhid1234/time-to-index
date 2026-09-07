"""The live compare endpoint asks the benchmark's question, or refuses.

Hermetic: a packument is injected, the control is switched off, and no
provider key is set in the test environment, so `available_arms()` is empty
and nothing here opens a socket. What is being pinned is the wiring -- that
the demo asks what the harness asks, and that it will not spend on a subject
nobody allow-listed.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import live
from tti.sources import npm as npm_source

# Two stable releases and a prerelease, so the predecessor logic has to choose.
PACKUMENT = {
    "dist-tags": {"latest": "7.3.1"},
    "time": {
        "created": "2020-01-01T00:00:00.000Z",
        "modified": "2026-09-03T13:29:45.970Z",
        "7.2.4": "2026-08-28T09:00:00.000Z",
        "7.3.0-beta.1": "2026-09-01T09:00:00.000Z",
        "7.3.1": "2026-09-03T13:29:45.970Z",
    },
}
# Derived, not hardcoded: an epoch typed by hand is a constant that silently
# disagrees with the parser it is meant to match.
PUBLISHED = npm_source._iso(PACKUMENT["time"]["7.3.1"])


def _fetch(_pkg):
    return PACKUMENT, len(str(PACKUMENT))


def _compare(pkg="astro", now=PUBLISHED + 600):
    return live.compare(pkg, fetch_packument=_fetch, now=now,
                        include_control=False)


def test_a_subject_nobody_allowlisted_is_refused_before_anything_is_spent():
    with pytest.raises(ValueError) as exc:
        live.compare("left-pad", fetch_packument=_fetch, include_control=False)
    assert "left-pad" in str(exc.value)


def test_every_allowed_subject_is_actually_askable():
    """An allow-list entry that the code path rejects is a dead promise."""
    for pkg in live.ALLOWED:
        assert _compare(pkg)["subject"] == pkg


def test_it_asks_the_question_the_collector_asks():
    """The demo and the benchmark must not drift into two different questions."""
    ev = npm_source.event_from_packument("astro", PACKUMENT)
    assert _compare()["question"] == ev.question
    assert "astro" in ev.question


def test_the_predecessor_skips_the_prerelease():
    r = _compare()
    assert r["answer"] == "7.3.1"
    assert r["predecessor"] == "7.2.4"


def test_age_is_reported_because_one_sample_needs_its_lag_stated():
    r = _compare(now=PUBLISHED + 600)
    assert round(r["age_seconds"]) == 600
    assert r["age_human"] == "10 minutes"
    assert "not a measurement of indexing speed" in r["disclaimer"]


def test_a_clock_behind_the_publisher_does_not_produce_a_negative_age():
    assert _compare(now=PUBLISHED - 30)["age_seconds"] == 0.0


def test_with_no_keys_nothing_is_asked_and_nothing_is_spent():
    r = _compare()
    assert r["arms"] == []
    assert r["spend_usd"] == 0.0
    assert r["summary"] == {"asked": 0, "graded": 0,
                            "fresh": 0, "stale": 0, "absent": 0}


def test_the_answer_carries_a_cache_window():
    """Without one, a public URL is a way to spend the provider budget."""
    assert _compare()["cache_seconds"] == live.CACHE_SECONDS
    assert live.CACHE_SECONDS > 0


def test_a_packument_with_no_latest_version_implies_no_event():
    with pytest.raises(ValueError):
        live.compare("astro", fetch_packument=lambda _p: ({"time": {}}, 2),
                     include_control=False)

def test_the_deploy_declares_what_the_endpoint_imports():
    """A missing dep fails at import on Vercel, not at request time.

    Walking the import graph rather than listing names by hand: the point is
    to catch the day someone adds a third-party import to `tti/` and the
    function starts 500-ing on a deploy nobody touched.
    """
    import ast

    root = pathlib.Path(__file__).resolve().parent.parent
    roots: set[str] = set()
    for path in [*(root / "tti").rglob("*.py"), root / "api" / "compare.py"]:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])

    # An import name is not a distribution name; pip installs PyYAML and you
    # import yaml. Only the ones this project actually uses are mapped, so a
    # new dependency with the same mismatch fails here and gets looked at.
    distribution = {"yaml": "pyyaml"}

    third_party = {distribution.get(m.lower(), m.lower()) for m in roots
                   if m not in sys.stdlib_module_names and m != "tti"}
    declared = {line.split(">=")[0].split("==")[0].strip().lower()
                for line in (root / "requirements.txt").read_text().splitlines()
                if line.strip() and not line.startswith("#")}
    assert third_party <= declared, f"undeclared: {sorted(third_party - declared)}"
