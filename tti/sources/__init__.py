"""Event collectors.

A source qualifies only if it stamps its own publication time. That is the
whole selection rule, and it rules out most of the web. A news article's
"published" field is whatever the CMS says and moves when the page is edited;
a package registry's upload time is a receipt.

Every collector returns Events whose `published_at` is the publisher's clock,
not ours, and whose `discovered_at` is ours. The gap between them is the
collector's own latency, and events where that gap is large are dropped
upstream in the scheduler rather than charged to a provider.
"""

from __future__ import annotations

import concurrent.futures as cf
import time
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from ..models import Event


class BaseSource:
    """Shared plumbing: bounded-concurrency polling and visible failures.

    A collector that swallows its exceptions reports an unreachable host as
    "no new releases", which is the same silent-failure shape this benchmark
    exists to measure in other people's systems. So every subject-level
    exception is recorded on `self.errors` and surfaced by `discover`, and a
    source whose every subject failed is reported as broken rather than quiet.
    """

    name = "base"
    source_class = "unknown"
    workers = 8

    def __init__(self) -> None:
        self.errors: list[str] = []
        # Non-fatal, per-subject. The subject was collected and the event is
        # real; something about it deserves a human's eye before it becomes
        # an error -- a packument nearing its size bound, for instance.
        self.warnings: list[str] = []
        self.attempted = 0
        # Cap on subjects polled this call. `tti doctor` sets it low: a
        # reachability check does not need the whole watchlist, and one that
        # takes two minutes will not be run before the run that needed it.
        self.max_subjects: int | None = None
        # Minimum seconds between consecutive requests when workers == 1.
        # For publishers whose terms say "one request every N seconds and a
        # single connection at a time" -- arXiv's exact words -- a thread pool
        # of any size is a violation, and a comment saying otherwise is not a
        # rate limiter.
        self.min_interval: float = 0.0

    def fan_out(self, fn: Callable[[Any], list[Event]], items: Iterable[Any]) -> list[Event]:
        items = list(items)
        if self.max_subjects is not None:
            items = items[:self.max_subjects]
        self.attempted += len(items)
        out: list[Event] = []
        if not items:
            return out
        if self.workers == 1 and self.min_interval > 0:
            # Sequential and spaced. Same error accounting as the pool path,
            # so a broken subject reads the same whichever way it was fetched.
            for i, it in enumerate(items):
                if i:
                    time.sleep(self.min_interval)
                try:
                    out.extend(fn(it) or [])
                except Exception as exc:  # noqa: BLE001
                    self.errors.append(f"{it}: {type(exc).__name__}: {exc}"[:200])
            return out
        with cf.ThreadPoolExecutor(max_workers=min(self.workers, len(items))) as pool:
            futures = {pool.submit(fn, it): it for it in items}
            for fut in cf.as_completed(futures):
                try:
                    out.extend(fut.result() or [])
                except Exception as exc:  # noqa: BLE001
                    self.errors.append(f"{futures[fut]}: {type(exc).__name__}: {exc}"[:200])
        return out

    @property
    def all_failed(self) -> bool:
        return self.attempted > 0 and len(self.errors) == self.attempted


class Source(Protocol):
    name: str
    source_class: str
    errors: list[str]

    def collect(self, seen: dict[tuple[str, str], str]) -> list[Event]:
        """Return newly published events. `seen` maps (source, subject) to the
        last answer recorded, so a collector can tell a genuine new release
        from its own restart."""
        ...


_REGISTRY: dict[str, Callable[[], Source]] = {}


def register(name: str):
    def deco(factory):
        _REGISTRY[name] = factory
        return factory
    return deco


def get(name: str) -> Source:
    if name not in _REGISTRY:
        raise KeyError(f"unknown source {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def available() -> list[str]:
    return sorted(_REGISTRY)


# Import for side effects: each module registers itself.
from . import arxiv, edgar, federal_register, github_releases, npm, pypi  # noqa: E402,F401


def subject_names(messages: list[str], limit: int = 8) -> str:
    """The subjects behind a list of "<subject>: <detail>" messages.

    Printed instead of the first message alone. The first real run against
    the live registry reported "12/46 subjects failed -- antd: ..." and the
    other eleven, one of which was `next`, took a separate script to learn.
    A count with one example is a number; a list of names is a finding.
    """
    names = []
    for m in messages:
        n = m.split(":", 1)[0].strip()
        if n and n not in names:
            names.append(n)
    shown = ", ".join(names[:limit])
    rest = len(names) - limit
    return shown + (f", +{rest} more" if rest > 0 else "")
