"""How long do you have to run this before you can say anything?

A leaderboard invites a claim -- "A indexes faster than B" -- and after two
days of collection that claim is usually unsupportable. The failure mode is
not a wrong number, it is a true number with a confidence interval nobody
printed, repeated until it sounds settled.

So the harness computes, for every pair of arms:

    the observed hazard ratio, from the log-rank O/E statistic
    the power the run currently has to detect it
    the number of events that would be needed for 80% power
    how many more days of collection that is, at the observed event rate

Schoenfeld's formula for the log-rank test gives the required number of
*events* (not subjects) as

    d = 4 (z_{alpha/2} + z_beta)^2 / (ln HR)^2

which for two-sided alpha = 0.05 and power = 0.8 is 31.4 / (ln HR)^2. A
hazard ratio of 2 needs 66 events; a ratio of 1.2 needs 945. That gap is the
entire argument for saying "not distinguishable yet" out loud instead of
ranking three arms that are within noise of each other.

For staleness, which is a proportion rather than a time, the same question is
answered with the standard two-proportion normal approximation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .metrics import Z95, Observation

# z for 80% power, one-sided beta
Z80 = 0.8416212335729143
SCHOENFELD_80 = 4 * (Z95 + Z80) ** 2      # 31.395...


@dataclass
class PairPower:
    a: str
    b: str
    hazard_ratio: float           # >1 means `a` indexes faster
    events_observed: int
    p_value: float                # raw, uncorrected
    p_adjusted: float = float("nan")   # Holm-Bonferroni across the family
    power_now: float = float("nan")
    events_for_80: float | None = None
    events_needed: float | None = None   # additional events required
    days_needed: float | None = None
    verdict: str = ""


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def hazard_ratio(a: list[Observation], b: list[Observation]) -> tuple[float, int]:
    """O/E hazard ratio from the log-rank counts, plus the event total.

    Uses the same risk-set walk as the test itself, so the ratio and the
    p-value can never disagree about which arm is ahead -- a mismatch that is
    easy to introduce by estimating the ratio some other way and one that
    would be very hard to spot in a rendered table.
    """
    times = sorted({o.time for o in a + b if o.indexed})
    o1 = e1 = o2 = e2 = 0.0
    for t in times:
        n1 = sum(1 for o in a if o.time >= t)
        n2 = sum(1 for o in b if o.time >= t)
        n = n1 + n2
        d1 = sum(1 for o in a if o.indexed and o.time == t)
        d2 = sum(1 for o in b if o.indexed and o.time == t)
        d = d1 + d2
        if n == 0 or d == 0:
            continue
        o1 += d1
        o2 += d2
        e1 += d * n1 / n
        e2 += d * n2 / n
    if e1 <= 0 or e2 <= 0 or o2 <= 0 or o1 <= 0:
        return float("nan"), int(o1 + o2)
    return (o1 / e1) / (o2 / e2), int(o1 + o2)


def events_for_power(hr: float, power: float = 0.8) -> float | None:
    """Schoenfeld: events needed to detect this hazard ratio."""
    if hr != hr or hr <= 0 or abs(math.log(hr)) < 1e-9:
        return None
    z_beta = _z_for_power(power)
    return 4 * (Z95 + z_beta) ** 2 / (math.log(hr) ** 2)


def achieved_power(hr: float, events: int) -> float:
    """Power of the log-rank test at this hazard ratio and event count."""
    if hr != hr or hr <= 0 or events <= 0:
        return float("nan")
    lam = abs(math.log(hr)) * math.sqrt(events / 4.0)
    return _norm_cdf(lam - Z95)


def _z_for_power(power: float) -> float:
    if abs(power - 0.8) < 1e-9:
        return Z80
    # Acklam's rational approximation to the normal quantile, plenty for a
    # planning number.
    return _ppf(power)


def _ppf(p: float) -> float:
    if not 0.0 < p < 1.0:
        return float("nan")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def proportions_n(p1: float, p2: float, power: float = 0.8) -> float | None:
    """Per-group sample size to distinguish two rates (staleness, recall)."""
    if any(x != x for x in (p1, p2)) or abs(p1 - p2) < 1e-9:
        return None
    pbar = (p1 + p2) / 2
    z_beta = _z_for_power(power)
    num = (Z95 * math.sqrt(2 * pbar * (1 - pbar))
           + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return num / ((p1 - p2) ** 2)


def analyse(a_name: str, a: list[Observation],
            b_name: str, b: list[Observation],
            p_value: float, events_per_day: float = 0.0,
            p_adjusted: float = float("nan")) -> PairPower:
    hr, n_events = hazard_ratio(a, b)
    need = events_for_power(hr)
    power_now = achieved_power(hr, n_events)
    extra = max(0.0, need - n_events) if need else None
    days = (extra / events_per_day) if (extra and events_per_day > 0) else None

    # The verdict uses the *adjusted* p-value when one has been supplied. A
    # leaderboard with six arms invites fifteen comparisons, and judging each
    # against a raw 0.05 gives a 54% chance that at least one pair is called
    # different when neither is. `analyse` is also called for a single pair,
    # where there is no family and the raw value is the right one.
    p_used = p_adjusted if (p_adjusted == p_adjusted) else p_value
    if p_used == p_used and p_used < 0.05:
        verdict = "distinguishable"
    elif need is None:
        verdict = "no difference to detect"
    elif power_now == power_now and power_now < 0.8:
        verdict = f"underpowered ({power_now*100:.0f}%)"
    else:
        verdict = "well powered, no difference found"

    return PairPower(a=a_name, b=b_name, hazard_ratio=hr, events_observed=n_events,
                     p_value=p_value, p_adjusted=p_adjusted, power_now=power_now,
                     events_for_80=need, events_needed=extra, days_needed=days,
                     verdict=verdict)


def pairwise_family(events, results, arms, rate: float) -> list[PairPower]:
    """Every pairwise comparison among `arms`, Holm-adjusted as one family.

    The only place this loop exists. There were three copies -- `tti power`,
    `tti report`, and the demo -- and the demo's had no adjustment step, so
    its page printed a Holm column of dashes over verdicts the note beneath
    said were adjusted. A correction that lives in one function cannot be
    applied to some of the callers.
    """
    from .metrics import logrank, observations
    from .multiplicity import holm

    raw = []
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            a, b = arms[i], arms[j]
            oa = observations(events, results, *a)
            ob = observations(events, results, *b)
            _, pv = logrank(oa, ob)
            raw.append((f"{a[0]}/{a[1]}", oa, f"{b[0]}/{b[1]}", ob, pv))
    adj = holm([(f"{na} vs {nb}", pv) for na, _, nb, _, pv in raw])
    return [analyse(na, oa, nb, ob, pv, rate, p_adjusted=ad.adjusted)
            for (na, oa, nb, ob, pv), ad in zip(raw, adj, strict=True)]


def raw_pairs(powers: list[PairPower]) -> list[tuple[str, str, float]]:
    """(a, b, uncorrected p) for the comparisons that could be computed."""
    return [(r.a, r.b, r.p_value) for r in powers if r.p_value == r.p_value]
