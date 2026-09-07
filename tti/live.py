"""One event, asked of every arm right now, for the demo page.

This is not the benchmark. The benchmark starts a clock when a fact is
published and asks again at six fixed lags; this asks once, at whatever lag
happens to obtain when someone presses a button. A single sample at an
arbitrary age cannot support a claim about any provider's indexing speed, and
`age_seconds` is returned on every response so the page can say so.

What it is for: making the mechanism visible. The question, the aliases, the
grading and the origin control are the same code the benchmark runs, so what
a reader sees here is what the harness would have recorded.

Cost is bounded by three things and none of them are optional in a page
anyone can open: only allow-listed subjects are accepted, the caller is
expected to cache on the answer's `cache_seconds`, and an arm with no key is
skipped rather than substituted.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from . import control, grader, providers
from .budget import unit_cost
from .models import ABSENT
from .sources import npm as npm_source

# Only these may be asked. An open parameter is an open invitation to spend
# someone else's budget on arbitrary traffic.
ALLOWED = ("astro", "next", "react", "vite", "typescript", "svelte")

# How long an answer stays good. Chosen to be shorter than the fastest thing
# it could miss -- a release landing inside the window -- and long enough that
# a page being read by several people costs one fan-out, not several.
CACHE_SECONDS = 900

MAX_RESULTS = 5
MAX_CHARS = 1500


def _fmt_lag(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    if seconds < 5400:
        return f"{seconds / 60:.0f} minutes"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 86400:.1f} days"


def compare(
    pkg: str,
    *,
    fetch_packument: Callable[[str], tuple[dict, int]] | None = None,
    now: float | None = None,
    include_control: bool = True,
) -> dict[str, Any]:
    """Ask every keyed arm about `pkg`'s current version, and grade the answers.

    Raises ValueError for a subject that is not allow-listed, so the caller
    answers 400 rather than spending on it.
    """
    if pkg not in ALLOWED:
        raise ValueError(
            f"{pkg!r} is not one of the subjects this endpoint will ask about")

    fetch = fetch_packument or npm_source.fetch_packument
    doc, _size = fetch(pkg)
    event = npm_source.event_from_packument(pkg, doc)
    if event is None:
        raise ValueError(f"the registry document for {pkg!r} implies no event")

    now = now or time.time()
    age = max(0.0, now - event.published_at)

    arms: list[dict[str, Any]] = []

    if include_control:
        started = time.time()
        try:
            payload = control.probe_origin(event)
            verdict, fresh, stale, chars = grader.grade(event, payload)
            arms.append({
                "provider": "origin", "mode": "direct", "control": True,
                "verdict": verdict, "fresh_hits": fresh, "stale_hits": stale,
                "chars": chars, "latency_ms": round((time.time() - started) * 1000),
                "cost_usd": 0.0, "cost_source": "free",
                # Which origin answered matters: npmjs.com refuses non-browser
                # clients, so a fallback to the registry answers a weaker
                # question and the record has to say which one was reached.
                "note": payload.get("origin_used") or payload.get("error") or None,
                "render": payload.get("render"),
                "error": None,
            })
        except Exception as exc:  # noqa: BLE001
            arms.append({
                "provider": "origin", "mode": "direct", "control": True,
                "verdict": None, "error": f"{type(exc).__name__}: {exc}",
                "latency_ms": round((time.time() - started) * 1000),
                "cost_usd": 0.0,
            })

    for name, mode in providers.available_arms():
        started = time.time()
        try:
            payload = providers.get(name).search(
                event.question, mode,
                max_results=MAX_RESULTS, max_chars=MAX_CHARS)
            verdict, fresh, stale, chars = grader.grade(event, payload)
            # List price unless the vendor states its own charge, which is
            # how the scheduler records it; a price table can drift and the
            # response cannot.
            cost, cost_source = unit_cost(name, mode, MAX_RESULTS), "list"
            hook = getattr(providers.get(name), "reported_cost", None)
            actual = hook(payload) if hook else None
            if actual is not None:
                cost, cost_source = actual, "reported"
            arms.append({
                "provider": name, "mode": mode, "control": False,
                "verdict": verdict, "fresh_hits": fresh, "stale_hits": stale,
                "chars": chars, "latency_ms": round((time.time() - started) * 1000),
                "cost_usd": cost, "cost_source": cost_source,
                "note": None, "error": None,
            })
        except Exception as exc:  # noqa: BLE001
            # An arm that failed is not an arm that returned nothing. Grading
            # a transport error as ABSENT would charge the provider for our
            # network, so the verdict stays null and the reason is shown.
            arms.append({
                "provider": name, "mode": mode, "control": False,
                "verdict": None, "error": f"{type(exc).__name__}: {exc}",
                "latency_ms": round((time.time() - started) * 1000),
                "cost_usd": None, "cost_source": None,
            })

    graded = [a for a in arms if not a["control"] and a["verdict"]]
    return {
        "subject": pkg,
        "source": "npm",
        "question": event.question,
        "answer": event.answer,
        "predecessor": event.predecessor,
        "published_at": event.published_at,
        "asked_at": now,
        "age_seconds": age,
        "age_human": _fmt_lag(age),
        "arms": arms,
        "summary": {
            "asked": len([a for a in arms if not a["control"]]),
            "graded": len(graded),
            "fresh": len([a for a in graded if a["verdict"] == "FRESH"]),
            "stale": len([a for a in graded if a["verdict"] == "STALE"]),
            "absent": len([a for a in graded if a["verdict"] == ABSENT]),
        },
        "spend_usd": round(sum(a["cost_usd"] or 0.0
                               for a in arms if not a["control"]), 6),
        "cache_seconds": CACHE_SECONDS,
        "disclaimer": (
            "One sample at one age, not a measurement of indexing speed. The "
            "benchmark asks the same question at six fixed lags and reports a "
            "survival curve; this asks once, "
            f"{_fmt_lag(age)} after publication."
        ),
    }
