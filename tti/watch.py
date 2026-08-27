"""Crawlability over time.

A single scan says a page is unreadable today. It cannot say the page used to
be readable, which is the more useful and much more actionable statement: a
site did not decide to become invisible to agents, it shipped a refactor and
nobody noticed. Nothing warns about that. There is no build check, no deploy
gate, no dashboard panel — a route can go from server-rendered to a client
shell in a routine pull request and every existing signal stays green.

So the survey gets a ledger. Each run appends one line per target; the report
compares consecutive *judged* observations of the same URL and reports where
posture moved.

The comparison rules matter more than the storage:

    Only judged observations count. A page that was readable, then
    unreachable, then readable has not changed twice. Interception, instability
    and fetch failures are recorded and skipped when pairing, or the report
    fills with transitions that describe the network.

    Body changes are not posture changes. Pages get edited constantly; the
    content hash moves every day on a healthy site. Posture is the signal.

    A large fall in readable text without a posture change is reported
    separately. Going from 40,000 visible characters to 1,200 is a real
    regression even if both still classify as server-rendered, and it is the
    shape a partial migration takes.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from dataclasses import dataclass, field

from .framework import NO_BODY
from .survey import Survey

FILENAME = "crawl.jsonl"

# A drop this large in readable text is reported even when the posture label
# is unchanged. Chosen to be obviously beyond editorial variation: pages get
# rewritten, they do not usually lose four fifths of their text.
TEXT_DROP_RATIO = 0.2
TEXT_DROP_FLOOR = 500


@dataclass
class Observation:
    at: float
    url: str
    category: str = ""
    judged: bool = False
    posture: str = ""
    verdict: str = ""
    visible_chars: int = 0
    bytes_total: int = 0
    framework: str = ""
    body_sha: str = ""
    why_unusable: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> Observation:
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})


@dataclass
class Change:
    url: str
    at: float
    prev_at: float
    kind: str                # "posture" | "text_drop"
    before: str = ""
    after: str = ""
    before_chars: int = 0
    after_chars: int = 0

    @property
    def worsened(self) -> bool:
        if self.kind == "text_drop":
            return True
        readable = {"server_rendered", "static_html"}
        return self.before in readable and self.after not in readable

    def describe(self) -> str:
        if self.kind == "text_drop":
            return (f"readable text fell from {self.before_chars:,} to "
                    f"{self.after_chars:,} characters with no posture change")
        return (f"{self.before} -> {self.after} "
                f"({self.before_chars:,} -> {self.after_chars:,} chars)")


def path(run_dir: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(run_dir) / FILENAME


def record(sv: Survey, run_dir: pathlib.Path, now: float | None = None) -> int:
    """Append one line per target. Returns the number written."""
    now = now if now is not None else time.time()
    p = path(run_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in sv.results:
        judged = r.usable
        rows.append(Observation(
            at=now, url=r.url, category=r.category, judged=judged,
            posture=(r.prof.posture if r.prof else NO_BODY),
            verdict=r.verdict,
            visible_chars=(r.prof.visible_chars if r.prof else 0),
            bytes_total=(r.prof.bytes_total if r.prof else 0),
            framework=(r.prof.framework if r.prof else ""),
            body_sha=r.body_sha,
            why_unusable=("" if judged else r.why_unusable),
        ))
    with open(p, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row.to_dict(), sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return len(rows)


def history(run_dir: pathlib.Path) -> dict[str, list[Observation]]:
    p = path(run_dir)
    out: dict[str, list[Observation]] = {}
    if not p.exists():
        return out
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obs = Observation.from_dict(json.loads(line))
            except (json.JSONDecodeError, TypeError):
                continue
            out.setdefault(obs.url, []).append(obs)
    for v in out.values():
        v.sort(key=lambda o: o.at)
    return out


def changes(hist: dict[str, list[Observation]]) -> list[Change]:
    """Posture moves and large text regressions between judged observations."""
    out: list[Change] = []
    for url, obs in hist.items():
        judged = [o for o in obs if o.judged]
        for prev, cur in zip(judged, judged[1:], strict=False):
            if prev.posture != cur.posture:
                out.append(Change(url=url, at=cur.at, prev_at=prev.at,
                                  kind="posture", before=prev.posture,
                                  after=cur.posture,
                                  before_chars=prev.visible_chars,
                                  after_chars=cur.visible_chars))
                continue
            # Same label, far less text: a partial migration looks like this.
            if (prev.visible_chars >= TEXT_DROP_FLOOR
                    and cur.visible_chars < prev.visible_chars * TEXT_DROP_RATIO):
                out.append(Change(url=url, at=cur.at, prev_at=prev.at,
                                  kind="text_drop", before=prev.posture,
                                  after=cur.posture,
                                  before_chars=prev.visible_chars,
                                  after_chars=cur.visible_chars))
    out.sort(key=lambda c: c.at)
    return out


@dataclass
class Coverage:
    urls: int = 0
    runs: int = 0
    first: float = 0.0
    last: float = 0.0
    judged_rate: float = 0.0
    never_judged: list[str] = field(default_factory=list)

    @property
    def span_days(self) -> float:
        return (self.last - self.first) / 86_400 if self.last > self.first else 0.0


def coverage(hist: dict[str, list[Observation]]) -> Coverage:
    """How much history there is, so a report cannot imply more than it has.

    Two runs an hour apart will show almost no change, and saying "no site
    changed posture" from that would be a claim about the observation window
    rather than about the web.
    """
    cov = Coverage(urls=len(hist))
    stamps = sorted({o.at for obs in hist.values() for o in obs})
    if not stamps:
        return cov
    cov.runs = len(stamps)
    cov.first, cov.last = stamps[0], stamps[-1]
    total = sum(len(v) for v in hist.values())
    judged = sum(1 for v in hist.values() for o in v if o.judged)
    cov.judged_rate = judged / total if total else 0.0
    cov.never_judged = sorted(u for u, v in hist.items()
                              if not any(o.judged for o in v))
    return cov
