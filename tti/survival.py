"""Interval-censored survival estimation.

Kaplan-Meier is the wrong estimator for this data, and it is wrong in a way
that flatters slow providers.

An arm probed at 15m (ABSENT) and 1h (FRESH) did not index at 1h. It indexed
somewhere in (15m, 1h]. Kaplan-Meier takes a point event time, so feeding it
the rung records an event at 1h and systematically overstates every latency
by up to the width of a bracket. Worse, when a probe is dropped -- budget cap,
rung slip, provider error -- the true interval widens to (15m, 6h], and
Kaplan-Meier has no way to say that. It either invents a rung that was never
observed or discards the event.

Turnbull's nonparametric maximum likelihood estimator handles exactly this.
Each observation is an interval (L, R]; right-censored observations are
(L, inf). The estimator finds the support intervals -- the maximal regions
where the data can actually locate probability mass -- and solves for the
mass on each by self-consistency (Turnbull 1976; the EM formulation of
Gentleman and Geyer 1994).

The payoff is not academic. It means a run with a flaky provider, an
exhausted budget, or a runner that missed a cron tick still contributes its
events at the correct, honestly widened, precision instead of being dropped
or silently mis-binned.

The survival function it produces is undefined *inside* a support interval:
the data genuinely cannot say where in (15m, 1h] the mass sits. Reporting a
point median would be inventing that information, so quantiles come back as
brackets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

INF = float("inf")


@dataclass(frozen=True, slots=True)
class Interval:
    """One observation: the fact became retrievable in (lo, hi].

    lo is the last lag at which the arm was observed *not* to have it.
    hi is the first lag at which it was observed to have it, or infinity if
    that never happened inside the window.
    """
    lo: float
    hi: float

    @property
    def censored(self) -> bool:
        return self.hi == INF

    def contains(self, q: float, p: float) -> bool:
        """Is support interval (q, p] entirely inside this observation?"""
        return q >= self.lo and p <= self.hi


@dataclass
class NPMLE:
    """The fitted estimator."""
    support: list[tuple[float, float]] = field(default_factory=list)
    mass: list[float] = field(default_factory=list)
    n: int = 0
    iterations: int = 0
    converged: bool = True
    loglik: float = 0.0

    # -- the survival function ------------------------------------------
    def cdf_upper(self, t: float) -> float:
        """P(indexed by t), counting only mass the data places at or before t.

        Mass on a support interval straddling t is excluded, which makes this
        a lower bound on the CDF. `cdf_lower` is the matching upper bound;
        between them lies everything the data cannot resolve.
        """
        return sum(m for (q, p), m in zip(self.support, self.mass, strict=True) if p <= t)

    def cdf_lower(self, t: float) -> float:
        return sum(m for (q, p), m in zip(self.support, self.mass, strict=True) if q < t)

    def quantile_bracket(self, q: float) -> tuple[float | None, float | None]:
        """The support interval containing the q-th quantile.

        Returns (lower, upper] as a bracket, or (last_support_upper, None) if
        the estimator never accumulates q of its mass -- which is the correct
        answer for an arm that indexed less than half the corpus, and is not
        the same statement as "slow".
        """
        cum = 0.0
        for (lo, hi), m in zip(self.support, self.mass, strict=True):
            cum += m
            if cum >= q - 1e-12:
                return lo, (None if hi == INF else hi)
        last = self.support[-1][1] if self.support else None
        return (None if last == INF else last), None

    @property
    def total_mass(self) -> float:
        return sum(self.mass)


def _support_intervals(obs: list[Interval]) -> list[tuple[float, float]]:
    """Turnbull's equivalence classes.

    A region (q, p] can carry mass only if q is some observation's lower
    bound, p is some observation's upper bound, and no other endpoint falls
    strictly between them. Everywhere else, the likelihood is flat in the
    mass placement, so the NPMLE is not identified and pretending otherwise
    is how a plot ends up asserting more than the data supports.

    The ordering trick: at an identical numeric value, an upper bound (which
    closes an interval) sorts before a lower bound (which opens one), because
    observations are half-open (lo, hi]. Getting this backwards silently
    drops the first support interval, which is the one covering "already
    indexed by the first rung".
    """
    pts: set[tuple[float, int]] = set()
    for iv in obs:
        pts.add((iv.lo, 1))          # 1 = opens
        pts.add((iv.hi, 0))          # 0 = closes
    ordered = sorted(pts)
    out: list[tuple[float, float]] = []
    for (v1, k1), (v2, k2) in zip(ordered, ordered[1:], strict=False):
        if k1 == 1 and k2 == 0 and v1 < v2:
            out.append((v1, v2))
    return out


def fit(obs: list[Interval], tol: float = 1e-10, max_iter: int = 10_000) -> NPMLE:
    """Self-consistency (EM) for the interval-censored NPMLE.

    Each observation spreads its unit of probability over the support
    intervals it contains, in proportion to the current mass estimate; the
    new estimate is the average of those spreads. Fixed points of that map
    are exactly the stationary points of the likelihood.
    """
    est = NPMLE(n=len(obs))
    if not obs:
        return est

    support = _support_intervals(obs)
    if not support:
        return est
    m = len(support)

    # Membership matrix, precomputed: rows that match no support interval are
    # dropped, which happens only for degenerate observations like (t, t].
    rows: list[list[int]] = []
    for iv in obs:
        idx = [j for j, (q, p) in enumerate(support) if iv.contains(q, p)]
        if idx:
            rows.append(idx)
    if not rows:
        return est
    n = len(rows)

    p = [1.0 / m] * m
    for it in range(1, max_iter + 1):
        new = [0.0] * m
        for idx in rows:
            denom = 0.0
            for j in idx:
                denom += p[j]
            if denom <= 0:
                # No mass anywhere this observation allows. Spread uniformly
                # over its own support rather than dividing by zero; this is
                # only reachable from a pathological start.
                share = 1.0 / len(idx)
                for j in idx:
                    new[j] += share
                continue
            for j in idx:
                new[j] += p[j] / denom
        new = [v / n for v in new]
        delta = max(abs(a - b) for a, b in zip(new, p, strict=True))
        p = new
        if delta < tol:
            est.iterations = it
            break
    else:
        est.iterations = max_iter
        est.converged = False

    # Trim support intervals the estimator emptied. They carry no information
    # and their presence makes a bracket look narrower than it is.
    keep = [(s, mass) for s, mass in zip(support, p, strict=True) if mass > 1e-12]
    est.support = [s for s, _ in keep]
    est.mass = [mass for _, mass in keep]

    est.loglik = 0.0
    for idx in rows:
        tot = sum(p[j] for j in idx)
        est.loglik += math.log(tot) if tot > 0 else -math.inf
    return est


def bootstrap_quantile(
    obs: list[Interval],
    q: float = 0.5,
    resamples: int = 400,
    seed: int = 20260826,
) -> tuple[float | None, float | None, float]:
    """Nonparametric bootstrap CI for a quantile bracket's upper edge.

    A median printed without an interval is the most common way a small run
    gets over-read. With forty events, a bracket of (15m, 1h] can land a rung
    either side on luck alone, and the leaderboard's ordering is exactly what
    that luck moves.

    Resamples the observations with replacement, refits, and reports the
    2.5th and 97.5th percentiles of the bracket's upper edge, plus the share
    of resamples in which the quantile was never reached at all. That last
    number is the honest one for a slow arm: if 30% of resamples never get
    there, the point estimate is not the story.

    Deterministic by default -- a confidence interval that moves when you
    re-render the page is not a confidence interval.
    """
    import random

    if not obs:
        return None, None, 1.0
    rng = random.Random(seed)
    n = len(obs)
    uppers: list[float] = []
    unreached = 0
    for _ in range(resamples):
        sample = [obs[rng.randrange(n)] for _ in range(n)]
        _, hi = fit(sample).quantile_bracket(q)
        if hi is None:
            unreached += 1
        else:
            uppers.append(hi)
    if not uppers:
        return None, None, 1.0
    uppers.sort()
    lo_i = max(0, int(0.025 * len(uppers)) - 1)
    hi_i = min(len(uppers) - 1, int(math.ceil(0.975 * len(uppers))) - 1)
    return uppers[lo_i], uppers[hi_i], unreached / resamples


def intervals_from_ladder(
    probed: list[tuple[float, bool]],
) -> Interval | None:
    """Build one observation from an arm's graded probes for one event.

    `probed` is (lag, was_fresh) for every probe that produced a verdict.
    Probes that errored or were skipped are simply absent, and their absence
    widens the interval -- which is the entire reason for using an
    interval-censored estimator rather than dropping those events.
    """
    if not probed:
        return None
    probed = sorted(probed)
    first_fresh = next((lag for lag, fresh in probed if fresh), None)
    if first_fresh is None:
        return Interval(max(lag for lag, _ in probed), INF)
    lo = max((lag for lag, fresh in probed if not fresh and lag < first_fresh),
             default=0.0)
    return Interval(lo, first_fresh)
