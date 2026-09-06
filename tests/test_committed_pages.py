"""The two pages committed under docs/ must be what the current code renders.

Tonight the committed placeholder carried last week's page frame because the
CSS moved and nobody re-ran `tti placeholder`. A reader opening docs/ sees
the committed file, not the code, so drift there is a false statement about
the instrument. Timestamps are masked; everything else must match.

Only while docs/index.html is still the placeholder. Once a run has started,
the probe workflow renders that file with `tti report` from runs/, which is
gitignored, so no clean checkout can reproduce it -- the placeholder check
skips rather than assert something CI cannot verify. docs/demo.html is never
written by the workflow, so its check always applies.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti.cli import main

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAMP = re.compile(r"Generated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")


def _norm(text: str) -> str:
    return STAMP.sub("Generated <stamp>", text)


# Emitted only by report.placeholder_page(). Once a run has happened the
# probe workflow overwrites docs/index.html with `tti report` output and this
# sentence is gone, which is how the two states are told apart.
PRE_RUN = "No run has happened yet."


def test_the_committed_placeholder_is_the_one_the_code_renders(tmp_path):
    committed = (ROOT / "docs" / "index.html").read_text()
    if PRE_RUN not in committed:
        pytest.skip(
            "docs/index.html is a rendered report, not the placeholder. The probe "
            "workflow renders it with `tti report` from runs/, which is gitignored, "
            "so a clean checkout cannot reproduce it and asserting on it would be "
            "asserting something CI cannot verify. Do NOT run "
            "`tti placeholder --out-dir docs` to make this pass: that overwrites the "
            "live dashboard with an empty page until the next probe run."
        )
    assert main(["placeholder", "--out-dir", str(tmp_path)]) == 0
    fresh = (tmp_path / "index.html").read_text()
    assert _norm(fresh) == _norm(committed), \
        "docs/index.html is stale — run `python -m tti placeholder --out-dir docs` and commit it"


def test_the_committed_demo_is_the_one_the_code_renders(tmp_path):
    assert main(["demo", "--out-dir", str(tmp_path)]) == 0
    fresh = (tmp_path / "demo.html").read_text()
    committed = (ROOT / "docs" / "demo.html").read_text()
    assert _norm(fresh) == _norm(committed), \
        "docs/demo.html is stale — run `python -m tti demo` and commit it"
