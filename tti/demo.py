"""Synthetic run, for looking at the instrument without paying for one.

Every arm here is named `provider-a`, `provider-b`, `provider-c`. None of
them is a real product and the numbers are drawn from a seeded random
generator, so a screenshot of the demo page cannot be mistaken for a finding
about anybody's index. The demo exists to answer one question -- does the
estimator behave sensibly on data with known ground truth -- and it is wired
so that it writes to `docs/demo.html` and never to `docs/index.html`.

The generator is also a check on the statistics: it draws indexing latencies
from log-normal distributions with parameters the test knows, and the
recovered Kaplan-Meier medians should land near them. If they do not, the
estimator is wrong, and that is worth finding out before publishing a number
about a real vendor.
"""

from __future__ import annotations

import math
import pathlib
import random
import time
import zlib

from . import report
from .ledger import Ledger
from .metrics import fmt_duration, fmt_pair, score, staleness_by_rung
from .models import ABSENT, FRESH, STALE, Event, ProbeResult

# (arm, median latency in seconds, sigma, ceiling on ever indexing,
#  probability of returning the superseded answer while un-indexed)
PROFILES = [
    ("provider-a", "fast",  420.0,   1.1, 0.97, 0.55),
    ("provider-b", "base",  5_400.0, 1.4, 0.93, 0.71),
    ("provider-c", "base",  64_800.0, 1.6, 0.78, 0.44),
]

# The shape of text each synthetic arm serves: which response key it uses and
# roughly how many characters per result. Real arms differ by an order of
# magnitude here (an excerpt API honours max_chars_per_result; a snippet API
# returns ~150 regardless). The demo writes a real payload for every provider
# probe, in that shape, and grades it with the real grader -- so the text
# column, the sensitivity panel and the snippet-window variant on the demo
# page are produced by the same code path a live run uses, not by fiat.
TEXT_SHAPE = {"provider-a": ("excerpts", 1_380),
              "provider-b": ("snippet", 150),
              "provider-c": ("text", 620)}

# Digit-free filler, so nothing version-shaped appears in a payload by
# accident and the verdict the generator drew is the verdict the grader finds.
_WORDS = ["release", "notes", "changelog", "package", "install", "upgrade", "fixed", "added", "removed", "documentation", "client", "server", "build", "tests", "pinned", "dependency", "migration", "breaking", "deprecated", "stable", "preview", "maintainers", "thanks", "contributors"]

CLASSES = [
    ("package_registry", "npm", True, 40),
    ("code_release", "github_release", True, 22),
    ("regulatory_filing", "edgar", True, 14),
    ("preprint", "arxiv", False, 18),
    ("gov_publication", "federal_register", False, 12),
]


# Presence of this file in a run directory means the ledger was produced by
# the generator below, not by probing anything.
DEMO_MARKER = "SYNTHETIC"


def generate(run_dir: pathlib.Path, ladder: list[int], seed: int = 7,
             payloads: bool = True
             ) -> tuple[Ledger, dict[str, list[float]]]:
    rng = random.Random(seed)
    led = Ledger(run_dir)
    now = time.time()

    # Mark the run as synthetic. Pre-registration is a claim about a
    # measurement of somebody's product, and this run measures a generator
    # whose answers are already known. Without the marker the arms here read
    # as five undeclared providers and the five real ones read as having
    # failed everywhere -- both true statements about the ledger, and both
    # nonsense as statements about the world.
    led.root.mkdir(parents=True, exist_ok=True)
    (led.root / DEMO_MARKER).write_text(
        "Synthetic run from `tti demo`. Not a measurement of any product.\n",
        encoding="utf-8")

    events: list[Event] = []
    for source_class, source, has_predecessor, n in CLASSES:
        for i in range(n):
            published = now - rng.uniform(300_000, 900_000)
            major, minor = rng.randint(1, 9), rng.randint(0, 40)
            events.append(Event(
                source=source, source_class=source_class,
                subject=f"{source}-subject-{i}",
                published_at=published, discovered_at=published + rng.uniform(5, 200),
                question=f"synthetic question {source}-{i}",
                answer=f"{major}.{minor}.{rng.randint(1, 9)}",
                predecessor=(f"{major}.{minor}.0" if has_predecessor else None),
            ))
    led.add_events(events)

    results: list[ProbeResult] = []
    truth: dict[str, list[float]] = {}   # arm -> the latencies actually drawn

    # The origin control. Most facts are on their own page immediately; a
    # minority of origins refuse a non-browser client, and a few pages never
    # contain the fact at all because they render it client-side. Those
    # proportions are invented, but the *shape* is what the real arm produced
    # on live pages during development, and the panel exists to make that
    # shape visible rather than to assert the numbers.
    origin_state: dict[str, str] = {}
    for ev in events:
        roll = rng.random()
        state = ("blocked" if roll < 0.14 else
                 "not_found" if roll < 0.20 else "found")
        origin_state[ev.event_id] = state
        # Registries and filings are server-rendered; a slice of pages put the
        # fact only in a data blob. Invented proportions, real shape.
        rclass = rng.choices(
            ["server_html", "embedded_json", "api_only"], weights=[62, 26, 12])[0]
        appears_at = rng.choice([0, 300, 300, 300, 900])
        for rung in ladder:
            if state == "blocked":
                results.append(_r(ev, "origin", "direct", rung, "ERROR", 0.0, now,
                                  note="origin:blocked"))
                continue
            if state == "not_found":
                results.append(_r(ev, "origin", "direct", rung, ABSENT, 0.0, now,
                                  note="origin:not_found"))
                continue
            if rung >= appears_at:
                results.append(_r(ev, "origin", "direct", rung, FRESH, 0.0, now,
                                  note=f"origin:found rank=0 render={rclass}",
                                  render=rclass))
                break
            results.append(_r(ev, "origin", "direct", rung, ABSENT, 0.0, now,
                              note="origin:not_found"))
    for provider, mode, median, sigma, ceiling, stale_rate in PROFILES:
        mu = math.log(median)
        drawn: list[float] = []
        for ev in events:
            # Regulatory filings are slower to propagate everywhere; preprints
            # faster. The multiplier is the same for every arm, so the demo
            # does not bake in a ranking that the estimator then "discovers".
            mult = {"regulatory_filing": 2.4, "preprint": 0.6,
                    "gov_publication": 1.5}.get(ev.source_class, 1.0)
            indexes = rng.random() < ceiling
            t_index = rng.lognormvariate(mu, sigma) * mult if indexes else float("inf")
            drawn.append(t_index)

            for rung in ladder:
                if t_index <= rung:
                    verdict, cost = FRESH, 0.005
                    results.append(_r(ev, provider, mode, rung, verdict, cost, now))
                    break
                stale = ev.predecessor and rng.random() < stale_rate
                results.append(_r(ev, provider, mode, rung,
                                  STALE if stale else ABSENT, 0.005, now))
        truth[f"{provider}/{mode}"] = drawn
    if payloads:
        _attach_payloads(led, events, results)
    led.add_results(results)
    return led, truth


def true_median(latencies: list[float]) -> float:
    """Median of the drawn latencies, counting never-indexed as infinite.

    This is the number the estimator has to recover, and it is not the
    log-normal median the profile was configured with: a ceiling below 1.0
    mixes in a point mass at infinity, which pushes the median right. Getting
    that distinction wrong is exactly the kind of error a synthetic check is
    for.
    """
    xs = sorted(latencies)
    mid = xs[len(xs) // 2]
    return mid


def _r(ev: Event, provider: str, mode: str, rung: int, verdict: str,
       cost: float, now: float, note: str = "", render: str = "") -> ProbeResult:
    return ProbeResult(
        probe_id=f"{ev.event_id}-{provider}-{rung}", event_id=ev.event_id,
        provider=provider, mode=mode, rung=rung,
        requested_at=ev.published_at + rung, lag=float(rung), verdict=verdict,
        # zlib.crc32, not hash(): Python randomises string hashing per
        # process, so the previous version produced different latencies on
        # every run of a demo that advertises itself as seeded.
        latency_ms=random.Random(
            zlib.crc32(f"{provider}:{mode}:{rung}".encode())).randint(300, 2400),
        matched_stale=[ev.predecessor] if verdict == STALE and ev.predecessor else [],
        matched_fresh=[ev.answer] if verdict == FRESH else [],
        n_results=5, cost_usd=cost, raw_ref="", note=note, render=render)


def _payload(ev: Event, r: ProbeResult) -> dict:
    """A provider response that grades to the verdict the generator drew.

    The fact sits at a seeded position inside one result's text: early or
    late in a long excerpt, wherever it lands in a short snippet. That is the
    property the `snippet-window` sensitivity variant is sensitive to, and it
    is why the demo can show that variant doing something.
    """
    key, size = TEXT_SHAPE[r.provider]
    rng = random.Random(zlib.crc32(f"payload:{r.probe_id}".encode()))

    def filler(n: int) -> str:
        out: list[str] = []
        length = 0
        while length < n:
            w = rng.choice(_WORDS)
            out.append(w)
            length += len(w) + 1
        return " ".join(out)[:n]

    token = ev.answer if r.verdict == FRESH else (ev.predecessor if r.verdict == STALE else None)
    hit = rng.randrange(5) if token else -1
    results = []
    for i in range(5):
        body = filler(size + rng.randint(-8, 8))
        if i == hit:
            pos = rng.randint(0, max(0, len(body) - 24))
            body = body[:pos] + f" version {token} " + body[pos:]
        results.append({"url": f"https://example.invalid/{ev.subject}/{i}",
                        "title": f"{ev.subject} — {key}",
                        key: [body] if key == "excerpts" else body})
    return {"results": results}


def _attach_payloads(led: Ledger, events: list[Event], results: list[ProbeResult]) -> None:
    from .grader import grade
    by_id = {e.event_id: e for e in events}
    for r in results:
        if r.provider == "origin" or r.verdict in ("ERROR", "SKIPPED"):
            continue
        ev = by_id[r.event_id]
        payload = _payload(ev, r)
        verdict, fresh, stale, chars = grade(ev, payload)
        if verdict != r.verdict:   # the generator and the grader must agree, by construction
            raise RuntimeError(f"demo payload for {r.probe_id} graded {verdict}, drew {r.verdict}")
        r.raw_ref = led.store_raw(r.provider, r.probe_id, payload)
        r.chars, r.matched_fresh, r.matched_stale = chars, fresh, stale


BANNER = """
<div style="background:#7a2530;color:#fff;padding:14px 18px;border-radius:8px;
     margin:0 0 26px;font-size:13.5px;line-height:1.5">
<b>This page is synthetic.</b> Every arm is a made-up provider
(<code>provider-a/b/c</code>) with latencies drawn from a seeded generator. It exists
to show what the instrument renders and to check that the estimator recovers latencies
it was given. No real search API was called to produce anything on this page, and
nothing here is a finding about any product. Real runs are published at
<code>docs/index.html</code>.
</div>
"""


def render(run_dir: pathlib.Path, out: pathlib.Path, ladder: list[int]) -> str:
    led, truth = generate(run_dir, ladder)
    events, results = led.events(), led.results()
    arms = sorted({(r.provider, r.mode) for r in results if r.provider != "origin"})
    scores = [score(events, results, p, m, bootstrap=400) for p, m in arms]
    classes = sorted({e.source_class for e in events.values()})
    by_class = {c: [score(events, results, p, m, c) for p, m in arms] for c in classes}

    # Same family function as `tti report` and `tti power`: the demo's own
    # copy of this loop skipped the Holm step, and the page printed a column
    # of dashes under "p adjusted" beside verdicts it said were adjusted.
    from .power import pairwise_family, raw_pairs
    powers = pairwise_family(events, results, arms, 15.0)
    pairs = raw_pairs(powers)
    stale_series = [(f"{sc.provider}/{sc.mode}",
                     staleness_by_rung(events, results, sc.provider, sc.mode))
                    for sc in sorted(scores, key=lambda s: (s.median_ttl is None,
                                                            s.median_ttl or 0))]
    from .metrics import recall_by_render
    render_table = {f"{sc.provider}/{sc.mode}":
                    recall_by_render(events, results, sc.provider, sc.mode)
                    for sc in scores}
    render_table = {k: v for k, v in render_table.items() if v}
    # The demo stores a payload per provider probe, so the sensitivity pass
    # runs for real here rather than rendering "not evaluated".
    from . import sensitivity
    sens_rows = sensitivity.run(led)
    html = report.dashboard_html(scores, events, results, by_class, pairs, powers,
                                 stale_series, sens_rows, render_table or None,
                                 prereg_panel=report.prereg_panel_html("synthetic"))
    html = html.replace("<h1>Time to Index</h1>", "<h1>Time to Index</h1>" + BANNER)
    html = html.replace("<title>Time to Index</title>",
                        "<title>Time to Index — synthetic demo</title>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.full_page(html, "Time to Index — synthetic demo"),
                   encoding="utf-8")
    # Fragment copy, for embedding somewhere that supplies its own document
    # shell.
    out.with_suffix(".fragment.html").write_text(html, encoding="utf-8")

    lines = []
    for sc in sorted(scores, key=lambda s: (s.median_ttl is None, s.median_ttl or 0)):
        actual = true_median(truth[f"{sc.provider}/{sc.mode}"])
        lo, hi = sc.median_bracket
        ok = (lo or 0) < actual <= (hi if hi is not None else float("inf"))
        lines.append(
            f"  {'OK ' if ok else 'MISS'} {sc.provider}/{sc.mode}: "
            f"estimated {fmt_pair(sc.median_bracket):>10s}  "
            f"true {fmt_duration(actual) if actual != float('inf') else 'never':>7s}  "
            f"(n={sc.n_events}, indexed {sc.n_indexed})")
    return "\n".join(lines)
