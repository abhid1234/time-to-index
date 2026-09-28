"""`tti report` must not publish from a working ledger older than the committed one.

This repo keeps two ledgers. `runs/` is where a probe writes and is
gitignored; `ledger/` is the committed mirror the hosted runner copies back
after every run. So `git pull` advances `ledger/` and leaves `runs/` alone,
and the next local `tti report` -- which reads `runs/` -- regenerates
RESULTS.md, docs/index.html and docs/data/observed.json from the older state.

That is not hypothetical. A merge here regenerated RESULTS.md over a
ten-event ledger from a six-event `runs/`, and the published page went from
twelve graded provider calls to zero. Every test passed, because nothing
compared the two.

A project whose whole argument is that a page must never understate what was
collected cannot ship the command that does exactly that, silently.
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _events(path: pathlib.Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_guard_refuses_when_committed_ledger_is_ahead(tmp_path, capsys) -> None:
    from tti.cli import _refuse_if_stale
    from tti.ledger import Ledger

    committed = _events(ROOT / "ledger" / "events.jsonl")
    if len(committed) < 2:
        import pytest
        pytest.skip("needs at least two committed events to drop one")

    run_dir = tmp_path / "runs"
    (run_dir / "raw").mkdir(parents=True)
    # Everything the committed ledger has, minus its newest event.
    trimmed = sorted(committed, key=lambda e: e["published_at"])[:-1]
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in trimmed) + "\n")

    rc = _refuse_if_stale(Ledger(run_dir), explicit_run_dir=False)
    assert rc == 3
    err = capsys.readouterr().err
    assert "refusing to publish" in err
    assert "overwrite the published pages" in err


def test_an_explicit_run_dir_is_never_guarded(tmp_path) -> None:
    """--run-dir names the ledger you mean; comparing it to this checkout's is
    nonsense, and doing so broke twenty-three unrelated tests once."""
    from tti.cli import _refuse_if_stale
    from tti.ledger import Ledger

    run_dir = tmp_path / "runs"
    (run_dir / "raw").mkdir(parents=True)
    (run_dir / "events.jsonl").write_text("")     # as far behind as it gets

    assert _refuse_if_stale(Ledger(run_dir), explicit_run_dir=True) is None
    assert _refuse_if_stale(Ledger(run_dir), explicit_run_dir=False) == 3


def test_guard_allows_a_working_ledger_that_is_not_behind(tmp_path) -> None:
    """The guard must not fire on an up-to-date run, or it is just noise."""
    from tti.cli import _committed_ledger_ahead
    from tti.ledger import Ledger

    run_dir = tmp_path / "runs"
    (run_dir / "raw").mkdir(parents=True)
    src = ROOT / "ledger" / "events.jsonl"
    (run_dir / "events.jsonl").write_text(src.read_text() if src.exists() else "")

    assert _committed_ledger_ahead(Ledger(run_dir)) == []


def test_guard_is_silent_when_pointed_at_the_committed_ledger_itself() -> None:
    """`--run-dir ledger` is a legitimate way to render the committed state."""
    from tti.cli import _committed_ledger_ahead
    from tti.ledger import Ledger

    assert _committed_ledger_ahead(Ledger(ROOT / "ledger")) == []
