"""Core data model.

Three record types move through the system:

    Event        a fact that entered the world at a known instant, plus the
                 question that fact answers and the answer it superseded.
    Probe        an intent to ask one provider one question at one moment.
    ProbeResult  what came back, graded.

Everything is a plain dataclass with `to_dict` / `from_dict` so the ledger
stays newline-delimited JSON that anyone can re-grade without our code.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

FRESH = "FRESH"        # the new answer is present in the response
STALE = "STALE"        # the superseded answer is present and the new one is not
ABSENT = "ABSENT"      # neither answer is present
ERROR = "ERROR"        # the call failed; excluded from all rates
SKIPPED = "SKIPPED"    # never dispatched (budget cap, or already resolved FRESH)

VERDICTS = (FRESH, STALE, ABSENT, ERROR, SKIPPED)

# Source classes. Staleness is only defined where supersession exists, i.e.
# where a question that had answer A now has answer B and A is wrong.
SUPERSEDING_CLASSES = frozenset({"package_registry", "code_release", "regulatory_filing"})


def _sha(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class Event:
    """A newly published fact with a publisher-side timestamp."""

    source: str                     # collector id, e.g. "npm"
    source_class: str               # "package_registry" | "code_release" | ...
    subject: str                    # "next", "apple-inc-10-Q", "vercel/next.js"
    published_at: float             # UNIX seconds, UTC. Publisher's own clock.
    discovered_at: float            # UNIX seconds, UTC. When our collector saw it.
    question: str                   # the natural-language query we will ask
    answer: str                     # canonical fresh answer token
    answer_aliases: list[str] = field(default_factory=list)
    predecessor: str | None = None  # canonical superseded answer token
    predecessor_aliases: list[str] = field(default_factory=list)
    url: str = ""                   # canonical URL of the new fact (never sent to providers)
    # Origin URLs for the control arm, most crawler-representative first.
    # A human-facing page is what a search crawler would index, so it leads;
    # an API URL is a fallback that answers a weaker question ("the fact was
    # public") and is labelled as such in the record.
    origins: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = _sha(self.source, self.subject, self.answer)
        if self.answer not in self.answer_aliases:
            self.answer_aliases.insert(0, self.answer)
        if self.predecessor and self.predecessor not in self.predecessor_aliases:
            self.predecessor_aliases.insert(0, self.predecessor)
        if not self.origins and self.url:
            self.origins = [self.url]

    @property
    def detection_lag(self) -> float:
        """Seconds between publication and our collector noticing.

        Events with a large detection lag are dropped: we cannot claim a
        provider was slow to index something we ourselves found late.
        """
        return self.discovered_at - self.published_at

    @property
    def measures_staleness(self) -> bool:
        return bool(self.predecessor) and self.source_class in SUPERSEDING_CLASSES

    to_dict = lambda self: dataclasses.asdict(self)  # noqa: E731

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Event:
        return cls(**d)


@dataclass(slots=True)
class Probe:
    """A scheduled question. Idempotent on (event_id, provider, mode, rung)."""

    event_id: str
    provider: str
    mode: str            # provider-specific mode, e.g. "advanced" / "auto" / "basic"
    rung: int            # target lag in seconds after publication
    due_at: float        # UNIX seconds, = event.published_at + rung
    phrasing: int = 0    # 0 = the canonical question; see tti/phrasing.py
    probe_id: str = ""

    def __post_init__(self) -> None:
        if not self.probe_id:
            parts = [self.event_id, self.provider, self.mode, str(self.rung)]
            # Phrasing joins the hash only when non-zero, so a ledger written
            # before this axis existed keeps its ids and stays re-gradable.
            if self.phrasing:
                parts.append(f"p{self.phrasing}")
            self.probe_id = _sha(*parts)

    to_dict = lambda self: dataclasses.asdict(self)  # noqa: E731

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Probe:
        return cls(**d)


@dataclass(slots=True)
class ProbeResult:
    probe_id: str
    event_id: str
    provider: str
    mode: str
    rung: int
    requested_at: float        # UNIX seconds when the call was dispatched
    lag: float                 # requested_at - event.published_at, the x-axis
    verdict: str
    phrasing: int = 0          # which wording was asked; see tti/phrasing.py
    # Origin-control only: where in the document the fact was found. Empty
    # for provider arms. See control.classify_render.
    render: str = ""
    latency_ms: int = 0
    matched_fresh: list[str] = field(default_factory=list)
    matched_stale: list[str] = field(default_factory=list)
    n_results: int = 0
    chars: int = 0
    cost_usd: float = 0.0
    # "list": priced from data/providers.yaml. "reported": the vendor stated
    # the charge in its response and that number was recorded instead.
    cost_source: str = "list"
    raw_ref: str = ""          # relative path to the stored raw payload
    note: str = ""             # error text, or skip reason

    to_dict = lambda self: dataclasses.asdict(self)  # noqa: E731

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProbeResult:
        return cls(**d)


def dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
