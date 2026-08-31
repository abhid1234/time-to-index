"""Correcting for the number of comparisons the leaderboard invites.

Six arms make fifteen pairwise comparisons. Testing each at alpha = 0.05 and
calling anything under it "distinguishable" gives a family-wise error rate of
1 - 0.95^15 = 54%: more likely than not, at least one pair is declared
different when neither is. That was this repository's behaviour, in two places,
and it is the most ordinary statistical mistake there is -- ordinary enough
that a benchmark built entirely around not over-claiming had it anyway.

Holm-Bonferroni rather than plain Bonferroni: it is a step-down procedure that
controls the family-wise error rate exactly as strictly, is uniformly more
powerful, and -- the reason it matters here -- makes no independence
assumption. Pairwise comparisons share arms, so their p-values are correlated,
and a procedure that needed independence would be the wrong tool.

Benjamini-Hochberg is deliberately not the default. It controls the false
discovery rate, which is the right target when a screen produces a list of
candidates for follow-up. A leaderboard is not a screen. Somebody reads one
row of it and picks a vendor, so the quantity to control is the chance that
*any* claimed difference is spurious, not the expected share of them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Adjusted:
    label: str
    raw: float
    adjusted: float

    def significant(self, alpha: float = 0.05) -> bool:
        return self.adjusted == self.adjusted and self.adjusted < alpha


def holm(pairs: list[tuple[str, float]]) -> list[Adjusted]:
    """Holm-Bonferroni step-down, returned in the input order.

    A NaN p-value means the comparison could not be evaluated -- too few
    events, an arm with no observations. Those are carried through as NaN and
    excluded from the family size, because counting an uncomputable comparison
    as a test would penalise every other comparison for it.
    """
    live = [(i, lab, p) for i, (lab, p) in enumerate(pairs)
            if isinstance(p, (int, float)) and not isinstance(p, bool)
            and math.isfinite(p)]
    m = len(live)
    out: list[Adjusted | None] = [None] * len(pairs)

    for i, lab, p in sorted(live, key=lambda t: t[2]):
        out[i] = Adjusted(lab, p, p)          # placeholder, filled below
    # Step-down with the running maximum: an adjusted p-value must never be
    # smaller than one for a more significant raw p-value, or the ordering the
    # correction is built on would be violated by its own output.
    running = 0.0
    for rank, (i, lab, p) in enumerate(sorted(live, key=lambda t: t[2])):
        adj = min(1.0, (m - rank) * p)
        running = max(running, adj)
        out[i] = Adjusted(lab, p, running)

    for i, (lab, p) in enumerate(pairs):
        if out[i] is None:
            out[i] = Adjusted(lab, float(p) if p == p else float("nan"),
                              float("nan"))
    return [a for a in out if a is not None]


def family_error_rate(m: int, alpha: float = 0.05) -> float:
    """The chance of at least one false positive across m independent tests.

    Printed beside the correction, because "we corrected for multiplicity" is
    a sentence and `1 - 0.95**15 = 0.54` is an argument.
    """
    if m <= 0:
        return 0.0
    return 1.0 - (1.0 - alpha) ** m


def note(m: int, alpha: float = 0.05) -> str:
    if m <= 1:
        return ""
    return (f"{m} pairwise comparisons. Testing each at "
            f"α = {alpha:g} without correction would give a "
            f"{family_error_rate(m, alpha) * 100:.0f}% chance that at least "
            f"one pair is called different when neither is, so the p-values "
            f"below are Holm-Bonferroni adjusted and the verdict uses the "
            f"adjusted value.")
