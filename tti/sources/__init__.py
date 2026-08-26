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
from typing import Any, Callable, Iterable, Protocol

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
        self.attempted = 0
        # Cap on subjects polled this call. `tti doctor` sets it low: a
        # reachability check does not need the whole watchlist, and one that
        # takes two minutes will not be run before the run that needed it.
        self.max_subjects: int | None = None

    def fan_out(self, fn: Callable[[Any], list[Event]], items: Iterable[Any]) -> list[Event]:
        items = list(items)
        if self.max_subjects is not None:
            items = items[:self.max_subjects]
        self.attempted += len(items)
        out: list[Event] = []
        if not items:
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
