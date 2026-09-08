"""Command line.

    tti doctor              check every source and provider is reachable
    tti verify              offline: config, estimator, grader, ledger, platform
    tti prereg              the analysis plan, its hash, and whether it has drifted
    tti discover            poll sources, enqueue probes
    tti probe [--limit N]   run probes whose due time has arrived
    tti score               print the leaderboard
    tti report              write RESULTS.md and docs/index.html
    tti regrade             re-grade stored raw payloads without new calls
    tti decoy               how often does this pipeline say FRESH about a
                            version that was never published?
    tti status              what is queued, what is due, what is spent

`discover` and `probe` are the two that run on a timer. Everything else is
read-only over the ledger, so it is safe to run at any time, including while
a probe run is in flight.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import math
import pathlib
import sys
import time
import urllib.parse

from . import __version__, config, providers, report, sources
from .budget import Budget, unit_cost, utc_day
from .grader import grade
from .ledger import Ledger
from .metrics import ORIGIN as metrics_origin
from .metrics import (
    ProviderScore,
    fmt_duration,
    fmt_p,
    recall_by_render,
    score,
    staleness_by_rung,
)
from .models import ERROR, SKIPPED
from .multiplicity import family_error_rate
from .multiplicity import note as multiplicity_note
from .scheduler import _count_results, discover, error_body, run_due


def _ledger(args) -> Ledger:
    return Ledger(pathlib.Path(args.run_dir) if args.run_dir else None)


ROOT = pathlib.Path(__file__).resolve().parent.parent

# The control arm's name, taken from metrics rather than repeated, so an
# exclusion cannot drift out of step with the thing it excludes.
ORIGIN_ARM = metrics_origin

# Fewer usable routes than this and `tti routes` declines to say anything
# site-wide. Three is the smallest number at which "uniform" and "mixed" are
# distinguishable claims rather than descriptions of one or two pages.
ROUTES_MIN_USABLE = 3


def _n(v):
    """JSON has no NaN or Infinity that a strict parser will accept.

    `json.dumps` emits the bare tokens NaN and Infinity by default, which
    Python reads back happily and almost nothing else does. Anything that is
    not a finite number becomes null, so a consumer sees a missing value
    rather than a parse error or, worse, a token it silently coerces.
    """
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v if math.isfinite(v) else None
    return v


def _interval(t) -> dict:
    lo, hi = t
    return {"low_seconds": _n(lo), "high_seconds": _n(hi)}


def _rate(t) -> dict:
    p, lo, hi = t
    return {"point": _n(p), "low": _n(lo), "high": _n(hi)}


def _score_json(sc) -> dict:
    return {
        "provider": sc.provider, "mode": sc.mode,
        "events": sc.n_events, "indexed": sc.n_indexed,
        "median_time_to_index": _interval(sc.median_bracket),
        "median_ci": _interval(sc.median_ci),
        "median_unreached_share": _n(sc.median_unreached),
        "p90_time_to_index": _interval(sc.p90_bracket),
        "recall_24h": _rate(sc.recall_24h),
        "recall_24h_vs_origin": _rate(sc.conditional_recall_24h),
        "recall_72h": _rate(sc.recall_72h),
        "staleness": _rate(sc.staleness),
        "staleness_opportunities": sc.n_stale_eligible,
        "phrasing_agreement": _rate(sc.phrasing_agreement),
        "phrasings_asked": sc.n_phrasings_asked,
        "origin_confirmed_events": sc.n_origin_confirmed,
        "spend_usd": _n(sc.spend_usd),
        "cost_per_fresh_answer_usd": _n(sc.cost_per_fresh_24h),
        "p50_latency_ms": _n(sc.p50_latency_ms),
        "chars_per_result_p50": _n(sc.chars_per_result_p50),
        "calls": sc.n_calls, "errors": sc.n_errors,
        "skipped_budget": sc.n_skipped_budget,
        "estimator_converged": sc.npmle.converged,
        "observations_dropped": sc.npmle.dropped,
    }


def _emit(payload) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0


def _out_dir(args) -> pathlib.Path:
    """Where rendered pages go.

    Defaults to the repo's docs/ so `tti report` publishes where GitHub Pages
    looks. Overridable because a command that can only write into its own
    source tree is a command the test suite has to either skip or let dirty
    the working copy, and both are worse than a flag.
    """
    d = pathlib.Path(getattr(args, "out_dir", None) or (ROOT / "docs"))
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------

def _plan_status(led, scores):
    """The plan, the lock, and how this run's arms line up with both.

    Returns None if there is no readable plan — a repo can be forked without
    one, and refusing to score in that case would punish the fork rather than
    the omission. Everything downstream treats None as "unregistered" and says
    so, which is the honest label.
    """
    from . import prereg
    from .demo import DEMO_MARKER

    if (led.root / DEMO_MARKER).exists():
        return "synthetic"
    try:
        plan = prereg.parse()
    except prereg.PreregError:
        return None
    present = sorted({(sc.provider, sc.mode) for sc in scores if sc.n_events})
    try:
        enabled = providers.available_arms()
    except Exception:  # noqa: BLE001  -- a broken adapter must not hide the plan
        enabled = None
    cls = prereg.classify(plan, present, control=ORIGIN_ARM, enabled=enabled)
    st = prereg.status(led.root, plan, started=bool(led.results()))
    return plan, cls, st


def _plan_lines(ps) -> list[str]:
    """Human-readable plan notes, or the note that there is no plan."""
    if ps == "synthetic":
        return ["  Synthetic run. The pre-registered plan does not apply: "
                "these arms are a",
                "  generator whose latencies are already known, not a "
                "measurement of anything."]
    if ps is None:
        return ["  ! No analysis plan (docs/PREREGISTRATION.md unreadable).",
                "    Every number below is exploratory by default."]
    plan, cls, st = ps
    out = [f"  plan {plan.hash} · v{plan.version} · registered {plan.registered}"]
    if st.drifted:
        out.append(f"  ! PLAN CHANGED SINCE COLLECTION BEGAN "
                   f"(locked {st.locked}, now {st.current})")
        out.append("    Reported every time. A plan edited after the data "
                   "exists is a")
        out.append("    different kind of claim from one written before it.")
    elif st.locked is None and st.started:
        out.append("  ! This run has results but no plan lock. It began before "
                   "locking existed,")
        out.append("    or the lock file was removed; either way the plan "
                   "cannot be shown to")
        out.append("    predate the data.")
    if cls.exploratory:
        out.append(f"  ! EXPLORATORY, not pre-registered: "
                   f"{', '.join(cls.exploratory)}")
    if cls.declared_but_silent:
        out.append(f"  ! Declared in the plan, enabled, produced nothing: "
                   f"{', '.join(cls.declared_but_silent)}")
        out.append("    Listed because an arm that fails everywhere is "
                   "otherwise just an absent row.")
    if cls.declared_not_enabled:
        out.append(f"  · Declared in the plan, not enabled in this run (no key): "
                   f"{', '.join(cls.declared_not_enabled)}")
    return out


def cmd_prereg(args) -> int:
    """Print the analysis plan, its hash, and whether a run has locked it."""
    from . import prereg

    try:
        plan = prereg.parse()
    except prereg.PreregError as exc:
        print(f"✗ {exc}")
        return 2

    led = _ledger(args)
    from .demo import DEMO_MARKER
    synthetic = (led.root / DEMO_MARKER).exists()
    st = prereg.status(led.root, plan, started=bool(led.results()))
    if args.json:
        return _emit({
            "synthetic": synthetic,
            "hash": plan.hash, "version": plan.version,
            "registered": plan.registered,
            "primary_endpoint": plan.primary_endpoint,
            "secondary_endpoints": plan.secondary_endpoints,
            "arms": plan.arms, "ladder_seconds": plan.ladder,
            "hypotheses": [{"id": h.id, "statement": h.statement,
                            "test": h.test, "threshold": h.threshold,
                            "falsified_if": h.falsified_if}
                           for h in plan.hypotheses],
            "exclusions": plan.exclusions,
            "stopping_rule": plan.stopping_rule,
            "lock": {"locked_hash": st.locked, "current_hash": st.current,
                     "collection_started": st.started, "drifted": st.drifted},
        })

    print(f"plan {plan.hash}  ·  version {plan.version}  ·  "
          f"registered {plan.registered}\n")
    print("primary endpoint")
    for line in _wrap(plan.primary_endpoint, 74):
        print(f"  {line}")
    if plan.secondary_endpoints:
        print("\nsecondary endpoints")
        for sec in plan.secondary_endpoints:
            for i, line in enumerate(_wrap(sec, 72)):
                print(f"  {'- ' if i == 0 else '  '}{line}")
    print(f"\narms declared in advance   {', '.join(plan.arms)}")
    print(f"ladder (seconds)           {plan.ladder}")
    print("\nhypotheses")
    for h in plan.hypotheses:
        for i, line in enumerate(_wrap(h.statement, 68)):
            print(f"  {h.id + '  ' if i == 0 else '    '}{line}")
        if h.threshold:
            print(f"      threshold     {h.threshold}")
        for i, line in enumerate(_wrap(h.falsified_if, 60)):
            print(f"      {'falsified if  ' if i == 0 else '              '}{line}")
        print()
    print(f"exclusions declared in advance  "
          f"{', '.join(str(e.get('id', '?')) for e in plan.exclusions)}")
    print("\nstopping rule")
    for line in _wrap(plan.stopping_rule, 74):
        print(f"  {line}")

    print("\nlock")
    if synthetic:
        # `tti demo` ledgers carry results and never a lock: the plan is a
        # claim about a measurement of somebody's product, and a generator
        # is not one. The warning below is for real runs.
        print("  synthetic run — the plan does not apply, and no lock is expected")
    elif not st.started:
        print("  no results yet — the plan locks on the first dispatched probe")
    elif st.locked is None:
        print("  ! results exist but no lock file; the plan cannot be shown "
              "to predate them")
    elif st.drifted:
        print(f"  ! CHANGED SINCE COLLECTION BEGAN: locked {st.locked}, "
              f"now {st.current}")
        for line in _wrap(prereg.DRIFT_NOTE, 74):
            print(f"    {line}")
        return 1
    else:
        print(f"  ✓ locked {st.locked} — unchanged since collection began")
    return 0


def _wrap(text: str, width: int) -> list[str]:
    import textwrap
    return textwrap.wrap(" ".join(str(text).split()), width) or [""]


def cmd_verify(args) -> int:
    """Offline: does this installation compute what it claims to compute?

    Separate from `doctor` on purpose. Doctor asks whether the network is
    reachable, which is somebody else's uptime. This asks whether the numbers
    would be right, which is ours, and it can be answered on a plane.
    """
    from . import verify as _verify

    checks = _verify.run_all(pathlib.Path(args.run_dir) if args.run_dir else None)
    status = _verify.worst(checks)
    if args.json:
        _emit({"status": status,
               "checks": [{"name": c.name, "status": c.status,
                           "detail": c.detail, "notes": c.notes}
                          for c in checks]})
        return {"ok": 0, "warn": 1, "fail": 2}[status]

    mark = {"ok": "✓", "warn": "!", "fail": "✗"}
    for c in checks:
        print(f"  {mark[c.status]} {c.name:10s} {c.detail}")
        for n in c.notes:
            print(f"      {n}")
    print()
    if status == "fail":
        print("FAIL — do not publish numbers from this installation until the")
        print("above is fixed. Each of these checks exists because the failure")
        print("it catches produced a plausible answer rather than a crash.")
        return 2
    if status == "warn":
        print("OK with warnings. Nothing here makes a number wrong on its own;")
        print("each one describes a way this installation could become wrong")
        print("without saying so.")
        return 1
    print("All checks passed. This says the arithmetic and the stored data are")
    print("sound; it says nothing about whether any provider is reachable —")
    print("that is `tti doctor`.")
    return 0


def cmd_doctor(args) -> int:
    # Config first: every check below reads it, and a run that starts from a
    # file nobody validated can be wrong in ways no probe would reveal.
    problems = config.check_all()
    if problems:
        print("configuration")
        for pr in problems:
            print(f"  ✗ {pr}")
        print("\nFix these before anything else. Nothing below is meaningful while")
        print("the configuration is not.")
        return 2
    print("configuration  ✓ all files valid")

    ua = config.contact_ua()
    if "set TTI_USER_AGENT" in ua:
        # SEC's fair-access policy and arXiv's terms both require a real
        # contact. Without one their collectors will be refused, and the
        # refusal looks like an unreachable host.
        print("  ! TTI_USER_AGENT is unset. SEC and arXiv require a real contact\n"
              "    string and will refuse requests without one.\n")
    print("sources")
    bad = 0
    from . import http as _http
    _http.set_retry_ceiling(0)      # fail fast; this is a reachability check
    for name in config.settings().get("sources", []):
        src = sources.get(name)
        src.max_subjects = args.subjects or None
        t0 = time.perf_counter()
        try:
            got = src.collect({})
            ms = (time.perf_counter() - t0) * 1000
            if src.all_failed:
                print(f"  ✗ {name:18s} unreachable ({len(src.errors)}/{src.attempted}) "
                      f"— {src.errors[0][:70]}")
                bad += 1
            else:
                # Subjects that answered, over subjects asked. Not events over
                # subjects: one arXiv category returns many papers, and the
                # first real run of this command printed "10/2 subjects
                # reachable" -- ten of two. npm and PyPI only looked right
                # because a fresh poll yields at most one event per subject.
                # The event count is still useful, so it is shown, separately.
                answered = src.attempted - len(src.errors)
                ev_word = "event " if len(got) == 1 else "events"
                print(f"  ✓ {name:18s} {answered:3d}/{src.attempted} subjects "
                      f"reachable · {len(got):3d} {ev_word}  {ms:6.0f}ms")
                if src.errors:
                    print(f"      failed: {sources.subject_names(src.errors)}")
                    print(f"      first:  {src.errors[0][:100]}")
                for w in getattr(src, "warnings", [])[:8]:
                    print(f"      ~ {w[:110]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {name:18s} {type(exc).__name__}: {exc}"[:110])
            bad += 1

    print("\nproviders")
    cfg = config.providers_config()["providers"]
    for arm in config.settings().get("arms", []):
        p, m = arm["provider"], arm["mode"]
        env = cfg.get(p, {}).get("env", "?")
        arm = f"{p}/{m}"
        try:
            prov = providers.get(p)
        except KeyError:
            print(f"  ✗ {arm:18s} no adapter")
            bad += 1
            continue
        if not prov.available():
            print(f"  · {arm:18s} skipped — {env} not set")
            continue
        try:
            t0 = time.perf_counter()
            payload = prov.search("what is the latest version of the npm package next",
                                  m, max_results=3, max_chars=500)
            ms = (time.perf_counter() - t0) * 1000
            err = error_body(payload)
            n_res = _count_results(payload)
            if err:
                # 200 with an error body. The runner would record an ERROR
                # row; doctor should not print a tick over it.
                print(f"  ✗ {arm:18s} error body with HTTP 200: {err[:60]}")
                bad += 1
            elif n_res == 0:
                # A query every general index answers came back empty. Not
                # a failure the harness can prove, but the first real run
                # should not start on it without somebody looking.
                print(f"  ! {arm:18s}  0 results  {ms:6.0f}ms  "
                      f"${unit_cost(p, m, 3):.4f}/call — check the key's plan and "
                      f"the raw response before running")
            else:
                print(f"  ✓ {arm:18s} {n_res:2d} results  {ms:6.0f}ms  "
                      f"${unit_cost(p, m, 3):.4f}/call")
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {arm:18s} {type(exc).__name__}: {str(exc)[:70]}")
            bad += 1

    led = _ledger(args)
    day = utc_day(time.time())
    b = Budget(spent_today=led.spent_on(day))
    print(f"\nbudget  ${b.spent:.4f} of ${b.cap:.2f} spent on {day} "
          f"(${b.remaining():.2f} left)")
    _http.set_retry_ceiling(None)
    if bad:
        print(f"\n{bad} check(s) failed. A run with unreachable sources is a partial")
        print("run; its per-class numbers should not be read as complete.")
    return 1 if bad else 0


def cmd_discover(args) -> int:
    from . import lock

    led = _ledger(args)
    if args.dry_run:
        # No lock. A dry run writes nothing, so it cannot collide with a real
        # one -- and taking the lock would mean a dry run could block the
        # scheduled job it exists to explain.
        rep = discover(led, source_names=args.sources or None, dry_run=True)
    else:
        try:
            with lock.exclusive(led.root, "discover"):
                rep = discover(led, source_names=args.sources or None)
        except lock.Busy as exc:
            print(f"skipped: {exc}")
            return 0
    if rep.dry_run:
        print("DRY RUN — sources were polled, nothing was written.\n")
    print(f"collected {rep.collected} · new {rep.new_events} · "
          f"dropped-late {rep.dropped_late} · probes queued {rep.probes_queued}")
    if rep.dropped_future:
        print(f"  ! {rep.dropped_future} event(s) had a publication timestamp ahead "
              f"of our clock by more than the skew tolerance and were dropped.")
        print("    Their ladder would have been anchored to a time that has not "
              "happened.")
    for k, v in sorted(rep.per_source.items()):
        print(f"  {k:18s} {v}")
    if rep.dry_run and rep.preview:
        print("\n  would enqueue a ladder for:")
        for src, subj, ans, lag in rep.preview[:25]:
            print(f"    {src:10s} {subj[:38]:38s} -> {ans[:22]:22s} "
                  f"seen {fmt_duration(lag)} after publication")
        if len(rep.preview) > 25:
            print(f"    ... and {len(rep.preview) - 25} more")
        print("\n  The detection-lag filter was applied against the clock as of")
        print("  now. An event listed here can still be dropped by a later real")
        print("  run if it has aged past the tolerance by then.")
    if rep.broken_sources:
        print(f"\n  UNREACHABLE: {', '.join(rep.broken_sources)}")
        print("  These contributed no events. A run with unreachable sources is a")
        print("  partial run; do not read its per-class numbers as complete.")
        return 2
    return 0


def cmd_probe(args) -> int:
    from . import lock

    led = _ledger(args)
    if args.dry_run:
        rep = run_due(led, limit=args.limit, dry_run=True)
    else:
        try:
            with lock.exclusive(led.root, "probe"):
                if not lock.SUPPORTED:
                    print("  ! file locking unavailable on this platform; "
                          "overlapping runs are not prevented")
                rep = run_due(led, limit=args.limit, dry_run=False)
        except lock.Busy as exc:
            # Exit 0. A second run that cannot take the lock is early, not
            # broken, and a cron wrapper should not page anyone for it.
            print(f"skipped: {exc}")
            print("  Two overlapping runs dispatch every due probe twice — double "
                  "spend,\n  duplicate rows, and every rate computed afterwards "
                  "counting one\n  observation twice.")
            return 0
    print(f"dispatched {rep.dispatched} · FRESH {rep.fresh} · STALE {rep.stale} · "
          f"ABSENT {rep.absent} · errors {rep.errors}")
    print(f"skipped: carry-forward {rep.skipped_carry} · budget {rep.skipped_budget} · "
          f"rung-slip {rep.dropped_slip}")
    print(f"spend ${rep.spend_usd:.4f} this run (cap ${rep.cap_usd:.2f}/day)")
    if rep.refunded_usd:
        print(f"  ${rep.refunded_usd:.4f} reserved and released for {rep.errors} failed "
              f"call(s) — assumes failures are not billed")
    if rep.days_crossed:
        print(f"  crossed {rep.days_crossed} UTC day boundary; the cap reset mid-run")
    if rep.skipped_budget:
        print("  ! the daily cap refused probes; today's coverage is incomplete")
    return 0


def _all_scores(led: Ledger, source_class: str | None = None) -> list[ProviderScore]:
    """Scores for every paid arm.

    The origin control is excluded. It is the yardstick, not a competitor:
    it fetches the canonical URL directly, so it has near-perfect recall at
    zero cost by construction, and listing it beside the providers invites
    exactly the comparison it exists to make unnecessary. This exclusion was
    written once and silently lost to a later edit, and nothing caught it —
    the demo filters its own arms, so only a real run would have shown the
    control sitting at the top of the leaderboard.
    """
    events, results = led.events(), led.results()
    arms = sorted({(r.provider, r.mode) for r in results if r.provider != ORIGIN_ARM})
    # Bootstrap only the top-level table; the per-source-class panels have
    # too few events per cell for a resample to mean much, and computing it
    # anyway would print an interval that looks authoritative and is not.
    boot = 0 if source_class else 400
    return [score(events, results, p, m, source_class, bootstrap=boot)
            for p, m in arms]


def _control_summary(led) -> dict | None:
    """What the origin control found, when it is the only arm with results.

    A run with no provider key -- the state anyone is in before the first key
    arrives -- produces a ledger full of control results and an empty
    leaderboard, because the leaderboard compares provider arms by design.
    "No results yet" is false for that ledger. This is what is true of it.
    Returns None when there are no graded control rows.
    """
    rows = [r for r in led.results()
            if r.provider == ORIGIN_ARM and r.verdict not in (ERROR, SKIPPED)]
    if not rows:
        return None
    states: dict[str, int] = {}
    renders: dict[str, int] = {}
    rank0 = 0
    for r in rows:
        st = (r.note or "origin:unknown").split()[0].replace("origin:", "")
        states[st] = states.get(st, 0) + 1
        if r.render:
            renders[r.render] = renders.get(r.render, 0) + 1
        if "rank=0" in (r.note or ""):
            rank0 += 1
    events = {r.event_id for r in rows}
    return {"events": len(events), "graded": len(rows), "states": states,
            "render": renders, "rank0": rank0,
            "fresh": sum(1 for r in rows if r.verdict == "FRESH")}


def _print_control_only(cs: dict) -> None:
    print(f"Only the origin control has results: {cs['graded']} graded probe(s) "
          f"across {cs['events']} event(s), no provider arm.")
    print("The leaderboard compares provider arms, and there are none -- every")
    print("provider key is unset or every provider probe is still pending.")
    print()
    print("| origin state | probes |")
    print("|---|---|")
    for k, v in sorted(cs["states"].items(), key=lambda kv: -kv[1]):
        print(f"| {k} | {v} |")
    if cs["render"]:
        print()
        print("| render class | probes |")
        print("|---|---|")
        for k, v in sorted(cs["render"].items(), key=lambda kv: -kv[1]):
            print(f"| {k} | {v} |")
    print()
    print(f"{cs['fresh']}/{cs['graded']} found the answer in the served bytes; "
          f"{cs['rank0']}/{cs['graded']} on the canonical page rather than a fallback.")
    print("This is the yardstick, not a result about any provider.")


def cmd_score(args) -> int:
    led = _ledger(args)
    scores = _all_scores(led)
    if not scores:
        cs = _control_summary(led)
        if cs:
            if args.json:
                return _emit({"arms": [], "control": cs,
                              "note": "only the origin control has results; the "
                                      "leaderboard compares provider arms and "
                                      "there are none"})
            _print_control_only(cs)
            return 0
        if args.json:
            return _emit({"arms": [], "note": "no results yet"})
        print("no results yet — run `tti discover` then `tti probe`")
        return 1
    ps = _plan_status(led, scores)
    if args.json:
        payload = {"arms": [_score_json(sc) for sc in scores],
                   "events": len(led.events())}
        if ps == "synthetic":
            payload["preregistration"] = {"synthetic": True}
        elif ps is None:
            payload["preregistration"] = {"registered": False}
        else:
            plan, cls, st = ps
            payload["preregistration"] = {
                "registered": True, "hash": plan.hash, "version": plan.version,
                "locked_hash": st.locked, "drifted": st.drifted,
                "declared": cls.declared, "exploratory": cls.exploratory,
                "declared_but_silent": cls.declared_but_silent,
                "declared_not_enabled": cls.declared_not_enabled,
            }
            # Per-arm, so a consumer reading one row does not have to
            # cross-reference a list at the top of the document to learn that
            # the row was not pre-registered.
            for row in payload["arms"]:
                arm = f"{row['provider']}/{row['mode']}"
                row["preregistered"] = arm in plan.arms
        return _emit(payload)
    print(report.leaderboard_md(scores))
    lines = _plan_lines(ps)
    if lines:
        print()
        for line in lines:
            print(line)
    return 0


def _cost_reconciliation(led, max_results: int) -> dict:
    """How far vendor-reported charges have diverged from the price table.

    Computed from the ledger, not from the in-memory Budget, because the
    Budget is rebuilt every run and forgets. Rows marked `cost_source:
    reported` are re-priced at today's list price and the difference summed.
    A table that has drifted shows up here as dollars, with a sign.
    """
    reported = list_rows = 0
    drift = 0.0
    for r in led.results():
        if r.verdict in (ERROR, SKIPPED) or r.provider == ORIGIN_ARM:
            continue
        if getattr(r, "cost_source", "list") == "reported":
            reported += 1
            # An unpriced arm is skipped here; the status command names it.
            with contextlib.suppress(config.ConfigError):
                drift += r.cost_usd - unit_cost(r.provider, r.mode, max_results)
        else:
            list_rows += 1
    return {"reported_rows": reported, "list_rows": list_rows,
            "drift_usd": round(drift, 6)}


def cmd_status(args) -> int:
    led = _ledger(args)
    if args.json:
        import time as _t
        now = _t.time()
        probes, done = led.probes(), led.completed_probe_ids()
        pending = [p for p in probes.values() if p.probe_id not in done]
        day = utc_day(now)
        b = Budget(spent_today=led.spent_on(day))
        return _emit({
            "events": len(led.events()),
            "probes": {"total": len(probes),
                       "done": sum(1 for pid in done if pid in probes),
                       "results": len(done), "pending": len(pending),
                       "due_now": sum(1 for p in pending if p.due_at <= now)},
            "next_due_at": _n(min((p.due_at for p in pending if p.due_at > now),
                                  default=float("nan"))),
            "budget": {"day": day, "cap_usd": b.cap, "spent_usd": b.spent,
                       "remaining_usd": b.remaining()},
            "cost_reconciliation": _cost_reconciliation(
                led, int(config.settings().get("max_results", 5))),
            "integrity": led.integrity(),
        })
    events, probes = led.events(), led.probes()
    done = led.completed_probe_ids()
    now = time.time()
    pending = [p for p in probes.values() if p.probe_id not in done]
    due = [p for p in pending if p.due_at <= now]
    nxt = min((p.due_at for p in pending if p.due_at > now), default=None)
    day = utc_day(now)
    b = Budget(spent_today=led.spent_on(day))
    print(f"events    {len(events)}")
    if not probes and done:
        # A ledger with results and no queue: generated by `tti demo`, or
        # copied without probes.jsonl. "0 total · 1430 done" is not a state.
        print(f"probes    no queue on disk · {len(done)} result(s) — a generated or "
              f"imported ledger, nothing to schedule")
    else:
        done_in_queue = sum(1 for pid in done if pid in probes)
        print(f"probes    {len(probes)} total · {done_in_queue} done · {len(pending)} pending · "
              f"{len(due)} due now")
    if nxt:
        print(f"next due  {dt.datetime.fromtimestamp(nxt, dt.timezone.utc):%H:%M:%S UTC} "
              f"(in {fmt_duration(nxt - now)})")
    print(f"budget    ${b.spent:.4f} / ${b.cap:.2f} today")
    rec = _cost_reconciliation(led, int(config.settings().get("max_results", 5)))
    if rec["reported_rows"]:
        sign = "+" if rec["drift_usd"] >= 0 else "-"
        print(f"cost      {rec['reported_rows']} vendor-reported row(s), "
              f"{rec['list_rows']} list-priced; reported minus list = "
              f"{sign}${abs(rec['drift_usd']):.4f}")
        if abs(rec["drift_usd"]) > 0.05 * max(b.spent, 1e-9):
            print("          data/providers.yaml has drifted from what vendors "
                  "charge; re-check the pricing pages.")
    est = 0.0
    unpriced: set[str] = set()
    for pr in due:
        try:
            est += unit_cost(pr.provider, pr.mode)
        except config.ConfigError:
            unpriced.add(f"{pr.provider}/{pr.mode}")
    if due:
        print(f"due cost  ${est:.4f} to clear the {len(due)} probes due now")
    if unpriced:
        print(f"  ! {len(unpriced)} arm(s) in the ledger are not in "
              f"providers.yaml: {', '.join(sorted(unpriced))}")
        print("    Their probes cannot be priced and will be refused by the cap.")

    bad = led.integrity()
    if bad:
        print("\nledger integrity")
        for fname, counts in sorted(bad.items()):
            parts = []
            if counts["unparseable"]:
                parts.append(f"{counts['unparseable']} unparseable "
                             f"(a torn write, usually the last line)")
            if counts["wrong_shape"]:
                parts.append(f"{counts['wrong_shape']} wrong shape "
                             f"(an older schema)")
            if counts.get("duplicates"):
                parts.append(f"{counts['duplicates']} duplicate probe id(s) "
                             f"(two runs overlapped)")
            print(f"  ! {fname}: {', '.join(parts)} of {counts['total']} records")
        print("  These are skipped, not fatal — one interrupted write must not make")
        print("  a month of collection unreadable. But they are records that no")
        print("  longer count, so every rate computed from this ledger is over a")
        print("  smaller denominator than the file length suggests.")
    return 0


def cmd_decoy(args) -> int:
    """Measure the pipeline's false-positive rate. Zero provider calls.

    Re-grades every stored payload against a counterfactual answer — a
    version-shaped token, same shape as the real one, that was never
    published. A FRESH verdict against a version that does not exist is a
    false positive by construction.
    """
    from . import decoy as decoy_mod
    from .metrics import wilson

    led = _ledger(args)
    if not led.results():
        # A monitoring wrapper polls from the first minute, so the JSON form
        # owes it a document rather than a bare exit code. Same contract every
        # other --json command here keeps.
        if args.json:
            return _emit({"arms": [], "events_decoyed": 0, "events_skipped": 0,
                          "skip_reasons": {}, "unverified_counterfactuals": 0,
                          "note": "no results yet — nothing to re-grade"})
        print("no results yet — nothing to re-grade")
        return 1

    synthetic = _plan_status(led, []) == "synthetic"
    # A synthetic ledger's subjects do not exist on any registry. Asking npm
    # whether "npm-subject-3@4.17.9" was ever published would be a network
    # call to confirm something known by construction.
    verify = None if (args.no_verify or synthetic) else decoy_mod.npm_absent
    if synthetic and not args.json:
        print("synthetic run: the counterfactuals are unpublished by construction, "
              "so no registry was asked")
    rep = decoy_mod.run(led, verify_absent=verify, verbose=not args.json)

    if args.json:
        return _emit({
            "events_decoyed": rep.events_decoyed,
            "events_skipped": rep.events_skipped,
            "skip_reasons": rep.skip_reasons,
            "unverified_counterfactuals": rep.unverified,
            "arms": [{"provider": a.provider, "mode": a.mode,
                      "graded": a.graded, "false_positives": a.hits,
                      "rate": _n(a.rate),
                      "rate_ci": _rate(wilson(a.hits, a.graded))
                      if a.graded else _rate((float("nan"),) * 3),
                      "examples": [{"subject": s, "counterfactual": t,
                                    "matched": m} for s, t, m in a.examples]}
                     for a in rep.arms],
        })

    print(f"\ncounterfactual answers minted for {rep.events_decoyed} event(s); "
          f"{rep.events_skipped} skipped")
    for reason, n in sorted(rep.skip_reasons.items()):
        print(f"  {n:4d}  {reason}")
    if rep.unverified:
        print(f"  {rep.unverified:4d}  counterfactual not confirmed absent with "
              f"the publisher (weaker evidence, counted anyway)")
    if not rep.any_graded:
        print("\nNo payload could be re-graded. Either nothing stored a raw "
              "payload, or\nno event had a semver-shaped answer to build a "
              "counterfactual from.")
        return 1


    print("\n| arm | payloads re-graded | false positives | rate (95% CI) |")
    print("|---|---|---|---|")
    for a in rep.arms:
        p_, lo, hi = wilson(a.hits, a.graded)
        print(f"| `{a.provider}/{a.mode}` | {a.graded} | {a.hits} | "
              f"{p_*100:.1f}% ({lo*100:.0f}–{hi*100:.0f}) |")

    print("\nA false positive here is the pipeline reporting FRESH for a version")
    print("that was never published. Two causes, both invisible in a leaderboard:")
    print("the grader matching a version-shaped token in unrelated prose, or a")
    print("provider's answer layer inventing one.")
    # Per-arm, not pooled. The first version printed the worst arm's bound as
    # if it applied to every row, which overstates it for the clean arms —
    # the same "one number for everybody" mistake this project exists to
    # object to.
    hi_by_arm = sorted(((wilson(a.hits, a.graded)[2], a) for a in rep.arms),
                       key=lambda t: -t[0])
    print("\nEach arm's recall carries its own upper error bar from the column "
          "above:")
    for hi, a in hi_by_arm:
        print(f"  {a.provider}/{a.mode}: up to {hi*100:.0f}% of its FRESH "
              f"verdicts could be spurious.")
    if not any(a.hits for a in rep.arms):
        # Keyed off the observed count, not the interval. Keying off the upper
        # bound was the first version and the note could never fire: the whole
        # point of a Wilson interval is that its upper edge is not zero when
        # the observed count is.
        print("\nNo false positive was observed. That is not a 0% rate — at "
              "this sample\nsize the upper bound above is what the evidence "
              "actually supports, and it\nis the number that belongs beside "
              "the recall figures.")
    return 0


def cmd_regrade(args) -> int:
    """Re-grade every stored payload with the current rules, no API calls.

    This is the affordance that makes the published numbers checkable: if you
    think the matching rules are wrong, change grader.py, run this, and see
    how much the leaderboard actually moves.
    """
    led = _ledger(args)
    events = led.events()
    changed = 0
    rows = []
    for r in led.results():
        if r.verdict in (ERROR, SKIPPED) or not r.raw_ref:
            rows.append(r)
            continue
        payload = led.load_raw(r.raw_ref)
        ev = events.get(r.event_id)
        if payload is None or ev is None:
            rows.append(r)
            continue
        v, fh, sh, chars = grade(ev, payload)
        if v != r.verdict:
            changed += 1
            print(f"  {r.provider}/{r.mode} {ev.subject} @{r.rung}s: {r.verdict} -> {v}")
        r.verdict, r.matched_fresh, r.matched_stale, r.chars = v, fh, sh, chars
        rows.append(r)
    if not args.write:
        print(f"{changed} of {len(rows)} verdicts would change — pass --write to apply")
        return 0

    from . import lock
    try:
        # Held for the whole read-modify-write. A concurrent `tti probe`
        # appending between them would have its rows silently discarded, and
        # nothing would show it happened.
        with lock.exclusive(led.root, "probe"):
            backup = led.rewrite_results(rows)
    except lock.Busy as exc:
        print(f"refused: {exc}")
        print("  Rewriting the ledger while a probe run is appending to it would")
        print("  discard whatever that run wrote. Try again once it finishes.")
        return 1

    print(f"rewrote {len(rows)} results ({changed} verdicts changed)")
    if backup:
        print(f"  previous file kept at {backup.name}")
    return 0


def _events_per_day(led: Ledger) -> float:
    evs = list(led.events().values())
    if len(evs) < 2:
        return 0.0
    span = max(e.published_at for e in evs) - min(e.published_at for e in evs)
    return (len(evs) / (span / 86_400.0)) if span > 3600 else 0.0


def _pairwise_family(events, results, arms, rate):
    """Every pairwise comparison, Holm-adjusted as one family.

    One function because there were two copies of this loop — the JSON branch
    and the text branch of `tti power` — and a correction applied to one of
    them would have produced two different verdicts for the same data
    depending on which flag the reader passed.
    """
    from .power import pairwise_family
    return pairwise_family(events, results, arms, rate)


def cmd_power(args) -> int:
    """Can this run support the claim its leaderboard invites?

    Printed as its own command rather than buried in the report, because the
    honest answer early in a run is "no", and that is the moment it matters.
    """

    led = _ledger(args)
    events, results = led.events(), led.results()
    arms = sorted({(r.provider, r.mode) for r in results
                   if r.provider != ORIGIN_ARM})
    if len(arms) < 2:
        cs = _control_summary(led)
        if args.json:
            return _emit({"comparisons": [],
                          "note": "need at least two provider arms with results",
                          "control_results": cs["graded"] if cs else 0})
        print("need at least two provider arms with results"
              + (f" ({len(arms)} so far)" if arms else ""))
        if cs:
            print(f"({cs['graded']} control-arm result(s) exist; power compares provider "
                  f"arms against each other, and the control is not one.)")
        return 1

    rate = _events_per_day(led)
    rows = _pairwise_family(events, results, arms, rate)
    m = sum(1 for r in rows if r.p_value == r.p_value)

    if args.json:
        return _emit({
            "events": len(events), "events_per_day": _n(rate),
            "multiplicity": {"method": "holm-bonferroni", "comparisons": m,
                             "uncorrected_family_error_rate":
                                 _n(family_error_rate(m))},
            "comparisons": [{
                "a": r.a, "b": r.b,
                "hazard_ratio": _n(r.hazard_ratio),
                "events_observed": r.events_observed,
                "p_value": _n(r.p_value),
                "p_value_adjusted": _n(r.p_adjusted),
                "power": _n(r.power_now),
                "events_for_80_percent": _n(r.events_for_80),
                "further_events_needed": _n(r.events_needed),
                "further_days_needed": _n(r.days_needed),
                "verdict": r.verdict} for r in rows]})

    print(f"{len(events)} events, {rate:.1f}/day observed\n")
    if m > 1:
        for line in _wrap(multiplicity_note(m), 78):
            print(line)
        print()
    hdr = (f"{'comparison':38s} {'HR':>6s} {'events':>7s} {'p':>7s} "
           f"{'p adj':>7s} {'power':>6s} {'need':>7s} {'days':>6s}  verdict")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        hr = "—" if r.hazard_ratio != r.hazard_ratio else f"{r.hazard_ratio:.2f}"
        pw = "—" if r.power_now != r.power_now else f"{r.power_now*100:.0f}%"
        need = "—" if r.events_for_80 is None else f"{r.events_for_80:.0f}"
        # 0 days when the run already has the events; a dash when the rate
        # is unknown, because "0 more days" and "cannot say" are different.
        days = ("0" if r.events_needed is not None and r.events_needed == 0 else
                "—" if r.days_needed is None else f"{r.days_needed:.0f}")
        pv, pa = fmt_p(r.p_value), fmt_p(r.p_adjusted)
        print(f"{r.a + ' vs ' + r.b:38s} {hr:>6s} {r.events_observed:>7d} "
              f"{pv:>7s} {pa:>7s} {pw:>6s} {need:>7s} {days:>6s}  {r.verdict}")
    print("\nHR > 1 means the first arm indexes faster. `need` is the Schoenfeld")
    print("event count for 80% power at the observed hazard ratio; `days` is how")
    print("much more collection reaching it takes at the current rate (0: already there).")
    return 0


def cmd_sensitivity(args) -> int:
    """Re-grade stored payloads under deliberately worse rules.

    Zero API calls. If the ranking holds under every variant, say so; if a
    variant reorders it, that belongs next to the leaderboard rather than in
    a footnote.
    """
    from . import sensitivity

    led = _ledger(args)
    rows = sensitivity.run(led)
    if args.json:
        return _emit({
            "verdict": sensitivity.verdict(rows) if rows else "no results",
            "variants": [{
                "name": r.name, "evaluated": r.regraded, "note": r.note,
                "verdict_churn": _n(r.churn),
                "verdicts_changed": r.verdict_changes,
                "verdicts_total": r.verdicts_total,
                "rank_correlation": _n(r.tau),
                "medians_moved": r.median_changes,
                "arms_lost": r.arms_lost, "arms": r.n_arms,
                "ordering": r.order} for r in rows]})
    if not rows:
        print("no provider-arm results to re-grade — run `tti probe` with a provider key first")
        cs = _control_summary(led)
        if cs:
            print(f"({cs['graded']} control-arm result(s) exist; sensitivity re-grades "
                  f"provider arms, which the leaderboard ranks, and the control is not one.)")
        return 1

    hdr = (f"{'rule variant':26s} {'churn':>8s} {'tau':>6s} {'medians':>8s} "
           f"{'lost':>5s}  ranking")
    print(hdr)
    print("-" * max(len(hdr), 74))
    for r in rows:
        if not r.regraded and r.name != "strict":
            print(f"{r.name:26s} {'—':>8s} {'—':>6s} {'—':>8s} {'—':>5s}  {r.note}")
            continue
        churn = f"{r.churn*100:.1f}%" if r.verdicts_total else "—"
        tau = f"{r.tau:.2f}"
        moved = " ".join(
            f"{n}{'' if r.rank_moves.get(n, 0) == 0 else f'({r.rank_moves[n]:+d})'}"
            for n in r.order)
        label = r.name + ("  (reported)" if r.name == "strict" else "")
        meds = f"{r.median_changes}/{r.n_arms}" if r.n_arms else "—"
        lost = str(r.arms_lost) if r.n_arms else "—"
        print(f"{label:26s} {churn:>8s} {tau:>6s} {meds:>8s} {lost:>5s}  {moved}")

    print()
    for line in _wrap(sensitivity.verdict(rows), 78):
        print(line)
    print()
    print("churn = share of probe verdicts that change. tau = Kendall rank")
    print("correlation against the reported ordering. medians = arms whose median")
    print("bracket moved. lost = arms that stopped being measurable at all.")
    print()
    print("High churn with tau near 1 is the good case: the rule matters locally and")
    print("washes out in aggregate. A high `lost` count with tau near 1 is the trap —")
    print("the order survives because there is nothing left to order.")
    return 0


def cmd_crawlability(args) -> int:
    """Can an AI agent read this page?

    Standalone: it needs no ledger, no keys, and no run. Point it at a URL
    and it answers the two questions that decide whether a page enters an AI
    system at all -- is the content in the served HTML, and is the crawler
    allowed to fetch it.
    """
    import json as _json
    import urllib.parse

    from . import framework as fw
    from . import http as _http

    _http.set_retry_ceiling(1)
    out_rows = []
    repeat = max(1, int(getattr(args, "repeat", 1) or 1))
    for url in args.urls:
        row = {"url": url}
        # Repeat-fetch agreement, the same rule `survey` applies. A verdict
        # about somebody's site should not rest on one request: a challenge
        # page, a rate limit or an edge node having a bad minute all classify
        # perfectly and mean nothing. The richest body is kept for the
        # verdict, because a truncated response reads as a worse posture than
        # the site deserves.
        samples: list[tuple[str, object]] = []      # (html, PageProfile)
        postures: list[str] = []
        err = ""
        for i in range(repeat):
            if i:
                time.sleep(1.5)
            try:
                resp = _http.raw_get(url, timeout=25, headers={
                    "Accept": "text/html,application/xhtml+xml"})
                if resp.status_code != 200:
                    postures.append(f"HTTP{resp.status_code}")
                    err = (f"HTTP {resp.status_code} — a non-200 is not a "
                           f"verdict about the site's rendering")
                    continue
                pr = fw.profile(resp.text)
                samples.append((resp.text, pr))
                postures.append(pr.posture)
            except Exception as exc:  # noqa: BLE001
                err = str(exc)[:200]
                postures.append("error")
        if not samples:
            row["error"] = err
            out_rows.append(row)
            if not args.json:
                print(f"\n{url}\n  could not fetch: {err[:100]}")
            continue
        row["attempts"] = repeat
        row["postures_seen"] = postures
        if len(set(postures)) > 1:
            row["verdict"] = "unstable"
            out_rows.append(row)
            if not args.json:
                print(f"\n{url}")
                print(f"  UNSTABLE — {repeat} fetches disagreed: "
                      f"{' / '.join(postures)}")
                print("  No verdict. A page that classifies differently on "
                      "consecutive requests is")
                print("  telling you about the network between you and it, "
                      "not about itself.")
            continue
        html, prof = max(samples, key=lambda bp: bp[1].bytes_total)

        verdict, why = fw.VERDICTS[prof.posture]
        row.update({"framework": prof.framework, "posture": prof.posture,
                    "verdict": verdict, "bytes": prof.bytes_total,
                    "visible_chars": prof.visible_chars,
                    "text_ratio": round(prof.text_ratio, 5),
                    "evidence": prof.evidence})

        parts = urllib.parse.urlsplit(url)
        robots = ""
        with contextlib.suppress(Exception):
            robots = _http.get_text(f"{parts.scheme}://{parts.netloc}/robots.txt",
                                    timeout=15, retries=0)
        matrix = fw.robots_matrix(robots, url) if robots else {}
        row["robots"] = matrix
        blocked = [a for a, ok in matrix.items() if ok is False]

        if args.find:
            in_bytes, in_text = fw.finds_token(html, args.find)
            row["find"] = {"token": args.find, "in_bytes": in_bytes,
                           "in_visible_text": in_text}

        out_rows.append(row)
        if args.json:
            continue

        print(f"\n{url}")
        print(f"  {prof.summary()}")
        if prof.evidence:
            print(f"  detected by: {', '.join(prof.evidence[:3])}")
        print(f"  verdict: {verdict.upper()} — {why}")
        if args.find:
            f = row["find"]
            if f["in_visible_text"]:
                print(f"  '{args.find}' is in the readable HTML.")
            elif f["in_bytes"]:
                print(f"  '{args.find}' is in the served bytes but NOT in the "
                      f"readable HTML — it is inside a script or data payload. "
                      f"Whether an agent finds it depends on that agent's extractor.")
            else:
                print(f"  '{args.find}' is not in the served bytes at all. "
                      f"Nothing that does not run JavaScript can find it here.")
        llms = ""
        with contextlib.suppress(Exception):
            llms = _http.get_text(fw.llms_txt_url(url), timeout=10, retries=0)
        if llms and fw.serves_html(llms):
            # A 200 carrying the application, not a file. Reported as its own
            # state: "absent" would understate it, because a crawler following
            # the convention gets a page and no error to notice.
            row["llms_txt"] = {"shell": True, "bytes": len(llms)}
            print(f"  llms.txt: the site answers with its own page — "
                  f"{len(llms):,} bytes of HTML, not a file.")
            print("    The route did not match and the app rendered instead, so the")
            print("    fetch succeeds and yields nothing an agent can use.")
        elif llms and len(llms) > 40:
            info = fw.summarise_llms_txt(llms)
            row["llms_txt"] = info
            print(f"  llms.txt: present — {info['bytes']:,} bytes, "
                  f"{info['sections']} sections, {info['links']} links"
                  + (f", titled {info['title'][:40]!r}" if info["title"] else ""))
            print("    A deliberate statement that the site wants to be read. Reported,")
            print("    not scored — the convention is too young to grade against.")
        else:
            row["llms_txt"] = None

        if not robots:
            print("  robots.txt: not readable — no crawler policy could be checked")
        elif blocked:
            print(f"  robots.txt blocks {len(blocked)} of {len(matrix)} AI agents:")
            for a in blocked:
                print(f"      {a:22s} {fw.AI_AGENTS[a]}")
        else:
            print(f"  robots.txt allows all {len(matrix)} AI agents checked")

    if args.json:
        print(_json.dumps(out_rows, indent=2))
    _http.set_retry_ceiling(None)
    return 0


def cmd_routes(args) -> int:
    """Sample a site's own sitemap and profile the routes it declares.

    One page is enough to prove a failure exists and not enough to describe a
    site. Marketing pages are almost always server-rendered; the interesting
    failures are on detail pages.
    """
    from . import routes as rt
    from . import survey as sv_mod

    for site in args.sites:
        rs = rt.sample(site, args.sample)
        print(f"\n{rs.site}")
        if not rs.ok:
            print(f"  {rs.note or 'no routes discovered'}")
            continue
        print(f"  {rs.discovered:,} routes declared in "
              f"{len(rs.sitemap_urls)} sitemap(s); sampling {len(rs.sampled)} "
              f"evenly across the sorted list")

        sv = sv_mod.run([(u, "route") for u in rs.sampled],
                        workers=args.workers, repeat=args.repeat)
        if sv.intercepted:
            print(f"  ! {len(sv.intercepted)} of {len(rs.sampled)} sampled routes: "
                  f"{sv.intercepted_summary()}.")
            print("    One page served for many is a challenge, block or proxy —")
            print("    not a rendering posture. Those routes are excluded, and the")
            print("    exclusion says how this client was treated, not how the site")
            print("    renders for a crawler in good standing.")
        hit, n = sv.readable_rate()
        if not n:
            print("  no route could be judged — fetches failed, disagreed, or all")
            print("  returned the same intercepted body")
            continue
        if n < ROUTES_MIN_USABLE and n < len(rs.sampled):
            # The first live run: seven of eight routes intercepted, one
            # survivor, and the line below it read "Uniformly readable across
            # the sample". A site-level sentence from one page is not a
            # sample; it is an anecdote with a percentage sign.
            for r in sorted(sv.usable, key=lambda r: r.prof.text_ratio):
                path = urllib.parse.urlsplit(r.url).path or "/"
                print(f"     {r.prof.text_ratio*100:5.2f}%  {r.prof.visible_chars:>7,}c  "
                      f"{r.prof.posture:15s} {path[:52]}")
            print(f"  Only {n} of {len(rs.sampled)} sampled routes usable after "
                  f"exclusions — too few to characterise the site.")
            print("  Re-run later, from a different network, or with a larger sample.")
            continue
        for r in sorted(sv.usable, key=lambda r: r.prof.text_ratio):
            mark = " " if r.readable else "!"
            path = urllib.parse.urlsplit(r.url).path or "/"
            print(f"   {mark} {r.prof.text_ratio*100:5.2f}%  "
                  f"{r.prof.visible_chars:>7,}c  {r.prof.posture:15s} {path[:52]}")
        share = hit / n
        print(f"  {hit}/{n} sampled routes readable ({share*100:.0f}%)")
        if share == 1.0:
            print("  Uniformly readable across the sample.")
        elif share == 0.0:
            print("  No sampled route was readable. This is a site-wide posture,")
            print("  not one bad page.")
        else:
            print("  Mixed. A site-level claim either way would be wrong — the")
            print("  readable routes and the unreadable ones are different pages,")
            print("  and only the second kind is actionable.")
    return 0


def cmd_watch(args) -> int:
    """Record a survey into a ledger, or report how postures have moved.

    A single scan says a page is unreadable today. It cannot say the page used
    to be readable, which is the actionable statement: nobody decides to
    become invisible to agents, they ship a refactor and no signal turns red.
    """
    from . import survey as sv_mod
    from . import watch as w

    run_dir = pathlib.Path(args.run_dir) if args.run_dir else config.RUNS
    hist = w.history(run_dir)

    sv = None
    if not args.report:
        targets = [(u, "cli") for u in args.urls] if args.urls else None
        sv = sv_mod.run(targets, workers=args.workers, repeat=args.repeat)
        n = w.record(sv, run_dir)
        hit, judged = sv.readable_rate()
        print(f"recorded {n} observations · {hit}/{judged} readable this run")
        hist = w.history(run_dir)

    cov = w.coverage(hist)
    if args.json:
        ch_all = w.changes(hist)
        return _emit({
            "urls": cov.urls, "runs": cov.runs,
            "span_days": _n(cov.span_days),
            "judged_rate": _n(cov.judged_rate),
            "never_judged": cov.never_judged,
            "changes": [{"url": c.url, "at": c.at, "previous_at": c.prev_at,
                         "kind": c.kind, "before": c.before, "after": c.after,
                         "before_chars": c.before_chars,
                         "after_chars": c.after_chars,
                         "regression": c.worsened,
                         "description": c.describe()} for c in ch_all],
        })
    ch: list = []
    if not cov.runs:
        print("no history yet — run `tti watch` at least twice, days apart")
        return 1

    print(f"\n{cov.urls} URLs · {cov.runs} run{'s' if cov.runs != 1 else ''} · "
          f"{cov.span_days:.1f} days of history "
          f"· {cov.judged_rate*100:.0f}% of observations judged")
    if cov.runs < 2:
        print("  One run is not a series. Nothing can be said about change yet.")
        if getattr(args, "out_dir", None) and sv is not None:
            out = _out_dir(args) / "corpus.html"
            out.write_text(report.full_page(report.corpus_html(sv, hist, [], cov),
                                            "Can an Agent Read the Web"),
                           encoding="utf-8")
            print(f"  wrote {out}")
        return 0
    if cov.span_days < 1:
        print("  Under a day of history. Sites redeploy on the order of days, so")
        print("  'nothing changed' here is a statement about the window, not the web.")

    ch = w.changes(hist)
    if not ch:
        print("\nNo posture changed between judged observations.")
    else:
        worse = [c for c in ch if c.worsened]
        print(f"\n{len(ch)} change(s), {len(worse)} of them regressions:")
        for c in ch:
            mark = "!" if c.worsened else " "
            when = dt.datetime.fromtimestamp(c.at, dt.timezone.utc).strftime("%Y-%m-%d")
            print(f" {mark} {when}  {c.url[8:60]:52s} {c.describe()}")
        if worse:
            print("\n  Each regression shipped in a routine change. No build check, no")
            print("  deploy gate and no dashboard turns red when a route stops being")
            print("  readable, which is why these are only visible in hindsight.")

    if cov.never_judged:
        print(f"\n{len(cov.never_judged)} URL(s) were never judged in any run and "
              f"contribute nothing:")
        for u in cov.never_judged[:8]:
            print(f"  {u}")
        if len(cov.never_judged) > 8:
            print(f"  … and {len(cov.never_judged) - 8} more (all of them in the JSON form)")

    if getattr(args, "out_dir", None):
        if sv is None:
            print("\n--out-dir needs a survey to render; drop --report to fetch one")
        else:
            out = _out_dir(args) / "corpus.html"
            out.write_text(
                report.full_page(report.corpus_html(sv, hist, ch, cov),
                                 "Can an Agent Read the Web"), encoding="utf-8")
            print(f"\nwrote {out}")
    return 0


def cmd_survey(args) -> int:
    """Scan a corpus of pages and report how much of it an agent can read.

    Needs no keys and no ledger. The output is about the web, not about any
    provider, which is the half of this project a site owner can act on.
    """
    import json as _json

    from . import survey as sv_mod

    targets = None
    if args.urls:
        targets = [(u, "cli") for u in args.urls]
    sv = sv_mod.run(targets, workers=args.workers, repeat=args.repeat)

    if args.json:
        print(_json.dumps([{
            "url": r.url, "category": r.category, "status": r.status,
            "usable": r.usable, "readable": r.readable, "verdict": r.verdict,
            "framework": r.prof.framework if r.prof else None,
            "posture": r.prof.posture if r.prof else None,
            "visible_chars": r.prof.visible_chars if r.prof else 0,
            "bytes": r.prof.bytes_total if r.prof else 0,
            "text_ratio": round(r.prof.text_ratio, 5) if r.prof else 0,
            "robots_blocked": r.robots_blocked, "robots_checked": r.robots_checked,
            "error": r.error,
        } for r in sorted(sv.results, key=lambda r: r.url)], indent=2))
        return 0

    hit, n = sv.readable_rate()
    meta = sv.metadata_only()
    print(f"{hit} of {n} pages readable without executing JavaScript"
          + (f" · {len(meta)} metadata-only" if meta else "")
          + (f" · {len(sv.intercepted)} intercepted" if sv.intercepted else "")
          + (f" · {len(sv.unstable)} unstable" if sv.unstable else "")
          + (f" · {len(sv.unreachable) - len(sv.unstable)} unreachable"
             if len(sv.unreachable) > len(sv.unstable) else ""))

    if n:
        print()
        for r in sorted(sv.usable, key=lambda r: r.prof.text_ratio):
            mark = " " if r.readable else "!"
            blocked = f"  robots blocks {len(r.robots_blocked)}" if r.robots_blocked else ""
            print(f" {mark} {r.prof.text_ratio*100:5.2f}%  "
                  f"{r.prof.visible_chars:>7,}c  {r.prof.framework:11s} "
                  f"{r.prof.posture:15s} {r.url[8:58]}{blocked}")

        print("\nby category")
        for cat, (h, t) in sv.by_category().items():
            print(f"  {cat:20s} {h}/{t} readable")

        empty = sv.open_and_empty()
        partial = [r for r in sv.open_but_unreadable() if r not in empty]
        if empty:
            print(f"\n{len(empty)} page(s) allow every AI crawler in robots.txt and "
                  f"ship them nothing at all — no readable body, no metadata:")
            for r in empty:
                print(f"  {r.url}  ({r.prof.visible_chars} visible chars)")
            print("  Nobody chose this. It falls out of a rendering default, and the")
            print("  robots.txt records that the team wanted the opposite.")
        if partial:
            print(f"\n{len(partial)} more allow every AI crawler and ship metadata "
                  f"only — a summary, not the content:")
            for r in partial:
                print(f"  {r.url}")

    if meta:
        print(f"\n{len(meta)} page(s) ship readable metadata over an unreadable body:")
        for r in meta:
            st = r.prof.structured
            print(f"  {r.url[8:56]:50s} JSON-LD {st.jsonld_chars}c "
                  f"{st.jsonld_types or ''}")
        print("  An agent learns what the page is about. It does not learn what the")
        print("  page says, which is usually the fact it was sent there for.")

    if sv.unstable:
        print(f"\n{len(sv.unstable)} target(s) gave different answers across repeat "
              f"fetches and were excluded:")
        for r in sv.unstable[:10]:
            print(f"  {r.url[8:56]:50s} {' / '.join(r.postures_seen)}")

    if getattr(args, "out_dir", None):
        out = _out_dir(args) / "corpus.html"
        out.write_text(report.full_page(report.corpus_html(sv),
                                        "Can an Agent Read the Web"),
                       encoding="utf-8")
        print(f"\nwrote {out}")

    if sv.unreachable and args.verbose:
        print(f"\nnot judged ({len(sv.unreachable)}):")
        for r in sv.unreachable[:24]:
            print(f"  {r.url[:58]:60s} {r.why_unusable[:52]}")
    return 0


def cmd_forecast(args) -> int:
    """Days-to-signal, from how often the watchlist has actually shipped."""
    from . import forecast as fc_mod

    fc = fc_mod.run(args.sources or None)
    ok, bad = fc.readable, [r for r in fc.rows if r.error]
    if args.json:
        top, eff = fc.concentration()
        return _emit({
            "window_days": fc.window_days,
            "subjects_readable": len(ok), "subjects_unreachable": len(bad),
            "events_per_day": _n(fc.per_day),
            "superseding_events_per_day": _n(fc.superseding_per_day),
            "concentration": {"top_subject_share": _n(top),
                              "effective_subjects": _n(eff)},
            "days_to_detect": {str(hr): _n(fc.days_for(hr))
                               for hr in (2.0, 1.5, 1.2)},
            "subjects": [{"source": r.source, "subject": r.subject,
                          "releases": r.releases, "per_day": _n(r.per_day),
                          "error": r.error} for r in fc.rows],
        })
    print(f"{len(ok)} subjects readable over the last {fc.window_days} days"
          + (f" · {len(bad)} unreachable" if bad else ""))
    print(f"observed rate   {fc.per_day:6.1f} events/day")
    print(f"  of which can measure staleness "
          f"{fc.superseding_per_day:.1f}/day (npm, pypi, releases, filings)")
    top, eff = fc.concentration()
    if top == top:
        flag = "  <-- one subject dominates the corpus" if top > 0.10 else ""
        print(f"concentration   top subject {top:5.1%} · "
              f"{eff:.0f} effective subjects{flag}")

    for name, why in fc_mod.UNBOUNDED.items():
        if name in (args.sources or config.settings().get("sources", [])):
            print(f"  + {name}: {why}")

    print(f"\n{'to detect a hazard ratio of':32s} {'events':>7s} {'days':>7s}")
    for hr in (2.0, 1.5, 1.2):
        d = fc.days_for(hr)
        need = fc_mod.events_for_power(hr)
        print(f"{'  ' + str(hr):32s} {need:7.0f} {('—' if d is None else f'{d:.0f}'):>7s}")

    quiet = fc.quiet()
    if quiet:
        print(f"\n{len(quiet)} subjects shipped nothing in {fc.window_days} days and are "
              f"pure cost:")
        print("  " + ", ".join(f"{r.subject}" for r in quiet[:16]))
        print("  Each still costs one poll per cycle. Drop them or accept the noise.")

    busiest = sorted(ok, key=lambda r: -r.releases)[:8]
    if busiest and busiest[0].releases:
        print("\nbusiest subjects:")
        for r in busiest:
            print(f"  {r.source:14s} {r.subject:22s} {r.releases:3d}  "
                  f"({r.per_day*7:.1f}/wk)")

    if bad:
        print(f"\n{len(bad)} unreachable — this forecast is a lower bound:")
        for r in bad[:5]:
            print(f"  {r.source:14s} {r.subject:22s} {r.error[:60]}")
    return 0


def cmd_placeholder(args) -> int:
    out = _out_dir(args) / "index.html"
    out.write_text(report.placeholder_page(), encoding="utf-8")
    print(f"wrote {out} — replaced by `tti report` on the first run")
    return 0


def cmd_demo(args) -> int:
    """Render docs/demo.html from a synthetic run.

    Deliberately never writes docs/index.html. The demo uses made-up provider
    names and a seeded generator, and it prints whether the estimator
    recovered the latencies the generator drew -- which is the only thing the
    demo is evidence of.
    """
    import tempfile

    from . import demo as demo_mod
    out = _out_dir(args) / "demo.html"
    lines = demo_mod.render(pathlib.Path(tempfile.mkdtemp()), out, config.ladder())
    print(f"wrote {out}  (synthetic — not a result about any product)")
    print("estimator recovery against the generator's own draws:")
    print(lines)
    return 0 if "MISS" not in lines else 1


def cmd_observed(args) -> int:
    """Write the measured ladder as JSON, for the playground to render.

    Separate from `tti report` only in that it never needs a score: an
    event with one graded cell is already worth showing, whereas the
    dashboard waits until there is something to estimate. It is written on
    every report as well, so the published page cannot fall behind the
    published analysis.
    """
    from . import observed as observed_mod
    led = _ledger(args)
    data = observed_mod.build(led, limit=getattr(args, "limit", None))
    out = _out_dir(args) / "data"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "observed.json"
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    t = data["totals"]
    print(f"wrote {path} ({path.stat().st_size // 1024}KB) — "
          f"{t['events']} events, {t['provider_cells']} graded provider cells, "
          f"${t['spend_usd']:.4f}")
    return 0


def cmd_report(args) -> int:
    led = _ledger(args)
    events, results = led.events(), led.results()
    scores = _all_scores(led)
    if not scores and not _control_summary(led):
        print("no results yet")
        return 1
    # With control results and no provider arm the page still renders: the
    # control panel is the whole finding, and the banner says so.

    classes = sorted({e.source_class for e in events.values()})
    by_class = {c: _all_scores(led, c) for c in classes}

    from .power import pairwise_family, raw_pairs
    rate = _events_per_day(led)
    arms = [(s.provider, s.mode) for s in
            sorted(scores, key=lambda s: (s.median_ttl is None, s.median_ttl or 0))
            if s.provider != ORIGIN_ARM]
    # Every pair is computed first, then the whole family is Holm-adjusted
    # together, in the one function `tti power` and the demo also use.
    powers = pairwise_family(events, results, arms, rate)
    pairs = raw_pairs(powers)

    out_dir = _out_dir(args)
    stale_series = [(f"{sc.provider}/{sc.mode}",
                     staleness_by_rung(events, results, sc.provider, sc.mode))
                    for sc in sorted(scores, key=lambda s: (s.median_ttl is None,
                                                            s.median_ttl or 0))]
    from . import sensitivity as _sens
    try:
        sens_rows = _sens.run(led)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! sensitivity pass skipped: {exc}")
        sens_rows = []

    render_table = {f"{sc.provider}/{sc.mode}":
                    recall_by_render(events, results, sc.provider, sc.mode)
                    for sc in scores}
    render_table = {k: v for k, v in render_table.items() if v}

    ps = _plan_status(led, scores)
    panel = report.prereg_panel_html(ps)
    # The false-positive pass, offline: no registry is asked here, and the
    # panel says so. `tti decoy` is the verified figure.
    from . import decoy as _decoy
    try:
        fp_rep = _decoy.run(led, verify_absent=None, verbose=False)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! false-positive pass skipped: {exc}")
        fp_rep = None
    synthetic = ps == "synthetic"
    html = report.full_page(
        report.dashboard_html(scores, events, results, by_class, pairs, powers,
                              stale_series, sens_rows, render_table or None,
                              prereg_panel=panel,
                              fp_panel=report.fp_panel_html(fp_rep, synthetic=synthetic)))
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    results_md = (out_dir.parent / "RESULTS.md" if out_dir.name == "docs"
                  else out_dir / "RESULTS.md")
    plan_md = "\n".join(_plan_lines(ps))
    results_md.write_text(
        "# Results\n\n" + report.summary_md(scores, events, results) + "\n"
        + report.fp_md(fp_rep, synthetic=synthetic)
        + ("\n## Pre-registration\n\n```\n" + plan_md + "\n```\n"
           if plan_md.strip() else ""),
        encoding="utf-8")
    # The playground reads this; writing it here means the raw ladder and
    # the analysis of it are always generated from the same ledger read.
    cmd_observed(args)
    print(f"wrote {out_dir / 'index.html'} ({len(html)//1024}KB) and {results_md}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tti", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"tti {__version__}")
    ap.add_argument("--run-dir", help="ledger directory (default: ./runs)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    doc = sub.add_parser("doctor", help="check sources and providers are reachable")
    doc.add_argument("--subjects", type=int, default=2,
                     help="subjects to poll per source (default 2; 0 for all)")
    doc.set_defaults(fn=cmd_doctor)

    dc = sub.add_parser("decoy", help="false-positive rate against "
                                      "counterfactual answers (no API calls)")
    dc.add_argument("--json", action="store_true", help="machine-readable")
    dc.add_argument("--no-verify", action="store_true",
                    help="skip asking the registry whether each counterfactual "
                         "really is absent (offline; weaker evidence)")
    dc.set_defaults(fn=cmd_decoy)

    pr = sub.add_parser("prereg", help="the analysis plan, its hash, and its lock")
    pr.add_argument("--json", action="store_true", help="machine-readable")
    pr.set_defaults(fn=cmd_prereg)

    v = sub.add_parser("verify", help="offline self-check: config, estimator, "
                                      "grader, ledger, platform")
    v.add_argument("--json", action="store_true", help="machine-readable")
    v.set_defaults(fn=cmd_verify)

    d = sub.add_parser("discover", help="poll sources and enqueue probes")
    d.add_argument("--sources", nargs="*", help="limit to these sources")
    d.add_argument("--dry-run", action="store_true",
                   help="poll sources and print what would be enqueued, "
                        "writing nothing")
    d.set_defaults(fn=cmd_discover)

    p = sub.add_parser("probe", help="run probes that are due")
    p.add_argument("--limit", type=int, help="cap probes this run")
    p.add_argument("--dry-run", action="store_true", help="print, do not call")
    p.set_defaults(fn=cmd_probe)

    scp = sub.add_parser("score", help="print the leaderboard")
    scp.add_argument("--json", action="store_true")
    scp.set_defaults(fn=cmd_score)
    stp = sub.add_parser("status", help="queue and budget state")
    stp.add_argument("--json", action="store_true")
    stp.set_defaults(fn=cmd_status)
    rp = sub.add_parser("report", help="write RESULTS.md and docs/index.html")
    rp.add_argument("--out-dir", help="where to write rendered pages "
                    "(default: the repo's docs/)")
    rp.set_defaults(fn=cmd_report)
    dm = sub.add_parser("demo", help="render docs/demo.html from a synthetic run")
    dm.add_argument("--out-dir", help="where to write the page")
    dm.set_defaults(fn=cmd_demo)
    ob = sub.add_parser("observed",
                        help="write docs/data/observed.json — the measured "
                             "ladder, one cell per arm per rung")
    ob.add_argument("--out-dir", help="where to write the page")
    ob.add_argument("--limit", type=int,
                    help="keep only the newest N events")
    ob.set_defaults(fn=cmd_observed)
    ph = sub.add_parser("placeholder", help="write the pre-run docs/index.html")
    ph.add_argument("--out-dir", help="where to write the page")
    ph.set_defaults(fn=cmd_placeholder)
    cw = sub.add_parser("crawlability",
                        help="can an AI agent read this page? (no keys, no ledger)")
    cw.add_argument("urls", nargs="+", help="one or more page URLs")
    cw.add_argument("--find", help="check whether this exact string is agent-visible")
    cw.add_argument("--json", action="store_true", help="machine-readable output")
    cw.add_argument("--repeat", type=int, default=2,
                    help="fetch this many times and require agreement (default 2)")
    cw.set_defaults(fn=cmd_crawlability)

    rt = sub.add_parser("routes",
                        help="sample a site's sitemap and profile its routes")
    rt.add_argument("sites", nargs="+", help="site root, e.g. https://example.com")
    rt.add_argument("--sample", type=int, default=8, help="routes to sample (default 8)")
    rt.add_argument("--repeat", type=int, default=2,
                    help="fetches per route; a verdict needs them to agree")
    rt.add_argument("--workers", type=int, default=6)
    rt.set_defaults(fn=cmd_routes)

    wt = sub.add_parser("watch",
                        help="record crawlability over time and report what moved")
    wt.add_argument("urls", nargs="*", help="URLs to record (default: data/corpus.yaml)")
    wt.add_argument("--report", action="store_true",
                    help="only report on existing history; do not fetch")
    wt.add_argument("--repeat", type=int, default=2)
    wt.add_argument("--workers", type=int, default=12)
    wt.add_argument("--out-dir", help="also render corpus.html here")
    wt.add_argument("--json", action="store_true")
    wt.set_defaults(fn=cmd_watch)

    sv = sub.add_parser("survey",
                        help="how much of a corpus is readable without JavaScript?")
    sv.add_argument("urls", nargs="*", help="URLs to scan (default: data/corpus.yaml)")
    sv.add_argument("--workers", type=int, default=12)
    sv.add_argument("--repeat", type=int, default=2,
                    help="fetches per URL; a verdict needs them to agree (default 2)")
    sv.add_argument("--json", action="store_true")
    sv.add_argument("--verbose", action="store_true", help="list unreachable targets")
    sv.add_argument("--out-dir", help="also render corpus.html here")
    sv.set_defaults(fn=cmd_survey)

    fx = sub.add_parser("forecast", help="days until this run can support a claim")
    fx.add_argument("--sources", nargs="*", help="limit to these sources")
    fx.add_argument("--json", action="store_true")
    fx.set_defaults(fn=cmd_forecast)
    pw = sub.add_parser("power", help="can this run support the claim it invites?")
    pw.add_argument("--json", action="store_true")
    pw.set_defaults(fn=cmd_power)
    sn = sub.add_parser("sensitivity",
                        help="how much does the ranking depend on grading rules?")
    sn.add_argument("--json", action="store_true")
    sn.set_defaults(fn=cmd_sensitivity)

    rg = sub.add_parser("regrade", help="re-grade stored payloads, no API calls")
    rg.add_argument("--write", action="store_true", help="apply the new verdicts")
    rg.set_defaults(fn=cmd_regrade)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except config.ConfigError as exc:
        # Exit 2, distinct from a command that ran and reported a problem, so
        # a cron wrapper can tell "misconfigured" from "nothing to do".
        print(f"\nconfiguration error\n  {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
