"""Collectors against malformed API responses.

Registry and filing APIs are external input that changes without notice, and
this is the one place the project consumes something it does not control.
The rule for every case below is the same: never crash the run, never
silently invent an event, and always leave a per-subject error behind so a
source that has started returning garbage is visible rather than quiet.
"""
import pathlib
import sys
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti import config
from tti.sources import arxiv as ax_mod
from tti.sources import edgar as ed_mod
from tti.sources import federal_register as fr_mod
from tti.sources import github_releases as gh_mod
from tti.sources import npm as npm_mod
from tti.sources import pypi as pypi_mod

WATCHLIST = {"npm": ["p"], "pypi": ["p"], "github": ["o/r"],
             "edgar": [{"cik": "1", "name": "X"}], "arxiv": ["cs.AI"]}


@pytest.fixture(autouse=True)
def watchlist(monkeypatch):
    monkeypatch.setitem(config._cache, "watchlist", WATCHLIST)


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    """Every fuzz test is offline by contract. Enforce it.

    A refactor moved npm from `get_json` to `get_json_sized`; the fuzz patch
    still targeted `get_json`, so npm's fetch went unpatched and made a LIVE
    call to the registry. The "null document" case then returned a genuine
    Event for the real package `p`, published in 2012 -- a plausible result
    for entirely the wrong reason, and the assertion caught it only because
    it demanded an empty list. Patching the transport turns that class of
    drift into a loud failure at the first call.
    """
    from tti import http as _http

    attempts: list[str] = []

    def refuse(method, url, *a, **kw):
        attempts.append(f"{method} {url}")
        raise ConnectionError("fuzz: live request refused")
    monkeypatch.setattr(_http, "_request", refuse)
    yield
    # Asserted at teardown, not inside `refuse`. Sources catch every Exception
    # from a fetch and file it under `errors`, so an assertion raised inside
    # the transport is swallowed and the test passes with the source merely
    # "errored" -- indistinguishable, to a never-invents assertion, from the
    # right answer. Out here nothing can catch it.
    assert not attempts, (
        "fuzz test reached the network; the patch is not covering this "
        "source's fetch:\n  " + "\n  ".join(attempts))


def collect(mod, cls, payload, method="get_json_sized"):
    """Run a source against a canned payload with no network.

    Patches `get_json_sized` by default: `get_json` delegates to it, so one
    patch covers every JSON source regardless of which of the two it calls.
    The sized variant returns (document, byte_count); for a fuzz payload the
    byte count is irrelevant and is zero.
    """
    src = cls()
    value = (payload, 0) if method == "get_json_sized" else payload
    with patch.object(mod.http, method, return_value=value):
        events = src.collect({})
    return src, events


NPM_GARBAGE = [
    ("empty object", {}),
    ("no dist-tags", {"time": {"1.0.0": "2026-01-01T00:00:00.000Z"}}),
    ("no time map", {"dist-tags": {"latest": "1.0.0"}}),
    ("latest absent from time", {"dist-tags": {"latest": "9.9.9"},
                                 "time": {"1.0.0": "2026-01-01T00:00:00.000Z"}}),
    ("unparseable date", {"dist-tags": {"latest": "1.0.0"},
                          "time": {"1.0.0": "not-a-date"}}),
    ("time is a list", {"dist-tags": {"latest": "1.0.0"}, "time": [1, 2, 3]}),
    ("dist-tags is null", {"dist-tags": None, "time": {}}),
    ("null document", None),
    ("a bare string", "unexpected"),
]

PYPI_GARBAGE = [
    ("empty object", {}),
    ("no info", {"releases": {"1.0.0": [{"upload_time_iso_8601": "2026-01-01T00:00:00.000Z"}]}}),
    ("version absent from releases", {"info": {"version": "9.9.9"}, "releases": {}}),
    ("release has no files", {"info": {"version": "1.0.0"}, "releases": {"1.0.0": []}}),
    ("file has no upload time", {"info": {"version": "1.0.0"},
                                 "releases": {"1.0.0": [{}]}}),
    ("unparseable date", {"info": {"version": "1.0.0"},
                          "releases": {"1.0.0": [{"upload_time_iso_8601": "nope"}]}}),
    ("releases is a list", {"info": {"version": "1.0.0"}, "releases": []}),
    ("null document", None),
]

GH_GARBAGE = [
    ("empty list", []),
    ("an error object, not a list", {"message": "Not Found"}),
    ("no published_at", [{"tag_name": "v1"}]),
    ("no tag_name", [{"published_at": "2026-01-01T00:00:00Z"}]),
    ("unparseable date", [{"tag_name": "v1", "published_at": "nope"}]),
    ("null document", None),
]

FR_GARBAGE = [
    ("empty object", {}),
    ("results is not a list", {"results": "nope"}),
    ("unparseable date", {"results": [{"document_number": "1", "title": "T",
                                       "publication_date": "not-a-date"}]}),
    ("null document", None),
]


@pytest.mark.parametrize("label,payload", NPM_GARBAGE, ids=[c[0] for c in NPM_GARBAGE])
def test_npm_never_crashes_and_never_invents(label, payload):
    src, events = collect(npm_mod, npm_mod.Npm, payload)
    assert events == []
    assert src.attempted == 1


@pytest.mark.parametrize("label,payload", PYPI_GARBAGE, ids=[c[0] for c in PYPI_GARBAGE])
def test_pypi_never_crashes_and_never_invents(label, payload):
    src, events = collect(pypi_mod, pypi_mod.PyPI, payload)
    assert events == []


@pytest.mark.parametrize("label,payload", GH_GARBAGE, ids=[c[0] for c in GH_GARBAGE])
def test_github_never_crashes_and_never_invents(label, payload):
    src, events = collect(gh_mod, gh_mod.GithubReleases, payload)
    assert events == []


@pytest.mark.parametrize("label,payload", FR_GARBAGE, ids=[c[0] for c in FR_GARBAGE])
def test_federal_register_never_crashes_and_never_invents(label, payload):
    src, events = collect(fr_mod, fr_mod.FederalRegister, payload)
    assert events == []


@pytest.mark.parametrize("xml", ["", "<<<", "<feed/>",
                                 "<feed xmlns='http://www.w3.org/2005/Atom'>"
                                 "<entry><title>T</title></entry></feed>"])
def test_arxiv_never_crashes_on_bad_xml(xml):
    src, events = collect(ax_mod, ax_mod.ArXiv, xml, method="get_text")
    assert events == []


def test_edgar_refuses_mismatched_parallel_arrays():
    """`recent` is parallel arrays keyed by position. When their lengths
    disagree, position i in one does not describe the same filing as position
    i in another.

    Reading across them anyway produced an event with a zero timestamp, which
    was then dropped downstream as "detected late" — a malformed response
    wearing the costume of a benign outcome, and the wrong count in the wrong
    bucket."""
    payload = {"filings": {"recent": {
        "form": ["10-Q", "8-K"], "accessionNumber": ["0000-1"],
        "acceptanceDateTime": [], "filingDate": []}}}
    src, events = collect(ed_mod, ed_mod.Edgar, payload)
    assert events == []
    assert src.errors, "a length mismatch must leave an error behind"
    assert "disagree in length" in src.errors[0]


def test_edgar_accepts_well_formed_parallel_arrays():
    payload = {"filings": {"recent": {
        "form": ["10-Q", "8-K"],
        "accessionNumber": ["0000320193-26-000081", "0000320193-26-000070"],
        "acceptanceDateTime": ["2026-08-01T16:31:07.000Z",
                               "2026-07-01T16:31:07.000Z"],
        "filingDate": ["2026-08-01", "2026-07-01"]}}}
    src, events = collect(ed_mod, ed_mod.Edgar, payload)
    assert len(events) == 1 and not src.errors
    assert events[0].answer == "0000320193-26-000081"
    assert events[0].published_at > 0


@pytest.mark.parametrize("payload", [{}, {"filings": {}}, None,
                                     {"filings": {"recent": {"form": ["X-1"],
                                      "accessionNumber": ["a"],
                                      "acceptanceDateTime": ["2026-01-01T00:00:00Z"],
                                      "filingDate": ["2026-01-01"]}}}])
def test_edgar_never_crashes_on_other_garbage(payload):
    src, events = collect(ed_mod, ed_mod.Edgar, payload)
    assert events == []


def test_a_source_returning_garbage_for_every_subject_reads_as_broken(monkeypatch):
    """One bad subject is noise. Every subject failing is a source that has
    changed its API, and must not read as a quiet day."""
    monkeypatch.setitem(config._cache, "watchlist", {"npm": ["a", "b", "c"]})
    src = npm_mod.Npm()
    with patch.object(npm_mod.http, "get_json_sized", return_value=(None, 0)):
        src.collect({})
    assert src.all_failed and len(src.errors) == 3
