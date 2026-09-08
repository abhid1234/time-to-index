"""The page, the generator and the workflow have to agree about one file.

`docs/playground.html` fetches `data/observed.json`. `tti observed` writes
it. `probe.yml` commits it. Any one of those three drifting leaves the panel
silently hidden on the published site -- which looks exactly like "no data
yet", the one thing this project must never say by accident.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti.cli import main

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAYGROUND = ROOT / "docs" / "playground.html"
COMMITTED = ROOT / "docs" / "data" / "observed.json"
WORKFLOW = ROOT / ".github" / "workflows" / "probe.yml"


def test_the_page_fetches_the_path_the_generator_writes(tmp_path):
    main(["--run-dir", str(tmp_path), "observed", "--out-dir", str(tmp_path / "docs")])
    written = tmp_path / "docs" / "data" / "observed.json"
    assert written.exists()
    # Relative, because the page is served from docs/ on GitHub Pages and an
    # absolute path would break on a project site served under /<repo>/.
    assert 'fetch("data/observed.json"' in PLAYGROUND.read_text()
    assert written.relative_to(tmp_path / "docs").as_posix() == "data/observed.json"


def test_the_workflow_commits_the_file_the_page_reads():
    """It is written on every report; if it is not added it never ships."""
    assert "docs/data/observed.json" in WORKFLOW.read_text()


def test_an_empty_ledger_still_writes_a_readable_file(tmp_path):
    """The panel hides itself on no events. It must not hide on a parse error."""
    assert main(["--run-dir", str(tmp_path), "observed",
                 "--out-dir", str(tmp_path / "docs")]) == 0
    data = json.loads((tmp_path / "docs" / "data" / "observed.json").read_text())
    assert data["events"] == []
    assert data["totals"]["events"] == 0


@pytest.mark.skipif(not COMMITTED.exists(),
                    reason="no run has published observed.json yet")
def test_the_committed_file_has_the_shape_the_page_indexes_into():
    """The page reads these keys positionally; a rename here renders blanks."""
    data = json.loads(COMMITTED.read_text())
    assert {"generated_at", "events", "totals"} <= set(data)
    for ev in data["events"]:
        assert {"subject", "answer", "question", "rungs", "rung_labels",
                "arms", "detection_lag", "age_seconds"} <= set(ev)
        assert len(ev["rungs"]) == len(ev["rung_labels"])
        for arm in ev["arms"]:
            assert {"provider", "mode", "control", "cells", "spend_usd"} <= set(arm)
            # One cell per rung, positionally -- the page zips them against
            # the header row it built from rung_labels.
            assert len(arm["cells"]) == len(ev["rungs"])
            for cell in arm["cells"]:
                assert cell["state"] in {"graded", "scheduled", "pending",
                                         "never_scheduled"}
                if cell["state"] == "graded":
                    assert "verdict" in cell
                else:
                    # The invariant the whole panel rests on.
                    assert "verdict" not in cell
