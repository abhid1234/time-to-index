"""The measured ladder, flattened into something a page can render.

`docs/index.html` is the analysis: survival curves, confidence intervals,
pairwise power. This is the raw material underneath it -- one row per event,
one cell per arm per rung, with the verdict exactly as recorded. It exists
because the playground's ladder is a simulation, and a reader who has just
watched a simulation is owed the real thing next to it.

The one judgement in here is what an empty cell means, and it is the whole
point of the project. A rung with no result is not an ABSENT. It is one of:
not due yet, dispatched and pending, or never dispatched (carry-forward,
budget cap, rung slip). So the probe queue is read alongside the results and
every cell carries a `state` that says which -- because a blank square that
a viewer reads as "the index didn't have it" would be this project making
the exact error it was built to expose.
"""
from __future__ import annotations

import time
from typing import Any

from .ledger import Ledger
from .metrics import ORIGIN
from .models import ABSENT, ERROR, FRESH, SKIPPED, STALE, Event, Probe, ProbeResult

# The ladder, in the order a reader walks it. Kept here rather than imported
# from report.RUNGS so that a page rendered from this file states the rungs
# the data actually used, not the ones the current config prefers.
RUNG_LABELS = {300: "5m", 900: "15m", 3600: "1h",
               21600: "6h", 86400: "24h", 259200: "72h"}

# How many events the page ships by default. Every visitor downloads this
# file, and a run left going for a year would otherwise put megabytes of
# ladder into it. The totals are computed over the whole ledger regardless,
# so capping what is drawn never understates what was collected.
DEFAULT_LIMIT = 60


def rung_label(rung: int) -> str:
    if rung in RUNG_LABELS:
        return RUNG_LABELS[rung]
    if rung < 3600:
        return f"{rung // 60}m"
    if rung < 86400:
        return f"{rung // 3600}h"
    return f"{rung // 86400}d"


def _cell(result: ProbeResult | None, probe: Probe | None,
          now: float) -> dict[str, Any]:
    """One square of the matrix, with its state named rather than implied."""
    if result is not None:
        return {
            "state": "graded",
            "verdict": result.verdict,
            "lag": round(result.lag),
            "latency_ms": result.latency_ms,
            "cost_usd": round(result.cost_usd, 6),
            "n_results": result.n_results,
            "chars": result.chars,
            "fresh_hits": len(result.matched_fresh),
            "stale_hits": len(result.matched_stale),
            "note": result.note or "",
        }
    if probe is None:
        # No result and no queued probe: this arm was never scheduled at this
        # rung at all -- typically because the arm had no key when the event
        # was discovered, which is when probes are enqueued.
        return {"state": "never_scheduled"}
    if probe.due_at > now:
        return {"state": "scheduled", "due_at": probe.due_at,
                "due_in": round(probe.due_at - now)}
    return {"state": "pending", "due_at": probe.due_at,
            "overdue_by": round(now - probe.due_at)}


def _arm_key(row: ProbeResult | Probe) -> tuple[str, str]:
    return (row.provider, row.mode)


def build(led: Ledger, *, now: float | None = None,
          limit: int | None = None) -> dict[str, Any]:
    """Flatten the ledger into one JSON-serialisable structure.

    `limit` keeps the newest N events, since the page is a demonstration and
    a run left going for months should not ship a megabyte to every visitor.
    """
    now = now or time.time()
    events: dict[str, Event] = led.events()
    probes: dict[str, Probe] = led.probes()
    results: list[ProbeResult] = led.results()

    by_event_probe: dict[str, dict[tuple[str, str], dict[int, Probe]]] = {}
    for p in probes.values():
        by_event_probe.setdefault(p.event_id, {}).setdefault(
            _arm_key(p), {})[p.rung] = p

    by_event_result: dict[str, dict[tuple[str, str], dict[int, ProbeResult]]] = {}
    for r in results:
        # `led.results()` has already de-duplicated by probe_id, first
        # occurrence winning -- the duplicates it guards against come from two
        # overlapping `tti probe` runs, where the second row is a repeat, not
        # a correction. A regrade is not an append at all: `tti regrade
        # --write` rewrites results.jsonl atomically. So there is exactly one
        # row per probe here and nothing to arbitrate.
        by_event_result.setdefault(r.event_id, {}).setdefault(
            _arm_key(r), {})[r.rung] = r

    ordered = sorted(events.values(), key=lambda e: e.published_at, reverse=True)
    if limit:
        ordered = ordered[:limit]

    out_events = []
    for ev in ordered:
        arms_probe = by_event_probe.get(ev.event_id, {})
        arms_result = by_event_result.get(ev.event_id, {})
        arm_keys = sorted(set(arms_probe) | set(arms_result),
                          key=lambda k: (k[0] == ORIGIN, k))

        # The rungs this event actually used, not the ones configured now.
        rungs = sorted({rung
                        for by_rung in list(arms_probe.values())
                                     + list(arms_result.values())
                        for rung in by_rung})
        if not rungs:
            continue

        arms = []
        for provider, mode in arm_keys:
            cells = [_cell(arms_result.get((provider, mode), {}).get(rung),
                           arms_probe.get((provider, mode), {}).get(rung),
                           now)
                     for rung in rungs]
            graded = [c for c in cells if c["state"] == "graded"]
            first_fresh = next((rungs[i] for i, c in enumerate(cells)
                                if c.get("verdict") == "FRESH"), None)
            arms.append({
                "provider": provider,
                "mode": mode,
                "control": provider == ORIGIN,
                "cells": cells,
                "first_fresh_rung": first_fresh,
                "spend_usd": round(sum(c.get("cost_usd") or 0.0
                                       for c in graded), 6),
            })

        out_events.append({
            "event_id": ev.event_id,
            "source": ev.source,
            "source_class": ev.source_class,
            "subject": ev.subject,
            "question": ev.question,
            "answer": ev.answer,
            "predecessor": ev.predecessor,
            "published_at": ev.published_at,
            "detection_lag": round(ev.discovered_at - ev.published_at),
            "age_seconds": round(now - ev.published_at),
            "url": ev.url,
            "rungs": rungs,
            "rung_labels": [rung_label(r) for r in rungs],
            "arms": arms,
        })

    # Totals are computed over the whole ledger, never over the events that
    # survived `limit`. The page renders them under "across the whole run",
    # and a run that silently reported the newest fifty events as its total
    # would understate its own spend and its own sample size -- the second of
    # which is the number a reader most needs to be able to trust.
    provider_results = [r for r in results if r.provider != ORIGIN]
    return {
        "generated_at": now,
        "events": out_events,
        "totals": {
            "events": len(out_events),           # rendered here
            "events_in_ledger": len(events),     # collected in total
            "graded_cells": len(results),
            "provider_cells": len(provider_results),
            "fresh": len([r for r in provider_results if r.verdict == FRESH]),
            "stale": len([r for r in provider_results if r.verdict == STALE]),
            "absent": len([r for r in provider_results if r.verdict == ABSENT]),
            "error": len([r for r in provider_results if r.verdict == ERROR]),
            "skipped": len([r for r in provider_results if r.verdict == SKIPPED]),
            "spend_usd": round(sum(r.cost_usd or 0.0
                                   for r in provider_results), 6),
        },
    }
