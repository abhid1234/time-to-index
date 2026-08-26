"""Estimators.

Time-to-index is a survival problem, not an average. Most events are still
un-indexed by the last rung, so the observation is "longer than 72 hours",
not a number. Dropping those events and taking the median of the rest is the
obvious thing to do and it is wrong in a specific direction: it discards
exactly the slow cases and reports a provider as faster than it is. The
faster the provider, the smaller the bias -- so the error does not cancel
across a leaderboard, it reorders it.

So: Kaplan-Meier with right-censoring at the last rung actually fired, and
Greenwood's formula for the interval. Rates get Wilson intervals rather than
normal-approximation ones, because at n=40 events per source class the normal
approximation puts the lower bound of a 100% recall below 90% and the upper
bound of a 0% staleness above 0, both of which are nonsense.

No numpy, no scipy. Two hundred lines of arithmetic anyone can audit.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .models import ABSENT, ERROR, FRESH, SKIPPED, STALE, Event, ProbeResult
from .survival import INF, Interval, NPMLE
from .survival import fit as turnbull_fit
from .survival import intervals_from_ladder

Z95 = 1.959963984540054


# ---------------------------------------------------------------------------
# Interval estimators
# ---------------------------------------------------------------------------

def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float, float]:
    """Wilson score interval. Returns (point, low, high)."""
    if n == 0:
        return (float("nan"),) * 3
    p = successes / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


# ---------------------------------------------------------------------------
# Survival
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    """One event/provider pair: time to first FRESH, or censoring time."""
    time: float          # seconds from publication
    indexed: bool        # False => right-censored at `time`
    event_id: str = ""
    source_class: str = ""


@dataclass
class SurvivalCurve:
    """S(t) = P(not yet indexed at t)."""
    times: list[float] = field(default_factory=list)
    survival: list[float] = field(default_factory=list)
    lower: list[float] = field(default_factory=list)
    upper: list[float] = field(default_factory=list)
    n: int = 0
    n_events: int = 0

    def quantile(self, q: float) -> float | None:
        """Smallest t with S(t) <= 1-q. None if the curve never gets there,
        which is the honest answer for a provider that indexed under half of
        the corpus inside the observation window."""
        target = 1.0 - q
        for t, s in zip(self.times, self.survival):
            if s <= target + 1e-12:
                return t
        return None

    def at(self, t: float) -> float:
        """P(indexed by t)."""
        s = 1.0
        for ti, si in zip(self.times, self.survival):
            if ti <= t:
                s = si
            else:
                break
        return 1.0 - s


def kaplan_meier(obs: list[Observation]) -> SurvivalCurve:
    """Product-limit estimator with Greenwood variance on a log-log scale.

    The log-log transform keeps the confidence band inside [0, 1]; the plain
    Greenwood band routinely exits the unit interval at the tails, where a
    time-to-index curve spends most of its length.
    """
    curve = SurvivalCurve(n=len(obs))
    if not obs:
        return curve

    by_time: dict[float, list[Observation]] = defaultdict(list)
    for o in obs:
        by_time[o.time].append(o)

    at_risk = len(obs)
    s = 1.0
    cum_var = 0.0  # sum d/(n(n-d)) -- Greenwood

    for t in sorted(by_time):
        group = by_time[t]
        d = sum(1 for g in group if g.indexed)
        n = at_risk
        if d and n:
            s *= 1.0 - d / n
            cum_var += d / (n * (n - d)) if n > d else 0.0
            curve.times.append(t)
            curve.survival.append(s)
            curve.n_events += d

            if 0.0 < s < 1.0 and cum_var > 0:
                ll = math.log(-math.log(s))
                se = math.sqrt(cum_var) / abs(math.log(s))
                lo = math.exp(-math.exp(ll + Z95 * se))
                hi = math.exp(-math.exp(ll - Z95 * se))
            else:
                lo = hi = s
            curve.lower.append(min(lo, hi))
            curve.upper.append(max(lo, hi))
        at_risk -= len(group)

    return curve


def logrank(a: list[Observation], b: list[Observation]) -> tuple[float, float]:
    """Two-sample log-rank test. Returns (chi-square with 1 df, p-value).

    This is what makes a leaderboard claim defensible: 'A indexed faster than
    B' needs a test that handles censoring, and a t-test on the indexed
    subset does not.
    """
    if not a or not b:
        return float("nan"), float("nan")
    times = sorted({o.time for o in a + b if o.indexed})
    o_minus_e = 0.0
    var = 0.0
    for t in times:
        n1 = sum(1 for o in a if o.time >= t)
        n2 = sum(1 for o in b if o.time >= t)
        n = n1 + n2
        d1 = sum(1 for o in a if o.indexed and o.time == t)
        d2 = sum(1 for o in b if o.indexed and o.time == t)
        d = d1 + d2
        if n < 2 or d == 0:
            continue
        e1 = d * n1 / n
        o_minus_e += d1 - e1
        var += (d * (n1 / n) * (1 - n1 / n) * (n - d)) / (n - 1)
    if var <= 0:
        return 0.0, 1.0
    chi2 = o_minus_e * o_minus_e / var
    return chi2, _chi2_sf_1df(chi2)


def _chi2_sf_1df(x: float) -> float:
    """Upper tail of chi-square with 1 df = erfc(sqrt(x/2))."""
    if x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2.0))


# ---------------------------------------------------------------------------
# Assembling observations from the ledger
# ---------------------------------------------------------------------------

@dataclass
class ProviderScore:
    provider: str
    mode: str
    n_events: int = 0
    n_indexed: int = 0
    curve: SurvivalCurve = field(default_factory=SurvivalCurve)
    # Turnbull is the reported estimator; Kaplan-Meier is kept alongside it
    # for the log-rank test and for the KM-vs-NPMLE delta the report prints,
    # which is a standing check that the ladder is fine enough to matter.
    npmle: NPMLE = field(default_factory=NPMLE)
    median_bracket: tuple[float | None, float | None] = (None, None)
    p90_bracket: tuple[float | None, float | None] = (None, None)
    median_ttl: float | None = None
    p90_ttl: float | None = None
    recall_24h: tuple[float, float, float] = (float("nan"),) * 3
    recall_72h: tuple[float, float, float] = (float("nan"),) * 3
    # Recall restricted to events the origin control verified were actually
    # fetchable from their own URL by the same horizon. This is the number
    # that is about the provider; plain recall charges it for documents that
    # were not on the web yet.
    conditional_recall_24h: tuple[float, float, float] = (float("nan"),) * 3
    n_origin_confirmed: int = 0
    staleness: tuple[float, float, float] = (float("nan"),) * 3
    n_stale_eligible: int = 0
    n_stale: int = 0
    spend_usd: float = 0.0
    # Dollars per fresh answer inside 24h. Cost per *event* rewards a provider
    # that answers nothing cheaply; cost per answer is the number a buyer is
    # actually choosing on.
    cost_per_fresh_24h: float = float("nan")
    n_calls: int = 0
    n_errors: int = 0
    n_skipped_budget: int = 0
    p50_latency_ms: float = 0.0


def observations(
    events: dict[str, Event],
    results: list[ProbeResult],
    provider: str,
    mode: str,
    source_class: str | None = None,
) -> list[Observation]:
    """One observation per event: first FRESH lag, else censored at the
    largest lag we actually probed."""
    first_fresh: dict[str, float] = {}
    last_probed: dict[str, float] = {}
    for r in results:
        if r.provider != provider or r.mode != mode:
            continue
        if r.verdict in (ERROR, SKIPPED):
            continue
        ev = events.get(r.event_id)
        if ev is None:
            continue
        if source_class and ev.source_class != source_class:
            continue
        last_probed[r.event_id] = max(last_probed.get(r.event_id, 0.0), r.lag)
        if r.verdict == FRESH:
            prev = first_fresh.get(r.event_id)
            if prev is None or r.lag < prev:
                first_fresh[r.event_id] = r.lag

    out = []
    for eid, censor_t in last_probed.items():
        ev = events[eid]
        if eid in first_fresh:
            out.append(Observation(first_fresh[eid], True, eid, ev.source_class))
        else:
            out.append(Observation(censor_t, False, eid, ev.source_class))
    return out


def intervals(
    events: dict[str, Event],
    results: list[ProbeResult],
    provider: str,
    mode: str,
    source_class: str | None = None,
) -> list[Interval]:
    """One interval-censored observation per event.

    Errored and skipped probes are simply not collected, so their absence
    widens the interval instead of dropping the event or inventing a rung.
    """
    by_event: dict[str, list[tuple[float, bool]]] = {}
    for r in results:
        if r.provider != provider or r.mode != mode:
            continue
        if r.verdict in (ERROR, SKIPPED):
            continue
        ev = events.get(r.event_id)
        if ev is None or (source_class and ev.source_class != source_class):
            continue
        by_event.setdefault(r.event_id, []).append((r.lag, r.verdict == FRESH))
    out = []
    for probed in by_event.values():
        iv = intervals_from_ladder(probed)
        if iv is not None:
            out.append(iv)
    return out


ORIGIN = "origin"


def origin_confirmed_by(
    events: dict[str, Event],
    results: list[ProbeResult],
    horizon: float,
    source_class: str | None = None,
) -> set[str]:
    """Events the control arm fetched, with the answer present, by `horizon`.

    Deliberately strict. An event whose origin was blocked, disallowed, or
    errored is not in this set: we failed to establish fetchability, and
    guessing either way would put a made-up number in the denominator of the
    metric that is supposed to be the clean one.
    """
    out: set[str] = set()
    for r in results:
        if r.provider != ORIGIN or r.verdict != FRESH or r.lag > horizon:
            continue
        ev = events.get(r.event_id)
        if ev is None or (source_class and ev.source_class != source_class):
            continue
        out.add(r.event_id)
    return out


def score(
    events: dict[str, Event],
    results: list[ProbeResult],
    provider: str,
    mode: str,
    source_class: str | None = None,
) -> ProviderScore:
    sc = ProviderScore(provider=provider, mode=mode)
    obs = observations(events, results, provider, mode, source_class)
    sc.n_events = len(obs)
    sc.n_indexed = sum(1 for o in obs if o.indexed)
    sc.curve = kaplan_meier(obs)
    sc.median_ttl = sc.curve.quantile(0.5)
    sc.p90_ttl = sc.curve.quantile(0.9)

    ivs = intervals(events, results, provider, mode, source_class)
    sc.npmle = turnbull_fit(ivs)
    sc.median_bracket = sc.npmle.quantile_bracket(0.5)
    sc.p90_bracket = sc.npmle.quantile_bracket(0.9)

    for horizon, attr in ((86_400, "recall_24h"), (259_200, "recall_72h")):
        hit = sum(1 for o in obs if o.indexed and o.time <= horizon)
        # Only events observed to the horizon count in the denominator; an
        # event censored at 6h says nothing about 24-hour recall.
        denom = sum(1 for o in obs if o.indexed and o.time <= horizon or o.time >= horizon)
        setattr(sc, attr, wilson(hit, denom))

    # Conditional recall: same question as recall_24h, but asked only of
    # events the control arm proved were on the web by 24 hours.
    confirmed = origin_confirmed_by(events, results, 86_400, source_class)
    sc.n_origin_confirmed = len(confirmed)
    if confirmed and provider != ORIGIN:
        first_fresh: dict[str, float] = {}
        observed: set[str] = set()
        for r in results:
            if r.provider != provider or r.mode != mode:
                continue
            if r.event_id not in confirmed or r.verdict in (ERROR, SKIPPED):
                continue
            observed.add(r.event_id)
            if r.verdict == FRESH:
                prev = first_fresh.get(r.event_id)
                if prev is None or r.lag < prev:
                    first_fresh[r.event_id] = r.lag
        denom = len(observed)
        hit = sum(1 for t in first_fresh.values() if t <= 86_400)
        sc.conditional_recall_24h = wilson(hit, denom)

    # Staleness: of all probes where the provider had not yet indexed the new
    # answer and the question had a superseded answer, how often did it return
    # the superseded one? This is the per-probe rate, not per-event, because
    # each opportunity to mislead an agent is a separate opportunity.
    stale = eligible = 0
    lat: list[int] = []
    for r in results:
        if r.provider != provider or r.mode != mode:
            continue
        ev = events.get(r.event_id)
        if ev is None or (source_class and ev.source_class != source_class):
            continue
        if r.verdict == ERROR:
            sc.n_errors += 1
            continue
        if r.verdict == SKIPPED:
            if "budget" in r.note:
                sc.n_skipped_budget += 1
            continue
        sc.n_calls += 1
        sc.spend_usd += r.cost_usd
        if r.latency_ms:
            lat.append(r.latency_ms)
        if ev.measures_staleness and r.verdict in (STALE, ABSENT):
            eligible += 1
            if r.verdict == STALE:
                stale += 1
    fresh_24h = sum(1 for o in obs if o.indexed and o.time <= 86_400)
    sc.cost_per_fresh_24h = (sc.spend_usd / fresh_24h) if fresh_24h else float("inf")

    sc.n_stale, sc.n_stale_eligible = stale, eligible
    sc.staleness = wilson(stale, eligible)
    if lat:
        lat.sort()
        sc.p50_latency_ms = lat[len(lat) // 2]
    return sc


def bracket(rungs: list[int], t: float | None) -> tuple[float | None, float | None]:
    """The interval a ladder observation actually pins down.

    A provider probed at 5m, 15m, 1h and first seen FRESH at the 1h rung
    indexed somewhere in (15m, 1h]. It did not index at 1h. Reporting the
    rung as the answer overstates the latency by up to the width of the
    bracket, and the brackets are wide by design -- a ladder fine enough to
    remove the ambiguity would cost an order of magnitude more per event.

    So the ladder is a stated limitation with a stated size, rather than a
    hidden one. Returns (lower_exclusive, upper_inclusive); a lower bound of
    0 means the provider had already indexed by the first rung, which is its
    own finding.
    """
    if t is None:
        return (float(rungs[-1]) if rungs else None, None)
    lower = 0.0
    for r in rungs:
        if float(r) >= t:
            return lower, float(r)
        lower = float(r)
    return lower, None


def fmt_bracket(rungs: list[int], t: float | None) -> str:
    lo, hi = bracket(rungs, t)
    if hi is None:
        return f">{fmt_duration(lo)}" if lo else ">72h"
    if not lo:
        return f"≤{fmt_duration(hi)}"
    return f"{fmt_duration(lo)}–{fmt_duration(hi)}"


def staleness_by_rung(
    events: dict[str, Event],
    results: list[ProbeResult],
    provider: str,
    mode: str,
    source_class: str | None = None,
) -> list[tuple[int, float, int]]:
    """(rung, staleness rate, n) for each rung.

    Staleness should fall as an index catches up. A curve that does not fall
    is the interesting case: it means the provider is holding a superseded
    answer with confidence rather than slowly acquiring the new one, and the
    shape says that in a way a single pooled percentage cannot.
    """
    buckets: dict[int, list[int]] = {}
    for r in results:
        if r.provider != provider or r.mode != mode:
            continue
        if r.verdict not in (STALE, ABSENT):
            continue
        ev = events.get(r.event_id)
        if ev is None or not ev.measures_staleness:
            continue
        if source_class and ev.source_class != source_class:
            continue
        buckets.setdefault(r.rung, []).append(1 if r.verdict == STALE else 0)
    return [(rung, sum(v) / len(v), len(v))
            for rung, v in sorted(buckets.items()) if v]


def fmt_pair(b: tuple[float | None, float | None]) -> str:
    """Render a Turnbull quantile bracket.

    (0, 300]        -> "≤5m"     already indexed by the first probe
    (900, 3600]     -> "15m–1h"
    (259200, None)  -> ">72h"    never accumulated this much mass
    """
    lo, hi = b
    if hi is None:
        return f">{fmt_duration(lo)}" if lo else "—"
    if not lo:
        return f"≤{fmt_duration(hi)}"
    return f"{fmt_duration(lo)}–{fmt_duration(hi)}"


def fmt_duration(sec: float | None) -> str:
    if sec is None:
        return ">72h"
    if sec < 90:
        return f"{sec:.0f}s"
    if sec < 3600:
        return f"{sec/60:.0f}m"
    if sec < 172_800:
        return f"{sec/3600:.1f}h"
    return f"{sec/86400:.1f}d"
