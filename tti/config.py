"""Configuration loading.

All tunables live in YAML under `data/` so that a fork can change the
watchlist, the probe ladder, or the cost table without touching code.
Secrets come from the environment only.
"""

from __future__ import annotations

import os
import pathlib
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RUNS = pathlib.Path(os.environ.get("TTI_RUN_DIR", ROOT / "runs"))

# Ladder of target lags, in seconds after publication. A probe fires once per
# rung per provider until that provider answers FRESH, after which the
# remaining rungs are skipped (see METHODOLOGY.md, "Carry-forward").
DEFAULT_LADDER = [300, 900, 3600, 21_600, 86_400, 259_200]

# An event whose detection lag exceeds this is discarded, not probed. We cannot
# attribute our own collection delay to a provider.
MAX_DETECTION_LAG = 600.0

# A probe fired more than this far past its due time is dropped rather than
# recorded at the wrong rung.
MAX_RUNG_SLIP = 600.0

_cache: dict[str, Any] = {}


def load(name: str) -> Any:
    if name not in _cache:
        with open(DATA / f"{name}.yaml", "r", encoding="utf-8") as fh:
            _cache[name] = yaml.safe_load(fh)
    return _cache[name]


def settings() -> dict[str, Any]:
    return load("settings")


def ladder() -> list[int]:
    return list(settings().get("ladder", DEFAULT_LADDER))


def watchlist() -> dict[str, Any]:
    return load("watchlist")


def providers_config() -> dict[str, Any]:
    return load("providers")


def api_key(env_var: str) -> str | None:
    v = os.environ.get(env_var, "").strip()
    return v or None


def contact_ua() -> str:
    """SEC and arXiv both require a real contact string in User-Agent."""
    return os.environ.get(
        "TTI_USER_AGENT",
        "time-to-index/0.1 (open benchmark; set TTI_USER_AGENT to your contact)",
    )
