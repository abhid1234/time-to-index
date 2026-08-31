"""Discovery and probe execution.

Two entry points, both idempotent and both safe to run from cron every five
minutes:

    discover()  poll sources, drop events we found too late, enqueue the
                full ladder of probes for every configured arm.
    run_due()   execute probes whose due time has arrived, grade them, write
                results and raw payloads.

Idempotency is what makes this survivable as an unattended job. Probe ids are
a hash of (event, provider, mode, rung), the ledger records which ids have
completed, and a re-run skips them. A crashed run loses at most the probes
in flight.

Three rules keep the numbers honest, and each one costs us data:

    Detection lag.  An event our collector noticed 40 minutes after
    publication cannot be probed at the t+5m rung, because that rung has
    already passed. Rather than record it at the wrong lag, the event is
    dropped entirely.

    Rung slip.  If the runner was down and a probe fires 90 minutes past its
    t+15m due time, recording it as a 15-minute observation is a lie and
    recording it as a 105-minute observation biases the ladder. It is
    dropped, and the drop is written to the ledger.

    Carry-forward.  Once an arm answers FRESH for an event, its remaining
    rungs are skipped. Indexing is not observed to reverse, the later rungs
    would cost money to confirm something already established, and the
    survival estimator only needs the first FRESH.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import config, control, phrasing, providers, sources
from .budget import Budget, BudgetExceeded, unit_cost, utc_day
from .grader import grade
from .ledger import Ledger
from .models import ERROR, FRESH, SKIPPED, STALE, Event, Probe, ProbeResult


@dataclass
class DiscoverReport:
    collected: int = 0
    new_events: int = 0
    dropped_late: int = 0
    dropped_future: int = 0
    probes_queued: int = 0
    per_source: dict = None
    source_errors: dict = None
    broken_sources: list = None
    dry_run: bool = False
    preview: list = None

    def __post_init__(self):
        self.per_source = self.per_source or {}
        self.source_errors = self.source_errors or {}
        self.broken_sources = self.broken_sources or []
        self.preview = self.preview or []


def discover(ledger: Ledger, source_names: list[str] | None = None,
             verbose: bool = True, dry_run: bool = False) -> DiscoverReport:
    """Poll every configured source and enqueue the ladder for what is new.

    With `dry_run`, the sources are still polled -- collection is reads, and
    the only way to know what a source is emitting right now is to ask it --
    but nothing is written: no events, no probes, and no advance of the
    per-subject high-water mark. The same run repeated without `dry_run`
    collects the same events.

    Two things a dry run cannot promise, both of them about time:

        The detection-lag filter is evaluated against the clock at the moment
        of the call. An event that clears it now can exceed `max_detection_
        lag_seconds` by the time a real run happens, and would then be
        dropped. A dry run is a description of this instant, not a plan.

        A source polled twice may answer differently in between; that is the
        entire premise of the project.
    """
    s = config.settings()
    names = source_names or s.get("sources", [])
    max_lag = float(s.get("max_detection_lag_seconds", config.MAX_DETECTION_LAG))
    max_skew = float(s.get("max_clock_skew_seconds", config.MAX_CLOCK_SKEW))
    seen = ledger.seen_subjects()
    rep = DiscoverReport()

    candidates: list[Event] = []
    for name in names:
        src = sources.get(name)
        try:
            got = src.collect(seen)
        except Exception as exc:  # a broken collector must not stop the others
            rep.source_errors[name] = [f"{type(exc).__name__}: {exc}"[:200]]
            rep.broken_sources.append(name)
            if verbose:
                print(f"  ! {name}: {exc}")
            continue
        rep.per_source[name] = len(got)
        if src.errors:
            rep.source_errors[name] = src.errors
            if verbose:
                print(f"  ! {name}: {len(src.errors)}/{src.attempted} subjects failed "
                      f"-- {src.errors[0][:120]}")
        if src.all_failed:
            # Every subject failed: the source is unreachable, not quiet. These
            # look identical in the event count, and conflating them is how a
            # benchmark ends up publishing a gap in its own collection as a
            # finding about somebody else's index.
            rep.broken_sources.append(name)
        candidates.extend(got)
    rep.collected = len(candidates)

    fresh_enough = []
    for e in candidates:
        if e.published_at <= 0:
            rep.dropped_late += 1
            continue
        # A publication timestamp ahead of our clock. Seconds of skew are
        # ordinary; more than the tolerance means the ladder would anchor to
        # a t0 that has not happened, so every lag it produced would describe
        # nothing while looking like a normal event. Causes seen in the wild:
        # a publisher's clock, an embargoed release dated forward, and a
        # timezone bug in a collector.
        if e.detection_lag < -max_skew:
            rep.dropped_future += 1
            continue
        if e.detection_lag > max_lag:
            # Not a failure. The watchlist is polled every five minutes, so
            # anything older than that was published before we started
            # watching this subject, and its ladder cannot be honoured.
            rep.dropped_late += 1
            continue
        fresh_enough.append(e)

    if dry_run:
        # Same predicate `add_events` applies, without the append. Computed
        # here rather than by calling and rolling back, because there is no
        # rollback for an append-only file.
        known = set(ledger.events())
        added = [e for e in fresh_enough if e.event_id not in known]
    else:
        added = ledger.add_events(fresh_enough)
    rep.new_events = len(added)
    rep.dry_run = dry_run
    if dry_run:
        rep.preview = [(e.source, e.subject, e.answer, e.detection_lag)
                       for e in added]

    arms = providers.available_arms()
    if s.get("origin_control", True):
        # Always first, so the control's own fetch happens as close to the
        # rung as the paid calls do.
        arms = [("origin", "direct")] + arms
    ladder = config.ladder()
    queued = [
        Probe(event_id=e.event_id, provider=p, mode=m, rung=r,
              due_at=e.published_at + r)
        for e in added for (p, m) in arms for r in ladder
    ]

    # Optional second axis: the same event, rung and provider asked more than
    # one way. Rung-limited by configuration because three phrasings at every
    # rung triples the bill, while three phrasings at one rung adds two probes
    # per event. The control arm is excluded -- it fetches a URL and never
    # sees a question.
    ph = s.get("phrasing_probe") or {}
    if ph.get("enabled"):
        ph_rungs = [int(r) for r in ph.get("rungs", [3600])]
        ph_max = int(ph.get("variants", 3))
        for e in added:
            n = min(phrasing.count(e), ph_max)
            for (p, m) in arms:
                if p == "origin":
                    continue
                for r in ph_rungs:
                    for idx in range(1, n):
                        queued.append(Probe(
                            event_id=e.event_id, provider=p, mode=m, rung=r,
                            due_at=e.published_at + r, phrasing=idx))
    if dry_run:
        known_p = set(ledger.probes())
        rep.probes_queued = len([p for p in queued
                                 if p.probe_id not in known_p])
    else:
        rep.probes_queued = len(ledger.add_probes(queued))
    return rep


@dataclass
class RunReport:
    dispatched: int = 0
    fresh: int = 0
    stale: int = 0
    absent: int = 0
    errors: int = 0
    skipped_carry: int = 0
    skipped_budget: int = 0
    dropped_slip: int = 0
    spend_usd: float = 0.0
    refunded_usd: float = 0.0
    cap_usd: float = 0.0
    days_crossed: int = 0


def run_due(ledger: Ledger, now: float | None = None, limit: int | None = None,
            dry_run: bool = False, verbose: bool = True) -> RunReport:
    now = now or time.time()
    s = config.settings()
    max_results = int(s.get("max_results", 5))
    max_chars = int(s.get("max_chars_per_result", 1500))
    slip = float(s.get("max_rung_slip_seconds", config.MAX_RUNG_SLIP))

    events = ledger.events()
    done = ledger.completed_probe_ids()
    resolved = ledger.resolved_fresh()
    day = utc_day(now)
    budget = Budget(spent_today=ledger.spent_on(day), day=day)
    rep = RunReport(cap_usd=budget.cap)

    due = [p for p in ledger.probes().values()
           if p.probe_id not in done and p.due_at <= now and p.event_id in events]
    due.sort(key=lambda p: p.due_at)
    if limit:
        due = due[:limit]

    # Lock the analysis plan to this run, on the first probe that will
    # actually be dispatched. Before there is data there is nothing to be
    # tempted by, so a plan edited up to this moment is a plan being written,
    # not a plan being revised in the light of results.
    if due and not dry_run:
        try:
            from . import prereg
            prereg.lock(ledger.root, prereg.parse())
        except Exception as exc:      # never block collection on the plan
            if verbose:
                print(f"  ! could not lock the analysis plan: {exc}")

    out: list[ProbeResult] = []
    for probe in due:
        event = events[probe.event_id]
        lag = now - event.published_at

        # A long run can cross midnight. Without this the second half keeps
        # charging against a cap that has already reset, and refuses probes
        # for a budget that is no longer spent.
        today = utc_day(time.time())
        if today != budget.day:
            budget.roll_to(today, ledger.spent_on(today))
            rep.days_crossed += 1

        # Carry-forward is per phrasing. A provider that answers one wording
        # and not another has not "already resolved" the others, and skipping
        # them would erase the only evidence of that.
        if not probe.phrasing and (probe.event_id, probe.provider, probe.mode) in resolved:
            out.append(_skip(probe, event, now, lag, "carry-forward: already FRESH"))
            rep.skipped_carry += 1
            continue

        if now - probe.due_at > slip:
            out.append(_skip(probe, event, now, lag,
                             f"rung slip {now - probe.due_at:.0f}s exceeds {slip:.0f}s"))
            rep.dropped_slip += 1
            continue

        # The origin control is a plain HTTP GET, so it is free and is never
        # refused by the spend cap. Losing it would be the worst possible
        # economy: without it, every ABSENT verdict from every paid provider
        # becomes ambiguous.
        is_control = probe.provider == "origin"
        try:
            cost = (0.0 if is_control
                    else unit_cost(probe.provider, probe.mode, max_results))
        except config.ConfigError as exc:
            # An arm the price table no longer knows. Skipping is right;
            # spending against a cap that cannot see the charge is not.
            out.append(_skip(probe, event, now, lag, f"unpriced: {exc}"))
            rep.skipped_budget += 1
            continue
        try:
            budget.charge(cost)
        except BudgetExceeded as exc:
            out.append(_skip(probe, event, now, lag, f"budget: {exc}"))
            rep.skipped_budget += 1
            continue

        if dry_run:
            print(f"  would probe {probe.provider}/{probe.mode} @{probe.rung}s "
                  f"${cost:.4f} :: {event.question[:70]}")
            rep.dispatched += 1
            continue

        t0 = time.perf_counter()
        try:
            if is_control:
                payload = control.probe_origin(event)
            else:
                question = (event.question if not probe.phrasing
                            else phrasing.variant(event, probe.phrasing))
                if question is None:
                    raise RuntimeError(
                        f"phrasing {probe.phrasing} unavailable for {event.source}")
                payload = providers.get(probe.provider).search(
                    question, probe.mode,
                    max_results=max_results, max_chars=max_chars)
        except Exception as exc:  # noqa: BLE001
            # Release the reservation: nothing was billed for a call that
            # never completed, and holding the charge would let a flaky
            # provider exhaust the day's cap for free.
            budget.refund(cost)
            out.append(ProbeResult(
                probe_id=probe.probe_id, event_id=event.event_id,
                provider=probe.provider, mode=probe.mode, rung=probe.rung,
                phrasing=probe.phrasing,
                requested_at=now, lag=lag, verdict=ERROR, cost_usd=0.0,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                note=str(exc)[:400]))
            rep.errors += 1
            continue

        latency = int((time.perf_counter() - t0) * 1000)
        verdict, fresh_hits, stale_hits, chars = grade(event, payload)
        note = ""
        render = ""
        if is_control:
            state = payload.get("state", "")
            rank = payload.get("origin_rank", -1)
            render = payload.get("render", "")
            # A control probe that could not fetch anything is an ERROR, not
            # an ABSENT. Scoring it as ABSENT would assert the fact was not on
            # the web, which is exactly what we failed to establish.
            if state in (control.BLOCKED, control.DISALLOWED, control.ERROR):
                verdict = ERROR
            note = (f"origin:{state}" + (f" rank={rank}" if rank >= 0 else "")
                    + (f" render={render}" if render else ""))
        raw_ref = ledger.store_raw(probe.provider, probe.probe_id, payload)

        out.append(ProbeResult(
            probe_id=probe.probe_id, event_id=event.event_id,
            provider=probe.provider, mode=probe.mode, rung=probe.rung,
            phrasing=probe.phrasing, render=render,
            requested_at=now, lag=lag, verdict=verdict, latency_ms=latency,
            matched_fresh=fresh_hits, matched_stale=stale_hits,
            n_results=_count_results(payload), chars=chars,
            cost_usd=cost, raw_ref=raw_ref, note=note))

        rep.dispatched += 1
        rep.spend_usd += cost
        if verdict == FRESH:
            rep.fresh += 1
            if not probe.phrasing:
                resolved.add((probe.event_id, probe.provider, probe.mode))
        elif verdict == STALE:
            rep.stale += 1
            if verbose:
                print(f"  STALE {probe.provider}/{probe.mode} @{probe.rung}s "
                      f"returned {stale_hits} for {event.subject}")
        else:
            rep.absent += 1

    rep.refunded_usd = budget.refunded
    if not dry_run:
        ledger.add_results(out)
    return rep


def _skip(probe: Probe, event: Event, now: float, lag: float, note: str) -> ProbeResult:
    return ProbeResult(
        probe_id=probe.probe_id, event_id=event.event_id, provider=probe.provider,
        mode=probe.mode, rung=probe.rung, phrasing=probe.phrasing,
        requested_at=now, lag=lag, verdict=SKIPPED, cost_usd=0.0, note=note)


def _count_results(payload) -> int:
    if not isinstance(payload, dict):
        return 0
    for k in ("results", "data", "organic", "items"):
        v = payload.get(k)
        if isinstance(v, list):
            return len(v)
    web = payload.get("web")
    if isinstance(web, dict) and isinstance(web.get("results"), list):
        return len(web["results"])
    return 0
