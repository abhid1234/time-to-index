"""`tti doctor` is the first command anyone runs, and it had no test.

Its reachability line read "10/2 subjects reachable" on the first real run:
events returned over subjects asked, which is ten of two. It survived because
doctor makes live network calls and the suite is offline, so nothing ever
looked at the string. These tests stub the source layer and look at the string.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, sources
from tti.cli import main
from tti.models import Event


def _event(i: int) -> Event:
    return Event(source="stub", source_class="preprint", subject=f"cat-{i % 2}",
                 published_at=1000.0 + i, discovered_at=1001.0 + i,
                 question="q", answer=f"1.0.{i}")


class _FanOut:
    """A source where one subject yields many events, like an arXiv category.

    Mirrors the fields `cmd_doctor` reads off a real Source: `attempted`,
    `errors`, `all_failed`, `max_subjects`, and `collect()`.
    """

    def __init__(self, attempted: int, errors: int, events: int,
                 warnings: int = 0):
        self._attempted, self._errors, self._events = attempted, errors, events
        self._warnings = warnings
        self.attempted = 0
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.max_subjects = None

    @property
    def all_failed(self) -> bool:
        return self.attempted > 0 and len(self.errors) == self.attempted

    def collect(self, seen):
        self.attempted = self._attempted
        self.errors = [f"cat-{k}: HTTPError: 503" for k in range(self._errors)]
        self.warnings = [f"cat-{k}: packument is 25.0 MB, bound is 32 MB"
                         for k in range(self._warnings)]
        return [_event(i) for i in range(self._events)]


def _wire(monkeypatch, src):
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["stub"], "arms": [], "ladder": [300],
        "origin_control": False})
    monkeypatch.setitem(config._cache, "providers", {"providers": {}})
    monkeypatch.setattr(config, "check_all", lambda: [])
    monkeypatch.setattr(config, "contact_ua", lambda: "test contact")
    monkeypatch.setattr(sources, "get", lambda name: src)


def test_reachability_counts_subjects_that_answered_not_events(monkeypatch, capsys):
    """Two categories asked, both answered, ten papers between them. The
    fraction is 2/2. It was printed as 10/2."""
    _wire(monkeypatch, _FanOut(attempted=2, errors=0, events=10))
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "  2/2 subjects reachable" in out, out
    assert "10/2" not in out
    # The event count is not thrown away; it is just not the numerator.
    assert " 10 events" in out


def test_a_subject_that_errored_is_not_counted_as_reachable(monkeypatch, capsys):
    _wire(monkeypatch, _FanOut(attempted=2, errors=1, events=4))
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "  1/2 subjects reachable" in out, out
    # Named, not counted. "[1 subject errors]" told you nothing about which.
    assert "failed: cat-0" in out
    assert "first:  cat-0: HTTPError: 503" in out


def test_a_warning_is_shown_beside_the_subject_that_raised_it(monkeypatch, capsys):
    _wire(monkeypatch, _FanOut(attempted=2, errors=0, events=4, warnings=1))
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "  2/2 subjects reachable" in out
    assert "~ cat-0: packument is 25.0 MB" in out


def test_every_subject_failing_is_unreachable_not_a_zero(monkeypatch, capsys):
    """The existing all-failed branch, pinned so the numerator fix cannot
    accidentally route an all-failed source through the success line."""
    _wire(monkeypatch, _FanOut(attempted=2, errors=2, events=0))
    # 1, not 2: doctor reserves exit 2 for configuration errors, so a cron
    # wrapper can tell "misconfigured" from "ran and found a source down".
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "unreachable (2/2)" in out
    assert "subjects reachable" not in out
