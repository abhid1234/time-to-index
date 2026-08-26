"""The origin control arm.

Without this, every ABSENT verdict is ambiguous. A provider that does not
return the new fact might have a slow crawler, or the fact might not be
fetchable from its own canonical URL yet -- CDN propagation, a page that
renders client-side, a robots directive, a registry whose web front end lags
its API. Those are different findings and only one of them is about the
provider.

So at every rung, alongside the paid providers, the canonical URL is fetched
directly with an ordinary HTTP GET and checked for the answer token. That
gives, per event per rung, a fact of the form "the document was retrievable
from its own origin at t+15m". Three things become possible:

    Conditional recall.  Of the events verifiably fetchable at rung r, what
    fraction did provider X have? This is the number that is actually about
    the provider.

    Crawler lag vs publication lag.  Time-to-index measured from
    publication mixes both. Measured from the origin becoming fetchable, it
    isolates the crawler.

    Uncrawlable facts.  A fact that never appears in its canonical page's
    served bytes is not indexable by anyone from that page. Providers that
    return it got it somewhere else, which is a finding about their sourcing
    rather than their speed, and it is the kind of thing a naive benchmark
    would silently score as a win.

The control costs nothing but politeness: one conditional GET per event per
rung, with robots.txt honoured, and it is the arm most likely to change how
the leaderboard reads.
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.robotparser
from typing import Any

from . import config, http
from .models import Event

# Outcome of an origin probe. These are deliberately five states rather than
# a boolean: "the page 403s every non-browser client" and "the page loaded
# and the fact was not in it" support completely different conclusions, and
# collapsing them would let a bot-walled origin masquerade as a slow web.
FOUND = "found"          # fetched, and the answer token is in the bytes
NOT_FOUND = "not_found"  # fetched, and it is not
BLOCKED = "blocked"      # origin refused us (403/429); fetchability unknown
DISALLOWED = "disallowed"  # robots.txt says do not crawl this
ERROR = "error"          # network or protocol failure

# Where in the document the fact actually lives. The control arm already
# fetches the page, so this axis is free -- and it is the one that turns
# "provider X missed it" into something actionable, because a fact that
# exists only inside a __NEXT_DATA__ blob is a different retrieval problem
# from one sitting in an <h1>.
RENDER_HTML = "server_html"      # in the visible text after scripts are stripped
RENDER_JSON = "embedded_json"    # only inside a script/JSON blob on the page
RENDER_API = "api_only"          # only via an API fallback origin, not the page
RENDER_NONE = "not_present"

EXCERPT_RADIUS = 400
NO_MATCH_HEAD = 3000
MAX_BODY = 2_000_000        # refuse to scan an unbounded stream

_robots_cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}
ROBOTS_TTL = 3600.0


def robots_allows(url: str, agent: str = "*") -> bool | None:
    """Does the origin's robots.txt permit fetching this URL?

    Returns None when robots.txt cannot be read, which is not the same as
    permission and is recorded as its own state. A provider cannot be marked
    down for missing a document nobody is allowed to crawl, and a benchmark
    that fetches what it was asked not to has no standing to publish
    anything about crawling.
    """
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    root = f"{parts.scheme}://{parts.netloc}"
    now = time.time()
    cached = _robots_cache.get(root)
    if cached and now - cached[0] < ROBOTS_TTL:
        rp = cached[1]
    else:
        rp = urllib.robotparser.RobotFileParser()
        try:
            body = http.get_text(root + "/robots.txt", timeout=10.0, retries=0)
            rp.parse(body.splitlines())
        except Exception:  # noqa: BLE001
            rp = None
        _robots_cache[root] = (now, rp)
    if rp is None:
        return None
    try:
        return rp.can_fetch(agent, url)
    except Exception:  # noqa: BLE001
        return None


def _boundary(token: str) -> re.Pattern[str]:
    core = re.escape(token)
    if token[:1].isdigit():
        core = "[vV]?" + core        # same rule as the grader; see grader._pattern
    return re.compile(rf"(?<![\w.]){core}(?![\w.])", re.IGNORECASE)


_SCRIPTY = re.compile(r"<(script|style|template|noscript)\b[^>]*>.*?</\1>",
                      re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def visible_text(html: str) -> str:
    """Roughly what a crawler that does not execute JavaScript would read.

    Script, style and template blocks go first, then the remaining tags. This
    is deliberately crude: the question is not "what would a browser paint"
    but "is this fact in the served bytes as text, or is it only in a data
    blob a renderer would have to run to surface". A regex answers that;
    a parser would answer it more slowly and no more usefully.
    """
    return _TAG.sub(" ", _SCRIPTY.sub(" ", html))


def classify_render(body: str, tokens: list[str], origin_rank: int) -> str:
    """Where the answer token sits in the document that carried it."""
    pats = [_boundary(t) for t in tokens if len(t) >= 3]
    if not pats:
        return RENDER_NONE
    if not any(p.search(body) for p in pats):
        return RENDER_NONE
    if origin_rank > 0:
        # It came from an API fallback, so the crawler-facing page is not
        # what answered and we cannot claim anything about its rendering.
        return RENDER_API
    text = visible_text(body)
    return RENDER_HTML if any(p.search(text) for p in pats) else RENDER_JSON


def _attempt(url: str, event: Event) -> dict[str, Any]:
    """One origin URL, fetched and scanned."""
    rec: dict[str, Any] = {
        "url": url, "state": ERROR, "robots_allowed": None, "status": None,
        "bytes": 0, "sha256": "", "elapsed_ms": 0, "matched": [],
        "truncated": False, "error": "", "excerpt": "", "body": None,
    }
    allowed = robots_allows(url, config.contact_ua().split("/")[0])
    rec["robots_allowed"] = allowed
    if allowed is False:
        # Not a failure of anything. Recorded and excluded from conditional
        # recall, because nobody is permitted to crawl this.
        rec["state"] = DISALLOWED
        return rec

    t0 = time.perf_counter()
    try:
        body = http.get_text(
            url, timeout=20.0, retries=1,
            headers={"Accept": "text/html,application/json;q=0.9,*/*;q=0.8"})
        rec["status"] = 200
    except Exception as exc:  # noqa: BLE001
        rec["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        msg = str(exc)
        rec["error"] = msg[:300]
        # A 403 or 429 means the origin refused *us*. It says nothing about
        # whether a search engine's crawler can fetch the page, so it must
        # not be recorded as "the fact was not on the web".
        rec["state"] = BLOCKED if ("403" in msg[:12] or "429" in msg[:12]) else ERROR
        return rec

    rec["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY]
        rec["truncated"] = True
    rec["bytes"] = len(body)
    rec["sha256"] = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()

    hit_at = None
    for token in event.answer_aliases:
        if len(token) < 3:
            continue
        m = _boundary(token).search(body)
        if m:
            rec["matched"].append(token)
            if hit_at is None:
                hit_at = m.start()

    rec["body"] = body      # dropped before storage; only classify_render needs it
    if hit_at is not None:
        rec["state"] = FOUND
        lo = max(0, hit_at - EXCERPT_RADIUS)
        rec["excerpt"] = body[lo:hit_at + EXCERPT_RADIUS]
    else:
        rec["state"] = NOT_FOUND
        # Keep the head, so a negative is auditable as a real document rather
        # than a login wall or an error page swallowed quietly.
        rec["excerpt"] = body[:NO_MATCH_HEAD]
    return rec


def probe_origin(event: Event) -> dict[str, Any]:
    """Walk the event's origin URLs until one answers, and grade the bytes.

    Origins are ordered most-crawler-representative first. npm is the case
    that forced this: www.npmjs.com returns 403 to any non-browser user agent,
    including for robots.txt, so the page a crawler would index cannot be
    verified by this harness at all. Falling silently back to the registry
    JSON would answer a *different*, weaker question -- "was the fact public"
    rather than "was the page crawlable" -- so the fallback is taken, labelled,
    and reported separately.

    The stored payload is an excerpt rather than the whole body: the one place
    this repo does not keep verbatim evidence. A full body per event per rung
    is tens of megabytes a day and would make the ledger unclonable. Kept
    instead: status, byte count, a SHA-256 of the exact bytes scanned, and a
    window around the match. Enough to audit a positive, and enough to show a
    negative was a real document.
    """
    out: dict[str, Any] = {
        "kind": "origin-control",
        "state": ERROR,
        "origin_used": "",
        "origin_rank": -1,      # 0 = the canonical crawler-facing page
        "attempts": [],
        "render": RENDER_NONE,
        "content": "",          # the only key the grader reads
        "error": "",
    }
    origins = event.origins or ([event.url] if event.url else [])
    if not origins:
        out["error"] = "event has no origin url"
        return out

    for rank, url in enumerate(origins):
        rec = _attempt(url, event)
        out["attempts"].append(rec)
        if rec["state"] in (FOUND, NOT_FOUND):
            out["state"] = rec["state"]
            out["origin_used"] = url
            out["origin_rank"] = rank
            out["content"] = rec["excerpt"]
            out["render"] = classify_render(rec.pop("body") or "",
                                            event.answer_aliases, rank)
            for a in out["attempts"]:
                a.pop("body", None)     # bodies never reach the ledger
            return out

    # Nothing answered. Report the strongest thing we learned, preferring
    # BLOCKED over ERROR because it is a statement about the origin's policy
    # rather than about our network.
    for a in out["attempts"]:
        a.pop("body", None)
    states = [a["state"] for a in out["attempts"]]
    for preferred in (DISALLOWED, BLOCKED, ERROR):
        if preferred in states:
            out["state"] = preferred
            break
    out["error"] = out["attempts"][0].get("error", "")
    return out


def conditional_recall(
    events: dict[str, Event],
    results: list[Any],
    provider: str,
    mode: str,
    rung: int,
) -> tuple[int, int]:
    """(hits, eligible) for provider at `rung`, over events the origin control
    confirmed were fetchable at that same rung.

    This is the recall number that is genuinely about the provider. Plain
    recall charges it for documents that were not on the web yet.
    """
    fetchable: set[str] = set()
    for r in results:
        if r.provider == "origin" and r.rung == rung and r.verdict == "FRESH":
            fetchable.add(r.event_id)
    # Events whose origin was blocked, disallowed or errored are absent from
    # this set by construction, so they never enter the denominator.
    if not fetchable:
        return 0, 0
    hits = eligible = 0
    for r in results:
        if r.provider != provider or r.mode != mode or r.rung != rung:
            continue
        if r.event_id not in fetchable or r.verdict in ("ERROR", "SKIPPED"):
            continue
        eligible += 1
        if r.verdict == "FRESH":
            hits += 1
    return hits, eligible
