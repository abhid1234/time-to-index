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
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .models import ABSENT, FRESH, STALE, Event

# Fields we treat as retrieved content. Anything not listed is ignored, which
# keeps a provider from scoring on its own echo of our query.
_TEXT_KEYS = frozenset({
    "title", "snippet", "description", "text", "content", "excerpt", "excerpts",
    "summary", "highlight", "highlights", "extract", "raw_content", "body",
    "page_content", "chunk",
})
_SKIP_KEYS = frozenset({"url", "link", "id", "source_url", "request_id", "query", "objective"})


@dataclass(frozen=True)
class Rules:
    """The grading rules, as data.

    Every one of these is a judgement call, and a benchmark whose conclusion
    depends on an author's judgement calls should be able to say by how much.
    Making them a parameter is what lets `tti sensitivity` re-grade the stored
    payloads under deliberately worse rules and report how far the leaderboard
    moves. If it barely moves, the choices did not matter. If it reorders, the
    right thing is to publish that alongside the ranking.
    """
    name: str = "strict"
    text_keys: frozenset = field(default_factory=lambda: _TEXT_KEYS)
    skip_keys: frozenset = field(default_factory=lambda: _SKIP_KEYS)
    boundary: bool = True        # False = plain substring, the classic trap
    allow_v_prefix: bool = True
    use_aliases: bool = True
    min_token_len: int = 3
    max_depth: int = 12
    # Characters kept from each text leaf before matching; 0 = all of it. The
    # arms do not return the same amount of text per result -- an excerpt
    # API returns up to `max_chars_per_result`, a classic snippet API ~160
    # characters -- and a version string deep in a long excerpt is a hit
    # that a short snippet could never have carried. The `snippet-window`
    # variant grades every arm as though it had returned short snippets.
    max_chars_per_field: int = 0


def flatten_text(payload: Any, _depth: int = 0, rules: Rules | None = None) -> str:
    """Collect provider-returned content into one string.

    Deliberately conservative: it walks the response tree and keeps values
    only under known content keys, so a change in a provider's envelope
    cannot accidentally start feeding query echo into the grader.
    """
    rules = rules or DEFAULT
    if _depth > rules.max_depth:
        return ""
    out: list[str] = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            lk = str(k).lower()
            if lk in rules.skip_keys:
                continue
            if lk in rules.text_keys:
                out.append(_stringify(v, _depth + 1, rules.max_chars_per_field))
            elif isinstance(v, (dict, list)):
                out.append(flatten_text(v, _depth + 1, rules))
    elif isinstance(payload, list):
        for v in payload:
            out.append(flatten_text(v, _depth + 1, rules))
    return "\n".join(s for s in out if s)


def _stringify(v: Any, _depth: int = 0, limit: int = 0) -> str:
    # Depth-bounded like flatten_text. Without this, a known content key
    # holding a deeply nested value recurses without limit, and a provider
    # response is attacker-adjacent input: it is not worth a stack overflow
    # in an unattended job to read one more level.
    #
    # `limit` applies per leaf string, not to the joined result: a list of
    # ten excerpts windowed to 160 characters is ten short snippets, which
    # is the thing being simulated, not one.
    if _depth > 12:
        return ""
    if isinstance(v, str):
        return v[:limit] if limit else v
    if isinstance(v, list):
        return "\n".join(_stringify(x, _depth + 1, limit) for x in v)
    if isinstance(v, dict):
        return "\n".join(_stringify(x, _depth + 1, limit) for x in v.values())
    return ""


def _pattern(token: str, boundary: bool = True,
             allow_v: bool = True) -> re.Pattern[str]:
    """Boundary-safe matcher for one answer token.

    The lookarounds exclude word characters and dots on both sides, so
    `15.4.1` does not match inside `15.4.10` or `v115.4.1x`, while still
    matching in `next@15.4.1,` or `(15.4.1)`.

    The optional `v` is not cosmetic. Half the web writes a release as
    `v15.4.2`, and the strict lookbehind rejects that -- the character before
    the digits is a word character. Every version-shaped answer would then
    score ABSENT against a response that plainly contains it. Including the
    `v` inside the match moves the lookbehind to the character before it, so
    `v15.4.2` matches while `115.4.2` still does not. Applied only to tokens
    that start with a digit, so it cannot loosen matching on an identifier
    that happens to begin with a letter.
    """
    core = re.escape(token)
    if not boundary:
        return re.compile(core, re.IGNORECASE)
    if allow_v and token[:1].isdigit():
        core = "[vV]?" + core
    return re.compile(rf"(?<![\w.]){core}(?![\w.])", re.IGNORECASE)


_PATTERN_CACHE: dict[tuple[str, bool, bool], re.Pattern[str]] = {}


def _match(text: str, tokens: Iterable[str], rules: Rules) -> list[str]:
    hits = []
    for t in tokens:
        t = (t or "").strip()
        if len(t) < rules.min_token_len:   # too short to be evidence
            continue
        key = (t, rules.boundary, rules.allow_v_prefix)
        pat = _PATTERN_CACHE.get(key)
        if pat is None:
            pat = _PATTERN_CACHE[key] = _pattern(t, rules.boundary,
                                                 rules.allow_v_prefix)
        if pat.search(text):
            hits.append(t)
    return hits


def grade(event: Event, payload: Any,
          rules: Rules | None = None) -> tuple[str, list[str], list[str], int]:
    """Return (verdict, fresh_hits, stale_hits, chars_scanned)."""
    rules = rules or DEFAULT
    text = flatten_text(payload, rules=rules)
    fresh_tokens = event.answer_aliases if rules.use_aliases else [event.answer]
    stale_tokens = (event.predecessor_aliases if rules.use_aliases
                    else ([event.predecessor] if event.predecessor else []))
    fresh_hits = _match(text, fresh_tokens, rules)
    stale_hits = _match(text, stale_tokens, rules) if event.predecessor else []
    if fresh_hits:
        return FRESH, fresh_hits, stale_hits, len(text)
    if stale_hits:
        return STALE, [], stale_hits, len(text)
    return ABSENT, [], [], len(text)


DEFAULT = Rules()

# Deliberately worse rules, for `tti sensitivity`. Each isolates one judgement
# call so its effect on the leaderboard can be measured rather than argued.
VARIANTS = [
    DEFAULT,
    Rules(name="naive-substring", boundary=False),
    Rules(name="no-v-prefix", allow_v_prefix=False),
    Rules(name="canonical-token-only", use_aliases=False),
    Rules(name="urls-count-as-evidence", skip_keys=frozenset({"query", "objective"})),
    Rules(name="titles-only", text_keys=frozenset({"title"})),
    Rules(name="shallow-walk", max_depth=2),
    Rules(name="snippet-window", max_chars_per_field=160),
]
