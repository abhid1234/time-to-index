"""Words this project does not use, enforced rather than remembered.

There is exactly one entry so far. "Honest" and "honestly" are house-banned
because they read as filler -- the sentence is always stronger with the claim
stated directly -- and because a benchmark arguing about truthfulness that
keeps *asserting* its own is doing the weaker version of the thing.

It had leaked into twenty-four places before anyone counted, including the
demo data on the playground, which put it in the launch video and on the
thumbnail. A style rule nobody can grep for is a style rule that decays, so
this greps.

Substitutes that carry the same weight: straight, candid, plain, truthful,
accurate, or just the claim on its own.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
BANNED = re.compile(r"\bhonest(ly|y)?\b", re.I)

# Everything the project itself writes. Not .git, not caches, and not the
# ledger -- raw provider payloads are evidence, and editing evidence to suit a
# style rule is the one thing this repo must never do.
SUFFIXES = {".py", ".md", ".html", ".yaml", ".yml", ".toml", ".txt", ".css", ".js"}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache",
             "ledger", ".ruff_cache", "htmlcov"}


def _sources() -> list[pathlib.Path]:
    out = []
    for p in ROOT.rglob("*"):
        if p.suffix not in SUFFIXES or not p.is_file():
            continue
        if SKIP_DIRS & set(p.relative_to(ROOT).parts):
            continue
        out.append(p)
    return out


def test_banned_word_absent() -> None:
    hits = []
    for p in _sources():
        if p.name == "test_prose.py":      # this file names the word on purpose
            continue
        for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if BANNED.search(line):
                hits.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()[:90]}")
    assert not hits, ("banned word found in " + str(len(hits)) + " place(s):\n  "
                      + "\n  ".join(hits))


def test_the_check_can_fail() -> None:
    """A guard that cannot fire is decoration."""
    assert BANNED.search("that is the honest answer")
    assert BANNED.search("Honestly, it drifted")
    assert not BANNED.search("dishonestly")   # word boundary, not substring
    assert not BANNED.search("a straight answer")
