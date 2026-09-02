"""The two pages committed under docs/ must be what the current code renders.

Tonight the committed placeholder carried last week's page frame because the
CSS moved and nobody re-ran `tti placeholder`. A reader opening docs/ sees
the committed file, not the code, so drift there is a false statement about
the instrument. Timestamps are masked; everything else must match.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti.cli import main

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAMP = re.compile(r"Generated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")


def _norm(text: str) -> str:
    return STAMP.sub("Generated <stamp>", text)


def test_the_committed_placeholder_is_the_one_the_code_renders(tmp_path):
    assert main(["placeholder", "--out-dir", str(tmp_path)]) == 0
    fresh = (tmp_path / "index.html").read_text()
    committed = (ROOT / "docs" / "index.html").read_text()
    assert _norm(fresh) == _norm(committed), \
        "docs/index.html is stale — run `python -m tti placeholder --out-dir docs` and commit it"


def test_the_committed_demo_is_the_one_the_code_renders(tmp_path):
    assert main(["demo", "--out-dir", str(tmp_path)]) == 0
    fresh = (tmp_path / "demo.html").read_text()
    committed = (ROOT / "docs" / "demo.html").read_text()
    assert _norm(fresh) == _norm(committed), \
        "docs/demo.html is stale — run `python -m tti demo` and commit it"
