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
        self.refunded = 0.0

    def remaining(self) -> float:
        return max(0.0, self.cap - self.spent)

    def can_afford(self, cost: float) -> bool:
        return self.spent + cost <= self.cap + 1e-9

    def refund(self, cost: float) -> None:
        """Give back a charge for a call that never completed.

        The cap is reserved before the request and released if it fails,
        because otherwise a provider having a bad hour consumes the whole
        day's budget without spending a cent and healthy probes are refused
        for money that was never billed. Measured: ten probes, a cap
        affording five, every call returning 503 -- five errors, five refused,
        $0.00 actually spent.

        This assumes failed requests are not billed, which is what the one
        vendor documentation we have says explicitly. Refunds are counted and
        reported so the assumption is visible rather than buried.
        """
        self.spent = max(0.0, self.spent - cost)
        self.refunded += cost

    def roll_to(self, day: str, spent_today: float) -> None:
        """Move to a new UTC day mid-run.

        A run that starts at 23:50 with the day nearly exhausted would
        otherwise keep refusing probes after midnight, against a cap that has
        already reset. That loses data in the conservative direction, which
        is still losing data.
        """
        if day != self.day:
            self.day = day
            self.spent = spent_today

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
    providers = config.providers_config()["providers"]
    if provider not in providers:
        # Realistic: an arm is removed from providers.yaml after it has
        # already written results. Pricing it as zero would let it spend
        # against a cap that cannot see it; guessing a price would be worse.
        raise config.ConfigError(
            f"data/providers.yaml has no entry for `{provider}`, but the ledger "
            f"references it. Restore the entry or the arm cannot be priced.")
    cfg = providers[provider]
    modes = cfg.get("modes", {})
    m = modes.get(mode) or next(iter(modes.values()))
    per_k = float(m.get("usd_per_1k_requests", 0.0))
    per_k_extra = float(m.get("usd_per_1k_extra_results", 0.0))
    included = int(m.get("results_included", n_results))
    extra = max(0, n_results - included)
    return (per_k + per_k_extra * extra) / 1000.0
