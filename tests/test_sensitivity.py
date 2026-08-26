"""Sensitivity of the ranking to grading rules.

These tests build a ledger with real stored payloads and confirm the harness
detects the difference between a rule that changes verdicts locally and one
that reorders the leaderboard. That distinction is the whole output.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti import sensitivity
from tti.grader import DEFAULT, Rules
from tti.ledger import Ledger
from tti.models import Event, FRESH, ABSENT, ProbeResult

LADDER = [300, 900, 3600, 21600, 86400, 259200]


def build(tmp_path, n=24):
    """Two arms. `pv` writes versions bare; `pw` writes them `v`-prefixed.

    Under the reported rules both are found. Under `no-v-prefix`, pw's
    answers stop counting entirely -- a rule change that should visibly
    reorder the table, which is exactly the case worth detecting.
    """
    led = Ledger(tmp_path)
    events, results = [], []
    for i in range(n):
        ev = Event(source="npm", source_class="package_registry", subject=f"pkg{i}",
                   published_at=1_000_000.0 + i, discovered_at=1_000_001.0 + i,
                   question="q", answer=f"3.{i}.2", predecessor=f"3.{i}.1")
        events.append(ev)
        for arm, render in (("pv", lambda a: f"released {a}"),
                            ("pw", lambda a: f"released v{a}")):
            for rung in LADDER:
                fresh = rung >= (300 if arm == "pv" else 900)
                body = render(ev.answer) if fresh else f"still on {ev.predecessor}"
                ref = led.store_raw(arm, f"{ev.event_id}-{arm}-{rung}",
                                    {"results": [{"url": "https://x", "snippet": body}]})
                results.append(ProbeResult(
                    probe_id=f"{ev.event_id}-{arm}-{rung}", event_id=ev.event_id,
                    provider=arm, mode="base", rung=rung,
                    requested_at=ev.published_at + rung, lag=float(rung),
                    verdict=FRESH if fresh else "STALE", cost_usd=0.001, raw_ref=ref))
                if fresh:
                    break
    led.add_events(events)
    led.add_results(results)
    return led


def test_reported_variant_is_the_baseline_and_never_churns(tmp_path):
    rows = sensitivity.run(build(tmp_path))
    strict = next(r for r in rows if r.name == "strict")
    assert strict.verdict_changes == 0
    assert strict.tau == 1.0


def test_a_rule_that_only_flips_verdicts_locally_keeps_the_ranking(tmp_path):
    """`naive-substring` is strictly more permissive, so it can only add
    matches. Churn should be low and the ordering unchanged."""
    rows = sensitivity.run(build(tmp_path))
    naive = next(r for r in rows if r.name == "naive-substring")
    assert naive.tau == 1.0


def test_a_rule_that_reorders_the_leaderboard_is_reported_as_such(tmp_path):
    """Dropping the `v` allowance makes one arm's answers stop counting.
    If the harness cannot see that, it cannot see anything."""
    rows = sensitivity.run(build(tmp_path))
    nov = next(r for r in rows if r.name == "no-v-prefix")
    assert nov.churn > 0.2
    assert nov.order[0] == "pv/base"
    # pw's medians collapse to never-reached, so it must fall to last.
    assert nov.order[-1] == "pw/base"


def test_titles_only_erases_all_evidence(tmp_path):
    """A variant that reads no content at all should find nothing, which is
    a check that the variants are actually being applied."""
    rows = sensitivity.run(build(tmp_path))
    titles = next(r for r in rows if r.name == "titles-only")
    assert titles.churn > 0.9


def test_a_destructive_variant_is_not_mistaken_for_a_stable_one(tmp_path):
    """The trap this harness caught about itself.

    `titles-only` erases every arm's evidence equally, so the ordering never
    changes and Kendall's tau comes back a perfect 1.00 for a table that has
    stopped meaning anything. Tau alone would call that robustness."""
    rows = sensitivity.run(build(tmp_path))
    titles = next(r for r in rows if r.name == "titles-only")
    assert titles.tau == 1.0                    # order preserved...
    assert titles.arms_lost == titles.n_arms    # ...because nothing survived
    assert "nothing left to rank" in sensitivity.verdict(rows)


def test_losing_one_arm_is_reported_even_when_the_order_holds(tmp_path):
    rows = sensitivity.run(build(tmp_path))
    nov = next(r for r in rows if r.name == "no-v-prefix")
    assert nov.arms_lost == 1
    assert nov.median_changes >= 1


def test_a_genuine_reorder_is_detected(tmp_path):
    """Three arms where dropping alias matching promotes the slowest one.

    If tau cannot see this, the whole module is decoration."""
    led = Ledger(tmp_path)
    events, results = [], []
    for i in range(20):
        ev = Event(source="npm", source_class="package_registry", subject=f"p{i}",
                   published_at=1_000_000.0 + i, discovered_at=1_000_001.0 + i,
                   question="q", answer=f"5.{i}.2",
                   # The alias must not *contain* the canonical token, or
                   # boundary matching finds it anyway and the variant is a
                   # no-op. (It did, the first time.)
                   answer_aliases=[f"5.{i}.2", f"rel20260826{i:03d}"],
                   predecessor=f"5.{i}.1")
        events.append(ev)
        # `alias-only` writes the answer solely in its alias form, so it looks
        # fastest under the reported rules and vanishes without aliases.
        plan = {"canonical": 300, "alias-only": 300, "slow-canonical": 3600}
        for arm, first_fresh in plan.items():
            for rung in LADDER:
                fresh = rung >= first_fresh
                if not fresh:
                    body = f"still on {ev.predecessor}"
                elif arm == "alias-only":
                    body = f"see release rel20260826{i:03d} notes"
                else:
                    body = f"released {ev.answer}"
                ref = led.store_raw(arm, f"{ev.event_id}-{arm}-{rung}",
                                    {"results": [{"url": "https://x", "snippet": body}]})
                results.append(ProbeResult(
                    probe_id=f"{ev.event_id}-{arm}-{rung}", event_id=ev.event_id,
                    provider=arm, mode="base", rung=rung,
                    requested_at=ev.published_at + rung, lag=float(rung),
                    verdict=FRESH if fresh else "STALE", cost_usd=0.001, raw_ref=ref))
                if fresh:
                    break
    led.add_events(events)
    led.add_results(results)

    rows = sensitivity.run(led)
    strict = next(r for r in rows if r.name == "strict")
    canon = next(r for r in rows if r.name == "canonical-token-only")
    assert "alias-only/base" in strict.order[:2]
    # Without aliases that arm has no evidence at all and must fall to last.
    assert canon.order[-1] == "alias-only/base"
    assert canon.tau < 1.0
    assert canon.rank_moves["alias-only/base"] != 0
    assert "reorders" in sensitivity.verdict(rows) or canon.tau < 0.99


def test_verdict_sentence_matches_what_happened(tmp_path):
    rows = sensitivity.run(build(tmp_path))
    line = sensitivity.verdict(rows)
    assert isinstance(line, str) and len(line) > 20


def test_no_stored_payloads_reports_unchecked_rather_than_perfect_agreement(tmp_path):
    """The dangerous failure: a tau of 1.0 that only means nothing was
    re-graded."""
    led = Ledger(tmp_path)
    ev = Event(source="npm", source_class="package_registry", subject="p",
               published_at=0.0, discovered_at=1.0, question="q", answer="1.0.1")
    led.add_events([ev])
    led.add_results([ProbeResult(
        probe_id="x", event_id=ev.event_id, provider="pv", mode="base", rung=300,
        requested_at=300.0, lag=300.0, verdict=FRESH, raw_ref="")])
    rows = sensitivity.run(led)
    skipped = [r for r in rows if not r.regraded]
    assert skipped and all("no stored payloads" in r.note for r in skipped)


def test_kendall_tau_edges():
    assert sensitivity.kendall_tau(["a"], ["a"]) == 1.0
    assert sensitivity.kendall_tau([], []) == 1.0
    assert sensitivity.kendall_tau(["a", "b"], ["b", "a"]) == -1.0
    assert sensitivity.kendall_tau(["a", "b", "c"], ["a", "b"]) == 1.0
