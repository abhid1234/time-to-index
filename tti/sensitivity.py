"""How much does the conclusion depend on the author's judgement calls?

Every grading rule in this repo is a choice someone made: match on token
boundaries or not, count a `v` prefix, trust aliases, read titles only, treat
a URL as evidence. Each is defensible. None is forced. A benchmark published
by one person is exactly the kind that should be able to say how much its
ranking survives those choices being made differently.

So: re-grade every stored payload under deliberately worse rules, rebuild the
leaderboard, and report what moved. No API calls -- this runs entirely on
`runs/raw/`, which is the reason those payloads are kept verbatim in the
first place.

Two numbers come out of it.

    Verdict churn -- how many individual probe verdicts change. High churn
    with a stable ranking is the good case: the rules matter locally and wash
    out in aggregate.

    Rank correlation -- Kendall's tau between each variant's ordering and the
    reported one. This is the number that decides whether the leaderboard is
    a finding or an artefact of the grader.

Tau on its own is not sufficient, and the harness caught that about itself:
a variant that reads no content at all collapses every arm identically, so
the ordering never changes and tau comes back 1.00 for a table that has
stopped meaning anything. Arms lost and medians moved are reported next to
it for exactly that reason.

A variant that reorders the top of the table is not a bug to be suppressed.
It is the most important thing on the page, and it belongs next to the
ranking rather than in a footnote.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .grader import DEFAULT, VARIANTS, Rules, grade
from .ledger import Ledger
from .metrics import ProviderScore, score
from .models import ERROR, SKIPPED, ProbeResult


@dataclass
class VariantResult:
    name: str
    order: list[str] = field(default_factory=list)
    scores: list[ProviderScore] = field(default_factory=list)
    verdict_changes: int = 0
    verdicts_total: int = 0
    tau: float = 1.0
    rank_moves: dict[str, int] = field(default_factory=dict)
    # Rank correlation alone is not enough. A variant that erases all the
    # evidence collapses every arm equally, leaves the order untouched, and
    # scores a perfect tau while making the table meaningless. These two
    # catch that: how many arms' median brackets moved, and how many stopped
    # being measurable at all.
    median_changes: int = 0
    arms_lost: int = 0
    n_arms: int = 0
    regraded: bool = True
    note: str = ""

    @property
    def churn(self) -> float:
        return self.verdict_changes / self.verdicts_total if self.verdicts_total else 0.0


def kendall_tau(a: list[str], b: list[str]) -> float:
    """Rank correlation between two orderings of the same arms.

    Written out rather than imported: the whole point of this module is that
    a reader can check the arithmetic that decides whether to believe the
    ranking.
    """
    common = [x for x in a if x in b]
    if len(common) < 2:
        return 1.0
    pos_b = {name: i for i, name in enumerate(b)}
    concordant = discordant = 0
    for i in range(len(common)):
        for j in range(i + 1, len(common)):
            ai, aj = i, j
            bi, bj = pos_b[common[i]], pos_b[common[j]]
            if (aj - ai) * (bj - bi) > 0:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total else 1.0


def _regrade(led: Ledger, events, results: list[ProbeResult],
             rules: Rules) -> tuple[list[ProbeResult], int, int]:
    """Re-score stored payloads under `rules`. Returns (results, changed, total)."""
    out: list[ProbeResult] = []
    changed = total = 0
    for r in results:
        if r.verdict in (ERROR, SKIPPED) or not r.raw_ref:
            out.append(r)
            continue
        payload = led.load_raw(r.raw_ref)
        ev = events.get(r.event_id)
        if payload is None or ev is None:
            out.append(r)
            continue
        v, fh, sh, chars = grade(ev, payload, rules)
        total += 1
        if v != r.verdict:
            changed += 1
        out.append(ProbeResult(
            probe_id=r.probe_id, event_id=r.event_id, provider=r.provider,
            mode=r.mode, rung=r.rung, requested_at=r.requested_at, lag=r.lag,
            verdict=v, latency_ms=r.latency_ms, matched_fresh=fh, matched_stale=sh,
            n_results=r.n_results, chars=chars, cost_usd=r.cost_usd,
            raw_ref=r.raw_ref, note=r.note))
    return out, changed, total


def _order(scores: list[ProviderScore]) -> list[str]:
    """Leaderboard ordering: fastest median first, un-reached medians last."""
    ranked = sorted(scores, key=lambda s: (
        s.median_bracket[1] is None, s.median_bracket[1] or 0.0,
        s.median_bracket[0] or 0.0))
    return [f"{s.provider}/{s.mode}" for s in ranked]


def run(led: Ledger, variants: list[Rules] | None = None) -> list[VariantResult]:
    variants = variants or VARIANTS
    events = led.events()
    results = led.results()
    arms = sorted({(r.provider, r.mode) for r in results if r.provider != "origin"})
    if not arms:
        return []

    have_raw = any(r.raw_ref for r in results)

    out: list[VariantResult] = []
    baseline_order: list[str] = []
    for rules in variants:
        if rules is DEFAULT or rules.name == DEFAULT.name:
            regraded, changed, total = results, 0, 0
        elif not have_raw:
            # Nothing to re-grade against. Say so instead of reporting a
            # perfect tau that only means "we did not check".
            out.append(VariantResult(name=rules.name, regraded=False,
                                     note="no stored payloads to re-grade"))
            continue
        else:
            regraded, changed, total = _regrade(led, events, results, rules)

        scores = [score(events, regraded, p, m) for p, m in arms]
        order = _order(scores)
        if not baseline_order:
            baseline_order = order
            baseline_medians = {f"{s.provider}/{s.mode}": s.median_bracket
                                for s in scores}
        moves = {name: baseline_order.index(name) - i
                 for i, name in enumerate(order) if name in baseline_order}

        med_changed = lost = 0
        for sc in scores:
            key = f"{sc.provider}/{sc.mode}"
            base = baseline_medians.get(key)
            if base is not None and sc.median_bracket != base:
                med_changed += 1
            if sc.median_bracket[1] is None and (base or (None, None))[1] is not None:
                lost += 1

        out.append(VariantResult(
            name=rules.name, order=order, scores=scores,
            verdict_changes=changed, verdicts_total=total,
            tau=kendall_tau(baseline_order, order), rank_moves=moves,
            median_changes=med_changed, arms_lost=lost, n_arms=len(scores)))
    return out


def verdict(results: list[VariantResult]) -> str:
    """One line a reader can act on."""
    others = [r for r in results if r.name != DEFAULT.name and r.regraded]
    if not others:
        return "no variants could be evaluated — run some probes first"

    # A variant that costs arms is more alarming than one that shuffles them,
    # so it is checked first: a table where half the arms became unmeasurable
    # is not "stable", it is empty.
    destructive = [r for r in others if r.n_arms and r.arms_lost >= r.n_arms / 2]
    lead = ""
    if destructive:
        # Every destructive variant is named, not only the worst: the demo
        # had two, and naming one hid the other behind "looks stable".
        destructive.sort(key=lambda r: -r.arms_lost)
        named = ", ".join(f"'{r.name}' ({r.arms_lost} of {r.n_arms})" for r in destructive)
        verb = "makes" if len(destructive) == 1 else "make"
        lead = (f"{named} {verb} arms unmeasurable rather than reordering them — "
                f"the ranking looks stable under {'it' if len(destructive) == 1 else 'them'} "
                f"only because there is nothing left to rank")
        others = [r for r in others if r not in destructive]
        if not others:
            return lead
        lead += ". Among the variants that keep the arms: "

    worst = min(others, key=lambda r: r.tau)
    shifted = max(others, key=lambda r: r.median_changes)
    if worst.tau >= 0.99:
        if shifted.median_changes:
            return lead + (f"the ranking is identical under every variant tested, though "
                    f"'{shifted.name}' moves {shifted.median_changes} of "
                    f"{shifted.n_arms} median brackets — the order is robust, the "
                    f"absolute latencies are less so")
        return lead + ("the ranking is identical under every rule variant tested; "
                "the grading choices did not decide it")
    if worst.tau >= 0.6:
        return lead + (f"the ranking survives every variant except '{worst.name}' "
                f"(tau {worst.tau:.2f}) — read the top of the table as robust "
                f"and the middle as provisional")
    return lead + (f"'{worst.name}' reorders the leaderboard (tau {worst.tau:.2f}). "
            f"The ranking is partly an artefact of the grading rules and should "
            f"be published with that stated, not without it")
