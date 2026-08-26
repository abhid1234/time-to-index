"""Search provider adapters.

Each adapter does one thing: take a question string, return the provider's
verbatim JSON response. No normalisation, no scoring, no reshaping. The raw
payload is what gets stored and what the grader reads, so that a dispute
about a number is settled by re-reading the evidence rather than by trusting
this repo's parsing.

A provider whose key is absent from the environment is skipped, never
simulated. There is no fixture path that can leak into a published result.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .. import config


class Provider(Protocol):
    name: str

    def modes(self) -> list[str]: ...

    def available(self) -> bool: ...

    def search(self, question: str, mode: str, *, max_results: int,
               max_chars: int) -> dict: ...


_REGISTRY: dict[str, Callable[[], Provider]] = {}


def register(name: str):
    def deco(factory):
        _REGISTRY[name] = factory
        return factory
    return deco


def get(name: str) -> Provider:
    if name not in _REGISTRY:
        raise KeyError(f"unknown provider {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def all_names() -> list[str]:
    return sorted(_REGISTRY)


def available_arms() -> list[tuple[str, str]]:
    """Arms from settings.yaml whose provider key is actually present."""
    out = []
    for arm in config.settings().get("arms", []):
        p, m = arm["provider"], arm["mode"]
        try:
            prov = get(p)
        except KeyError:
            continue
        if prov.available():
            out.append((p, m))
    return out


from . import brave, exa, parallel, serper, tavily  # noqa: E402,F401
