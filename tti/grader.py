"""Verdict assignment.

A provider response is flattened to text and scanned for two token sets: the
answer the event created, and the answer it superseded. Three outcomes:

    FRESH   the new token is present
    STALE   the old token is present and the new one is not
    ABSENT  neither

Most retrieval benchmarks collapse the second and third into one bucket
called "wrong". They are not the same failure. An agent that gets nothing
back retries, widens, or tells the user it does not know. An agent that gets
last quarter's number back cites it. Separating them is the reason this
repo exists.

Matching rules, in order of how much trouble they save:

1.  Version and identifier tokens are matched on non-word, non-dot
    boundaries. Plain substring matching scores "15.4.1" as present inside
    "15.4.10", which silently inflates every provider's freshness on exactly
    the fast-moving packages the benchmark cares about most.
2.  Both sets present means FRESH. A changelog page listing every release
    contains the superseded token by construction; that page is a correct
    retrieval, not a stale one.
3.  Grading reads only fields the provider returned as content -- titles,
    snippets, extracted text. URLs are excluded, because a URL can carry a
    version string that the page body contradicts.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .models import ABSENT, FRESH, STALE, Event

# Fields we treat as retrieved content. Anything not listed is ignored, which
# keeps a provider from scoring on its own echo of our query.
_TEXT_KEYS = {
    "title", "snippet", "description", "text", "content", "excerpt", "excerpts",
    "summary", "highlight", "highlights", "extract", "raw_content", "body",
    "page_content", "chunk",
}
_SKIP_KEYS = {"url", "link", "id", "source_url", "request_id", "query", "objective"}


def flatten_text(payload: Any, _depth: int = 0) -> str:
    """Collect provider-returned content into one string.

    Deliberately conservative: it walks the response tree and keeps values
    only under known content keys, so a change in a provider's envelope
    cannot accidentally start feeding query echo into the grader.
    """
    if _depth > 12:
        return ""
    out: list[str] = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            lk = str(k).lower()
            if lk in _SKIP_KEYS:
                continue
            if lk in _TEXT_KEYS:
                out.append(_stringify(v))
            elif isinstance(v, (dict, list)):
                out.append(flatten_text(v, _depth + 1))
    elif isinstance(payload, list):
        for v in payload:
            out.append(flatten_text(v, _depth + 1))
    return "\n".join(s for s in out if s)


def _stringify(v: Any) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "\n".join(_stringify(x) for x in v)
    if isinstance(v, dict):
        return "\n".join(_stringify(x) for x in v.values())
    return ""


def _pattern(token: str) -> re.Pattern[str]:
    """Boundary-safe matcher for one answer token.

    The lookarounds exclude word characters and dots on both sides so that
    `15.4.1` does not match inside `15.4.10` or `v115.4.1x`, while still
    matching in `next@15.4.1,` or `(15.4.1)`.
    """
    return re.compile(rf"(?<![\w.]){re.escape(token)}(?![\w.])", re.IGNORECASE)


_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _match(text: str, tokens: Iterable[str]) -> list[str]:
    hits = []
    for t in tokens:
        t = (t or "").strip()
        if len(t) < 3:          # too short to be evidence of anything
            continue
        pat = _PATTERN_CACHE.get(t)
        if pat is None:
            pat = _PATTERN_CACHE[t] = _pattern(t)
        if pat.search(text):
            hits.append(t)
    return hits


def grade(event: Event, payload: Any) -> tuple[str, list[str], list[str], int]:
    """Return (verdict, fresh_hits, stale_hits, chars_scanned)."""
    text = flatten_text(payload)
    fresh_hits = _match(text, event.answer_aliases)
    stale_hits = _match(text, event.predecessor_aliases) if event.predecessor else []
    if fresh_hits:
        return FRESH, fresh_hits, stale_hits, len(text)
    if stale_hits:
        return STALE, [], stale_hits, len(text)
    return ABSENT, [], [], len(text)
