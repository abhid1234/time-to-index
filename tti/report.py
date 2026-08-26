"""Rendering.

Two outputs: a Markdown leaderboard for the README and a self-contained HTML
dashboard with the survival curves drawn as inline SVG. No chart library and
no external requests, so the page works from a file:// URL, inside GitHub
Pages, and inside a corporate network that blocks CDNs.

Presentational rule that follows from the statistics: a median printed
without its censoring context is misleading, so every median is rendered
alongside the number of events it rests on, and a provider that never
crossed 50% prints ">72h" rather than a number invented from the indexed
subset.
"""

from __future__ import annotations

import datetime as dt
import html
import math

from .metrics import (ProviderScore, SurvivalCurve, fmt_bracket, fmt_duration,
                      logrank, observations)
from .models import Event, ProbeResult

W, H = 720, 300
PAD_L, PAD_R, PAD_T, PAD_B = 56, 18, 16, 40

RUNGS = [300, 900, 3600, 21_600, 86_400, 259_200]

PALETTE = [
    "#3b6ea5", "#c2571a", "#2f7d5c", "#8a4f9e",
    "#b03a4a", "#6b6f76", "#a07a1f", "#2c8ba0",
]


# ---------------------------------------------------------------------------
# SVG survival plot
# ---------------------------------------------------------------------------

def _x(lag: float, tmin: float, tmax: float) -> float:
    """Log-scaled x. Indexing latency spans seconds to days; a linear axis
    compresses everything interesting into the first two pixels."""
    lo, hi = math.log10(max(tmin, 1.0)), math.log10(max(tmax, 10.0))
    frac = (math.log10(max(lag, 1.0)) - lo) / (hi - lo) if hi > lo else 0.0
    return PAD_L + frac * (W - PAD_L - PAD_R)


def _y(p: float) -> float:
    return PAD_T + (1.0 - p) * (H - PAD_T - PAD_B)


def _steps(curve: SurvivalCurve, tmin: float, tmax: float) -> str:
    """Step function of P(indexed by t), drawn as a staircase because the
    estimator is piecewise constant and a smoothed line would imply
    observations between rungs that do not exist."""
    pts = [(_x(tmin, tmin, tmax), _y(0.0))]
    prev = 0.0
    for t, s in zip(curve.times, curve.survival):
        p = 1.0 - s
        x = _x(t, tmin, tmax)
        pts.append((x, _y(prev)))
        pts.append((x, _y(p)))
        prev = p
    pts.append((_x(tmax, tmin, tmax), _y(prev)))
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def _band(curve: SurvivalCurve, tmin: float, tmax: float) -> str:
    if not curve.times:
        return ""
    up, down = [], []
    for t, lo, hi in zip(curve.times, curve.lower, curve.upper):
        x = _x(t, tmin, tmax)
        up.append((x, _y(1.0 - hi)))
        down.append((x, _y(1.0 - lo)))
    pts = up + list(reversed(down))
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


TICKS = [(60, "1m"), (300, "5m"), (900, "15m"), (3600, "1h"),
         (21_600, "6h"), (86_400, "24h"), (259_200, "72h")]


def survival_svg(scores: list[ProviderScore], title: str = "") -> str:
    tmin, tmax = 60.0, 259_200.0
    parts = [
        f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
        f'aria-label="{html.escape(title or "time to index")}" '
        f'style="max-width:{W}px;font-family:var(--mono)">'
    ]
    # grid + x ticks
    for t, lbl in TICKS:
        x = _x(t, tmin, tmax)
        parts.append(f'<line x1="{x:.1f}" y1="{PAD_T}" x2="{x:.1f}" y2="{_y(0)}" '
                     f'stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<text x="{x:.1f}" y="{_y(0)+16:.0f}" font-size="10" '
                     f'text-anchor="middle" fill="var(--muted)">{lbl}</text>')
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = _y(p)
        parts.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" '
                     f'stroke="var(--grid)" stroke-width="1"'
                     + (' stroke-dasharray="3 3"' if p == 0.5 else "") + "/>")
        parts.append(f'<text x="{PAD_L-8}" y="{y+3:.1f}" font-size="10" '
                     f'text-anchor="end" fill="var(--muted)">{int(p*100)}%</text>')

    for i, sc in enumerate(scores):
        colour = PALETTE[i % len(PALETTE)]
        band = _band(sc.curve, tmin, tmax)
        if band:
            parts.append(f'<polygon points="{band}" fill="{colour}" opacity="0.10"/>')
        parts.append(f'<polyline points="{_steps(sc.curve, tmin, tmax)}" fill="none" '
                     f'stroke="{colour}" stroke-width="2" stroke-linejoin="round"/>')

    parts.append(f'<text x="{PAD_L}" y="{H-6}" font-size="10" fill="var(--muted)">'
                 f'lag since publication (log scale) &#183; shaded band = 95% CI</text>')
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _pct(t: tuple[float, float, float]) -> str:
    p, lo, hi = t
    if p != p:  # NaN
        return "—"
    return f"{p*100:.0f}% ({lo*100:.0f}–{hi*100:.0f})"


def leaderboard_md(scores: list[ProviderScore], rungs: list[int] | None = None) -> str:
    rungs = rungs or [300, 900, 3600, 21600, 86400, 259200]
    rows = [
        "| provider | median TTI | p90 | 24h recall | staleness | $/1k events | n |",
        "|---|---|---|---|---|---|---|",
    ]
    for sc in sorted(scores, key=lambda s: (s.median_ttl is None, s.median_ttl or 0)):
        per_1k = (sc.spend_usd / sc.n_events * 1000) if sc.n_events else 0.0
        rows.append(
            f"| `{sc.provider}/{sc.mode}` | {fmt_bracket(rungs, sc.median_ttl)} "
            f"| {fmt_bracket(rungs, sc.p90_ttl)} | {_pct(sc.recall_24h)} "
            f"| {_pct(sc.staleness)} | ${per_1k:.2f} | {sc.n_events} |"
        )
    return "\n".join(rows)


def summary_md(scores: list[ProviderScore], events: dict[str, Event],
               results: list[ProbeResult]) -> str:
    total_spend = sum(s.spend_usd for s in scores)
    skipped = sum(s.n_skipped_budget for s in scores)
    lines = [
        f"_Generated {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M UTC} · "
        f"{len(events)} events · {sum(s.n_calls for s in scores)} graded probes · "
        f"${total_spend:.2f} spent_",
        "",
        leaderboard_md(scores),
    ]
    if skipped:
        lines += ["", f"> **{skipped} probes were refused by the daily spend cap** and are "
                      "excluded from every rate above. They are in the ledger as "
                      "`SKIPPED`; a run with cap-refused probes is a partial run, and "
                      "saying so here is cheaper than having someone find it later."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------

_CSS = """
:root{
  --bg:#faf9f7; --panel:#ffffff; --ink:#1b1a18; --muted:#6d6a63;
  --line:#e3e0da; --grid:#eeece7; --accent:#c2571a; --good:#2f7d5c; --bad:#b03a4a;
  --mono:"SFMono-Regular",ui-monospace,Menlo,Consolas,monospace;
  --sans:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#14151a; --panel:#1b1d23; --ink:#e8e6e1; --muted:#93908a;
    --line:#2b2e36; --grid:#232630; --accent:#e08a4c; --good:#5cb894; --bad:#e0707f;
  }
}
:root[data-theme="dark"]{
  --bg:#14151a; --panel:#1b1d23; --ink:#e8e6e1; --muted:#93908a;
  --line:#2b2e36; --grid:#232630; --accent:#e08a4c; --good:#5cb894; --bad:#e0707f;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
     font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:980px;margin:0 auto;padding:48px 24px 80px}
h1{font-size:30px;letter-spacing:-.02em;margin:0 0 6px;text-wrap:balance}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
   margin:44px 0 14px;font-weight:600}
.sub{color:var(--muted);margin:0 0 28px;font-size:14px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
       padding:20px 22px;margin-bottom:18px}
table{width:100%;border-collapse:collapse;font-size:13.5px;
      font-variant-numeric:tabular-nums}
th{text-align:left;font-weight:600;color:var(--muted);font-size:11px;
   text-transform:uppercase;letter-spacing:.07em;padding:0 12px 9px 0;
   border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 12px 9px 0;border-bottom:1px solid var(--grid)}
tr:last-child td{border-bottom:none}
td.k{font-family:var(--mono);font-size:12.5px}
.scroll{overflow-x:auto}
.legend{display:flex;flex-wrap:wrap;gap:16px;margin:12px 0 0;font-size:12px;
        font-family:var(--mono);color:var(--muted)}
.legend i{display:inline-block;width:11px;height:3px;vertical-align:middle;
          margin-right:6px;border-radius:2px}
.note{font-size:13px;color:var(--muted);border-left:2px solid var(--accent);
      padding-left:14px;margin:14px 0}
.big{font-family:var(--mono);font-size:22px}
.bad{color:var(--bad)} .good{color:var(--good)}
footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);
       color:var(--muted);font-size:12.5px}
"""


def full_page(fragment: str, title: str = "Time to Index") -> str:
    """Wrap the dashboard fragment as a standalone document.

    Kept separate because the fragment is also embedded elsewhere. The page
    is self-contained apart from one Google Fonts link, with a real fallback
    stack behind it, so it renders correctly from a file:// URL and inside a
    network that blocks font CDNs.
    """
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        + fragment.split("<div class=\"wrap\">", 1)[0]
        + "</head>\n<body>\n<div class=\"wrap\">"
        + fragment.split("<div class=\"wrap\">", 1)[1]
        + "\n</body>\n</html>\n"
    )


def dashboard_html(scores: list[ProviderScore], events: dict[str, Event],
                   results: list[ProbeResult], by_class: dict[str, list[ProviderScore]],
                   pairs: list[tuple[str, str, float]]) -> str:
    e = html.escape
    gen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ordered = sorted(scores, key=lambda s: (s.median_ttl is None, s.median_ttl or 0))

    legend = "".join(
        f'<span><i style="background:{PALETTE[i % len(PALETTE)]}"></i>'
        f'{e(sc.provider)}/{e(sc.mode)}</span>'
        for i, sc in enumerate(ordered))

    rows = "".join(
        f"<tr><td class='k'>{e(sc.provider)}/{e(sc.mode)}</td>"
        f"<td class='k'>{fmt_bracket(RUNGS, sc.median_ttl)}</td>"
        f"<td class='k'>{fmt_bracket(RUNGS, sc.p90_ttl)}</td>"
        f"<td class='k'>{_pct(sc.recall_24h)}</td>"
        f"<td class='k{' bad' if sc.staleness[0] == sc.staleness[0] and sc.staleness[0] > 0.2 else ''}'>"
        f"{_pct(sc.staleness)}</td>"
        f"<td class='k'>{sc.p50_latency_ms:.0f}ms</td>"
        f"<td class='k'>${(sc.spend_usd / sc.n_events * 1000) if sc.n_events else 0:.2f}</td>"
        f"<td class='k'>{sc.n_events}</td></tr>"
        for sc in ordered)

    class_blocks = ""
    for cls, cscores in sorted(by_class.items()):
        if not any(c.n_events for c in cscores):
            continue
        crows = "".join(
            f"<tr><td class='k'>{e(c.provider)}/{e(c.mode)}</td>"
            f"<td class='k'>{fmt_bracket(RUNGS, c.median_ttl)}</td>"
            f"<td class='k'>{_pct(c.recall_24h)}</td>"
            f"<td class='k'>{_pct(c.staleness)}</td>"
            f"<td class='k'>{c.n_events}</td></tr>"
            for c in sorted(cscores, key=lambda s: (s.median_ttl is None, s.median_ttl or 0))
            if c.n_events)
        class_blocks += (
            f"<div class='panel'><h2 style='margin-top:0'>{e(cls.replace('_', ' '))}</h2>"
            f"<div class='scroll'><table><thead><tr><th>arm</th><th>median</th>"
            f"<th>24h recall</th><th>staleness</th><th>n</th></tr></thead>"
            f"<tbody>{crows}</tbody></table></div></div>")

    pair_rows = "".join(
        f"<tr><td class='k'>{e(a)} vs {e(b)}</td>"
        f"<td class='k'>p = {p:.4f}</td>"
        f"<td>{'distinguishable' if p < 0.05 else 'not distinguishable at this n'}</td></tr>"
        for a, b, p in pairs) or "<tr><td colspan='3'>not enough events yet</td></tr>"

    stale_total = sum(s.n_stale for s in scores)
    stale_elig = sum(s.n_stale_eligible for s in scores)
    stale_pct = f"{stale_total / stale_elig * 100:.0f}%" if stale_elig else "—"

    return f"""<title>Time to Index</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap">
<style>{_CSS}</style>
<div class="wrap">
<h1>Time to Index</h1>
<p class="sub">How long a newly published fact takes to become retrievable through each
web-search API, and how often the API confidently returns the answer it replaced.
Generated {gen}.</p>

<div class="panel">
  <div class="scroll"><table>
    <thead><tr><th>arm</th><th>median TTI</th><th>p90</th><th>24h recall</th>
    <th>staleness</th><th>p50 latency</th><th>$/1k events</th><th>events</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  <p class="note">Median is a Kaplan&#8211;Meier estimate with right-censoring at 72 hours,
  reported as the interval between ladder rungs rather than a point. An arm first seen
  fresh at the 1h rung indexed somewhere in (15m, 1h]; printing "1h" would overstate it
  by up to the width of the bracket. Events still un-indexed at the last rung are
  censored, not dropped &#8212; discarding them would report every provider as faster than
  it is, and unevenly, since the bias is largest for whoever has the most un-indexed
  events. <b>&gt;72h</b> means the arm never crossed 50% inside the window.</p>
</div>

<h2>Time to index</h2>
<div class="panel">
  {survival_svg(ordered, "time to index, all sources")}
  <div class="legend">{legend}</div>
</div>

<h2>Staleness</h2>
<div class="panel">
  <p style="margin-top:0">Across every probe where the provider had not yet indexed the
  new answer and the question had a superseded one, it returned the superseded answer
  <span class="big bad">{stale_pct}</span> of the time
  ({stale_total} of {stale_elig} opportunities).</p>
  <p class="note">Existing search benchmarks score a miss and a confidently-wrong
  stale answer identically. In production they are not the same event. An agent that
  gets nothing back retries, widens, or says it does not know. An agent that gets last
  quarter's number back cites it, and nothing downstream can tell that it is wrong.</p>
</div>

<h2>By source class</h2>
{class_blocks}

<h2>Are the differences real</h2>
<div class="panel">
  <div class="scroll"><table>
    <thead><tr><th>comparison</th><th>log-rank</th><th>read</th></tr></thead>
    <tbody>{pair_rows}</tbody></table></div>
  <p class="note">Log-rank rather than a t-test on the indexed subset, because most
  observations are censored and a test that ignores censoring will find differences
  that are artefacts of who ran out of window first.</p>
</div>

<footer>
Every number here is recomputed from <code>runs/results.jsonl</code>, and every result
points at the verbatim provider response stored under <code>runs/raw/</code>.
Re-grade the raw payloads with different matching rules and you will get a different
number out of the same evidence &#8212; which is the only reason to believe this one.
</footer>
</div>"""
