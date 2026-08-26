"""Hard spend cap.

The rule this file enforces: a probe that would push today's spend past the
cap is never dispatched, and its refusal is written to the ledger as a
SKIPPED result with a reason. Silent truncation is the one failure mode that
would make the published numbers a lie, because a benchmark that quietly
stops probing looks identical to a provider that quietly stopped indexing.
"""

from __future__ import annotations

import datetime as dt

from . import config


class BudgetExceeded(RuntimeError):
    pass


def utc_day(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


class Budget:
    def __init__(self, cap_usd: float | None = None, spent_today: float = 0.0, day: str = ""):
        s = config.settings()
        self.cap = float(cap_usd if cap_usd is not None else s.get("daily_usd_cap", 5.0))
        self.spent = float(spent_today)
        self.day = day
        self.refused = 0

    def remaining(self) -> float:
        return max(0.0, self.cap - self.spent)

    def can_afford(self, cost: float) -> bool:
        return self.spent + cost <= self.cap + 1e-9

    def charge(self, cost: float) -> None:
        if not self.can_afford(cost):
            self.refused += 1
            raise BudgetExceeded(
                f"daily cap ${self.cap:.2f} reached "
                f"(spent ${self.spent:.4f}, next call ${cost:.4f})"
            )
        self.spent += cost


def unit_cost(provider: str, mode: str, n_results: int = 5) -> float:
    """USD for one call, from data/providers.yaml.

    Published list prices, not negotiated rates. Every number in that file
    carries the URL it came from so a reader can check it against the vendor's
    own page rather than trusting this repo.
    """
    cfg = config.providers_config()["providers"][provider]
    modes = cfg.get("modes", {})
    m = modes.get(mode) or next(iter(modes.values()))
    per_k = float(m.get("usd_per_1k_requests", 0.0))
    per_k_extra = float(m.get("usd_per_1k_extra_results", 0.0))
    included = int(m.get("results_included", n_results))
    extra = max(0, n_results - included)
    return (per_k + per_k_extra * extra) / 1000.0
