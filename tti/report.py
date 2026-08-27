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

from .metrics import (
    ProviderScore,
    SurvivalCurve,
    fmt_bracket,
    fmt_duration,
    fmt_pair,
)
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
    for t, s in zip(curve.times, curve.survival, strict=True):
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
    for t, lo, hi in zip(curve.times, curve.lower, curve.upper, strict=True):
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


def staleness_svg(series: list[tuple[str, list[tuple[int, float, int]]]],
                  rungs: list[int]) -> str:
    """Staleness against lag, one line per arm.

    Plotted on the same log-x as the survival chart so the two read as one
    system. The y-axis is fixed to [0, 1] rather than scaled to the data:
    auto-scaling a rate makes a 4% staleness look like a crisis and is the
    most common way a chart lies without anyone deciding to.
    """
    if not any(pts for _, pts in series):
        return ""
    tmin, tmax = float(rungs[0]), float(rungs[-1])
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
             f'aria-label="staleness by lag" '
             f'style="max-width:{W}px;font-family:var(--mono)">']
    for t, lbl in TICKS:
        if not (tmin <= t <= tmax):
            continue
        x = _x(t, tmin, tmax)
        parts.append(f'<line x1="{x:.1f}" y1="{PAD_T}" x2="{x:.1f}" y2="{_y(0)}" '
                     f'stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<text x="{x:.1f}" y="{_y(0)+16:.0f}" font-size="10" '
                     f'text-anchor="middle" fill="var(--muted)">{lbl}</text>')
    for pv in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = _y(pv)
        parts.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" '
                     f'stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<text x="{PAD_L-8}" y="{y+3:.1f}" font-size="10" '
                     f'text-anchor="end" fill="var(--muted)">{int(pv*100)}%</text>')

    for i, (_name, pts) in enumerate(series):
        if not pts:
            continue
        colour = PALETTE[i % len(PALETTE)]
        coords = " ".join(f"{_x(float(r), tmin, tmax):.1f},{_y(rate):.1f}"
                          for r, rate, _ in pts)
        parts.append(f'<polyline points="{coords}" fill="none" stroke="{colour}" '
                     f'stroke-width="2" stroke-linejoin="round"/>')
        for r, rate, _n in pts:
            parts.append(f'<circle cx="{_x(float(r), tmin, tmax):.1f}" '
                         f'cy="{_y(rate):.1f}" r="2.5" fill="{colour}"/>')
    parts.append(f'<text x="{PAD_L}" y="{H-6}" font-size="10" fill="var(--muted)">'
                 f'lag since publication (log scale) &#183; share of not-yet-fresh '
                 f'probes that returned the superseded answer</text>')
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _ci(sc: ProviderScore) -> str:
    lo, hi = sc.median_ci
    if lo is None or hi is None:
        return f"never reached in {sc.median_unreached*100:.0f}% of resamples" \
            if sc.median_unreached >= 0.999 else "—"
    span = fmt_duration(lo) if lo == hi else f"{fmt_duration(lo)}–{fmt_duration(hi)}"
    if sc.median_unreached > 0.02:
        span += f" · unreached in {sc.median_unreached*100:.0f}%"
    return span


def _cpf(v: float) -> str:
    if not isinstance(v, (int, float)) or v != v:
        return "—"
    if v == float("inf"):
        return "no answers"
    if v < 0:
        return "—"      # not a price
    return f"${v*1000:.2f}"


def _pct(t: tuple[float, float, float]) -> str:
    p, lo, hi = t
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in t):
        return "—"
    # Clamp the interval to [0, 1]. Wilson stays inside it by construction,
    # but a rendered "0% (-10–150)" is worse than a clamped one either way,
    # and this is the last place to catch it.
    lo, hi = max(0.0, min(1.0, lo)), max(0.0, min(1.0, hi))
    return f"{p*100:.0f}% ({lo*100:.0f}–{hi*100:.0f})"


def leaderboard_md(scores: list[ProviderScore], rungs: list[int] | None = None) -> str:
    rungs = rungs or [300, 900, 3600, 21600, 86400, 259200]
    rows = [
        "| provider | median TTI | p90 | 24h recall | staleness "
        "| $/1k events | $/1k fresh answers | n |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sc in sorted(scores, key=lambda s: (s.median_ttl is None, s.median_ttl or 0)):
        per_1k = (sc.spend_usd / sc.n_events * 1000) if sc.n_events else 0.0
        rows.append(
            f"| `{sc.provider}/{sc.mode}` | {fmt_pair(sc.median_bracket)} "
            f"| {fmt_pair(sc.p90_bracket)} | {_pct(sc.recall_24h)} "
            f"| {_pct(sc.staleness)} | ${per_1k:.2f} "
            f"| {_cpf(sc.cost_per_fresh_24h)} | {sc.n_events} |"
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


def placeholder_page() -> str:
    """The page GitHub Pages serves before any real run.

    A results URL that 404s reads as abandoned; a results URL that shows a
    template reads as a finding. Neither is true here, so this says which it
    is. `tti report` overwrites this file on the first real run.
    """
    return full_page(f"""<title>Time to Index</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap">
<style>{_CSS}</style>
<div class="wrap">
<h1>Time to Index</h1>
<p class="sub">How long a newly published fact takes to become retrievable through each
web-search API, and how often the API confidently returns the answer it replaced.</p>

<div class="panel">
  <p style="margin-top:0"><b>No run has happened yet.</b> Nothing on this site is a
  finding about any product. This page is replaced by measured results the first time
  the harness runs against live provider APIs.</p>
  <p class="note">Said plainly because the alternatives are worse. A results URL that
  404s reads as abandoned. A results URL showing a populated template reads as a
  finding. Neither is true.</p>
</div>

<h2>In the meantime</h2>
<div class="panel">
  <p style="margin-top:0"><a href="demo.html">The synthetic demo</a> &#8212; what the
  instrument renders, with made-up providers whose latencies come from a seeded
  generator. It exists to show the shape and to check that the estimator recovers
  latencies it was never shown. It is labelled on the page itself.</p>
  <p><a href="METHODOLOGY.md">Methodology</a> &#8212; ground truth, the probe ladder,
  grading, the origin control, and the statistics. Including a section on everything
  that could make the numbers wrong.</p>
  <p><a href="INTEGRATION-NOTES.md">Integration notes</a> &#8212; the friction of wiring
  up each source and provider, split into what was observed and what is still open.</p>
</div>

<footer>
When results land they are published regardless of which provider wins, including if
the one I find most interesting comes last, and including if the differences turn out
to sit inside the noise. The raw payloads ship either way.
</footer>
</div>""")


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


def _overstatement(sc: ProviderScore) -> str:
    lo, hi = sc.median_bracket
    km = sc.median_ttl
    if km is None or hi is None or hi <= 0:
        return "—"
    # KM reports `km`; the NPMLE says the truth is somewhere in (lo, hi].
    # The largest defensible claim is the gap to the bracket's lower edge.
    gap = km - (lo or 0.0)
    if gap <= 0:
        return "none"
    return f"up to {fmt_duration(gap)}"


def dashboard_html(scores: list[ProviderScore], events: dict[str, Event],
                   results: list[ProbeResult], by_class: dict[str, list[ProviderScore]],
                   pairs: list[tuple[str, str, float]],
                   powers: list = (),
                   stale_series: list = (),
                   sensitivity_rows: list = (),
                   render_table: dict | None = None) -> str:
    e = html.escape
    gen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ordered = sorted(scores, key=lambda s: (s.median_ttl is None, s.median_ttl or 0))

    any_phrasing = any(s.n_phrasings_asked for s in scores)
    ph_head = ("<th>phrasing<br><span style='text-transform:none;letter-spacing:0'>"
               "agreement</span></th>" if any_phrasing else "")
    ph_note = ("" if not any_phrasing else
               "<p class='note'>Phrasing agreement asks the same event, at the same rung, "
               "more than one way, and reports the share of wordings that came back fresh "
               "among events where at least one did. An arm at 100% is phrasing-insensitive "
               "here. A low number means it <i>has</i> the document and does not reliably "
               "surface it &#8212; a different failure from not having it, and one an agent hits "
               "far more often than a benchmark does, because an agent asks whatever its "
               "planner produced that turn rather than what a template would write.</p>")

    dropped = [(f"{s.provider}/{s.mode}", s.npmle.dropped) for s in scores
               if s.npmle.dropped]
    drop_note = ("" if not dropped else
                 "<p class='note' style='border-color:var(--bad)'><b>"
                 + e(", ".join(f"{a}: {n}" for a, n in dropped))
                 + "</b> observation(s) matched no support interval and were "
                   "excluded from the fit. That shrinks the denominator of every "
                   "rate on this row, so it is stated rather than left as an "
                   "unexplained gap.</p>")

    non_converged = [f"{s.provider}/{s.mode}" for s in scores
                     if s.npmle.n and not s.npmle.converged]
    converge_note = ("" if not non_converged else
                     "<p class='note' style='border-color:var(--bad)'><b>The estimator did "
                     "not converge</b> for " + e(", ".join(non_converged)) + ". Their medians "
                     "and intervals are not trustworthy and should not be read as results. "
                     "This is surfaced rather than swallowed because a non-converged fit "
                     "still renders a plausible-looking number.</p>")

    legend = "".join(
        f'<span><i style="background:{PALETTE[i % len(PALETTE)]}"></i>'
        f'{e(sc.provider)}/{e(sc.mode)}</span>'
        for i, sc in enumerate(ordered))

    rows = "".join(
        (f"<tr><td class='k'>{e(sc.provider)}/{e(sc.mode)}</td>"
        f"<td class='k'>{fmt_pair(sc.median_bracket)}</td>"
        f"<td class='k'>{_ci(sc)}</td>"
        f"<td class='k'>{fmt_pair(sc.p90_bracket)}</td>"
        f"<td class='k'>{_pct(sc.recall_24h)}</td>"
        f"<td class='k'>{_pct(sc.conditional_recall_24h)}</td>"
        f"<td class='k{' bad' if sc.staleness[0] == sc.staleness[0] and sc.staleness[0] > 0.2 else ''}'>"
        f"{_pct(sc.staleness)}</td>"
        + (f"<td class='k'>{_pct(sc.phrasing_agreement)}</td>" if any_phrasing else "")
        + f"<td class='k'>{sc.p50_latency_ms:.0f}ms</td>"
        f"<td class='k'>${(sc.spend_usd / sc.n_events * 1000) if sc.n_events else 0:.2f}</td>"
        + f"<td class='k'>{_cpf(sc.cost_per_fresh_24h)}</td>"
        + f"<td class='k'>{sc.n_events}</td></tr>")
        for sc in ordered)

    class_blocks = ""
    for cls, cscores in sorted(by_class.items()):
        if not any(c.n_events for c in cscores):
            continue
        crows = "".join(
            f"<tr><td class='k'>{e(c.provider)}/{e(c.mode)}</td>"
            f"<td class='k'>{fmt_pair(c.median_bracket)}</td>"
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

    def _pw(r) -> str:
        cells = [
            f"<td class='k'>{e(r.a)} vs {e(r.b)}</td>",
            f"<td class='k'>{'—' if r.hazard_ratio != r.hazard_ratio else f'{r.hazard_ratio:.2f}'}</td>",
            f"<td class='k'>{r.events_observed}</td>",
            f"<td class='k'>{'—' if r.p_value != r.p_value else f'{r.p_value:.4f}'}</td>",
            f"<td class='k'>{'—' if r.power_now != r.power_now else f'{r.power_now*100:.0f}%'}</td>",
        ]
        if r.verdict == "distinguishable":
            tail = "<td class='good'>distinguishable</td>"
        elif r.events_needed and r.days_needed:
            tail = (f"<td>{e(r.verdict)} — needs ~{r.events_needed:.0f} more events "
                    f"(~{r.days_needed:.0f}d)</td>")
        else:
            tail = f"<td>{e(r.verdict)}</td>"
        return "<tr>" + "".join(cells) + tail + "</tr>"

    pair_rows = "".join(_pw(r) for r in powers) or (
        "".join(
            f"<tr><td class='k'>{e(a)} vs {e(b)}</td><td colspan='4' class='k'>p = {p:.4f}</td>"
            f"<td>{'distinguishable' if p < 0.05 else 'not distinguishable at this n'}</td></tr>"
            for a, b, p in pairs)
        or "<tr><td colspan='6'>not enough events yet</td></tr>")

    km_rows = "".join(
        f"<tr><td class='k'>{e(sc.provider)}/{e(sc.mode)}</td>"
        f"<td class='k'>{fmt_pair(sc.median_bracket)}</td>"
        f"<td class='k'>{fmt_bracket(RUNGS, sc.median_ttl)}</td>"
        f"<td class='k'>{_overstatement(sc)}</td></tr>"
        for sc in ordered)

    origin_counts: dict[str, int] = {}
    for r in results:
        if r.provider == "origin":
            key = (r.note or "origin:unknown").split()[0].replace("origin:", "")
            origin_counts[key] = origin_counts.get(key, 0) + 1
    MEANING = {
        "found": "fetchable, and the answer was in the served bytes",
        "not_found": "page fetched, answer not in it — nobody could index it from here",
        "blocked": "origin refused this client (403/429); fetchability not established",
        "disallowed": "robots.txt excludes it; no crawler should have it",
        "error": "network or protocol failure on our side",
    }
    origin_rows = "".join(
        f"<tr><td class='k'>{e(k)}</td><td class='k'>{v}</td>"
        f"<td>{e(MEANING.get(k, ''))}</td></tr>"
        for k, v in sorted(origin_counts.items(), key=lambda kv: -kv[1])
    ) or "<tr><td colspan='3'>control arm not run</td></tr>"
    n_confirmed = max((s.n_origin_confirmed for s in scores), default=0)
    RENDER_MEANING = {
        "server_html": "in the page's visible text — readable without executing anything",
        "embedded_json": "only inside a script or data blob — needs a renderer to surface",
        "api_only": "the crawler-facing page did not answer; an API fallback did",
        "not_present": "not in the document at all",
    }
    if render_table:
        classes = sorted({c for row in render_table.values() for c in row})
        head = "".join(f"<th>{e(c.replace('_', ' '))}</th>" for c in classes)
        body = "".join(
            "<tr><td class='k'>" + e(arm) + "</td>" + "".join(
                (lambda hv: f"<td class='k'>{hv[0]}/{hv[1]}"
                            f" <span style='color:var(--muted)'>"
                            f"({hv[0]/hv[1]*100:.0f}%)</span></td>"
                 if hv and hv[1] else "<td class='k'>—</td>")(row.get(c))
                for c in classes) + "</tr>"
            for arm, row in sorted(render_table.items()))
        legend_rows = "".join(
            f"<tr><td class='k'>{e(c.replace('_', ' '))}</td>"
            f"<td>{e(RENDER_MEANING.get(c, ''))}</td></tr>" for c in classes)
        render_block = f"""
<h2>Where the fact lived</h2>
<div class="panel">
  <div class="scroll"><table>
    <thead><tr><th>arm</th>{head}</tr></thead><tbody>{body}</tbody></table></div>
  <div class="scroll" style="margin-top:14px"><table>
    <thead><tr><th>class</th><th>meaning</th></tr></thead>
    <tbody>{legend_rows}</tbody></table></div>
  <p class="note">24-hour recall split by where the answer sat in its own document.
  The control arm already fetches every page, so this axis costs nothing, and it is the
  one that turns "provider X missed it" into something a buyer can act on. A fact in an
  <code>&lt;h1&gt;</code> and a fact buried in a <code>__NEXT_DATA__</code> blob are
  different retrieval problems. An arm strong on the first and weak on the second is not
  slow &#8212; it does not execute JavaScript, and that is a sourcing decision, not a
  latency one. Denominators are events the control arm confirmed were on the web.</p>
</div>
"""
    else:
        render_block = ""

    stale_chart = staleness_svg(list(stale_series), RUNGS) if stale_series else ""

    if sensitivity_rows:
        sens_rows = "".join(
            f"<tr><td class='k'>{e(r.name)}"
            + ("<span style='color:var(--muted)'> (reported)</span>"
               if r.name == "strict" else "")
            + "</td>"
            + (f"<td colspan='4'>{e(r.note)}</td>" if not r.regraded else
               f"<td class='k'>{r.churn*100:.1f}%</td>"
               f"<td class='k'>{r.tau:.2f}</td>"
               f"<td class='k'>{r.median_changes}/{r.n_arms}</td>"
               f"<td class='k{' bad' if r.arms_lost else ''}'>{r.arms_lost}</td>")
            + "</tr>"
            for r in sensitivity_rows)
        from .sensitivity import verdict as _sv
        sens_verdict = e(_sv(list(sensitivity_rows)))
    else:
        sens_rows = ("<tr><td colspan='5'>not evaluated &#8212; needs stored raw "
                     "payloads from a real run</td></tr>")
        sens_verdict = ("This panel fills in once probes have run against live "
                        "providers and their responses are on disk.")

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
    <thead><tr><th>arm</th><th>median TTI</th>
    <th>95% CI<br><span style="text-transform:none;letter-spacing:0">on the median</span></th>
    <th>p90</th><th>24h recall</th>
    <th>24h recall<br><span style="text-transform:none;letter-spacing:0">vs origin</span></th>
    <th>staleness</th>{ph_head}<th>p50 latency</th><th>$/1k events</th>
    <th>$/1k fresh<br><span style="text-transform:none;letter-spacing:0">answers</span></th>
    <th>events</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  {converge_note}
  {drop_note}
  {ph_note}
  <p class="note">The CI column is a nonparametric bootstrap on the median bracket's
  upper edge. It is here because a median printed without one is the most common way a
  short run gets over-read: at forty events, a bracket can land a rung either side on
  luck alone, and the ordering of this table is exactly what that luck moves. Where an
  arm's median is not reached inside the 72-hour window in some resamples, the share is
  printed rather than hidden &#8212; for a slow arm that number, not the point estimate, is
  the finding.</p>
  <p class="note">Two cost columns, because they can disagree and the disagreement is
  the point. Cost per <i>event</i> is what you pay to ask; cost per <i>fresh answer</i>
  is what you pay to get one, and a provider that returns nothing does it very cheaply.
  A freshness win bought at 5&#215; the price is a different product decision than a
  freshness win at parity, and a leaderboard that hides the denominator is
  advertising.</p>
  <p class="note">Median is a Turnbull nonparametric MLE for interval-censored data,
  reported as the interval the estimate actually pins down. An arm seen absent at 15m
  and fresh at 1h indexed somewhere in (15m, 1h] &#8212; it did not index <i>at</i> 1h, and
  printing a point would invent precision the ladder cannot supply. Events still
  un-indexed at 72h are censored, not dropped: discarding them reports every provider
  as faster than it is, and unevenly, since the bias is largest for whoever has the
  most un-indexed events. <b>&gt;72h</b> means the arm never accumulated half its mass
  inside the window, which is a different statement from "slow".</p>
</div>

<h2>Time to index</h2>
<div class="panel">
  {survival_svg(ordered, "time to index, all sources")}
  <div class="legend">{legend}</div>
</div>

<h2>The control arm</h2>
<div class="panel">
  <p style="margin-top:0">At every rung, each event's canonical URL is also fetched
  directly, with robots.txt honoured, and checked for the answer token. Of the events
  in this run, <b>{n_confirmed}</b> were confirmed retrievable from their own origin
  within 24 hours.</p>
  <div class="scroll"><table>
    <thead><tr><th>origin outcome</th><th>events</th><th>what it means</th></tr></thead>
    <tbody>{origin_rows}</tbody></table></div>
  <p class="note">Without this arm, every ABSENT is ambiguous: a provider that does not
  return the fact might have a slow crawler, or the fact might not be fetchable from its
  own page yet. The <b>24h recall vs origin</b> column asks the question only of events
  the control proved were on the web, and it is the column that is actually about the
  provider. Origins that refused us or that robots.txt excludes are omitted from that
  denominator rather than guessed at.</p>
</div>

{render_block}
<h2>Estimator check</h2>
<div class="panel">
  <div class="scroll"><table>
    <thead><tr><th>arm</th><th>Turnbull (reported)</th><th>Kaplan&#8211;Meier on the rung</th>
    <th>overstatement</th></tr></thead>
    <tbody>{km_rows}</tbody></table></div>
  <p class="note">Kaplan&#8211;Meier needs a point event time, so feeding it the rung records
  an arm as indexing <i>at</i> the probe that first saw it. That overstates every latency
  by up to a bracket width, and it cannot represent a widened interval at all when a
  probe is dropped for budget, rung slip, or a provider error. This column is kept
  visible rather than deleted: if the overstatement is ever small, the ladder is fine
  enough that the choice of estimator does not matter, and that is worth knowing too.</p>
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
  {stale_chart}
  <div class="legend">{legend}</div>
  <p class="note" style="border-color:var(--muted)">Staleness should fall as an index
  catches up, so the shape matters as much as the level. A line that stays flat means
  the provider is holding a superseded answer with confidence rather than slowly
  acquiring the new one &#8212; a different problem, and a worse one. Only questions with a
  superseded answer count here; preprints and Federal Register documents have none, so
  they are excluded by <code>Event.measures_staleness</code> rather than by
  convention.</p>
</div>

<h2>By source class</h2>
{class_blocks}

<h2>Does the ranking survive the rules that produced it</h2>
<div class="panel">
  <div class="scroll"><table>
    <thead><tr><th>rule variant</th><th>verdict churn</th><th>rank correlation</th>
    <th>medians moved</th><th>arms lost</th></tr></thead>
    <tbody>{sens_rows}</tbody></table></div>
  <p class="note">{sens_verdict}</p>
  <p class="note" style="border-color:var(--muted)">Every grading rule here is a
  judgement call: match on token boundaries or not, count a <code>v</code> prefix,
  trust aliases, treat a URL as evidence. Each variant re-grades the stored payloads
  under one of those calls made differently &#8212; no API calls, which is why the raw
  responses are kept. Rank correlation alone is not enough, and this harness caught
  that about itself: a variant that reads no content collapses every arm equally, so
  the order never changes and the correlation comes back perfect for a table that has
  stopped meaning anything. <b>Arms lost</b> is the column that catches it.</p>
</div>

<h2>Are the differences real</h2>
<div class="panel">
  <div class="scroll"><table>
    <thead><tr><th>comparison</th><th>hazard ratio</th><th>events</th><th>log-rank p</th>
    <th>power</th><th>read</th></tr></thead>
    <tbody>{pair_rows}</tbody></table></div>
  <p class="note">Log-rank rather than a t-test on the indexed subset, because most
  observations are censored and a test that ignores censoring finds differences that are
  artefacts of who ran out of window first. The power column is here because the honest
  answer early in a run is "not yet", and a leaderboard invites a claim long before the
  data can carry it: at the observed hazard ratio, Schoenfeld's formula says how many
  events 80% power would take. A hazard ratio of 2 needs 66 events; a ratio of 1.2 needs
  945.</p>
</div>

<footer>
Every number here is recomputed from <code>runs/results.jsonl</code>, and every result
points at the verbatim provider response stored under <code>runs/raw/</code>.
Re-grade the raw payloads with different matching rules and you will get a different
number out of the same evidence &#8212; which is the only reason to believe this one.
</footer>
</div>"""
