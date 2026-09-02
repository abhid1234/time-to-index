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
import statistics

from .metrics import (
    ProviderScore,
    SurvivalCurve,
    fmt_bracket,
    fmt_duration,
    fmt_p,
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


# The sentence every provider-only panel falls back to when there is no
# provider arm to draw from. One string, so the page says the same thing in
# each place rather than five slightly different things.
NO_ARMS = ("No provider arm has results yet: every provider key is unset, or every "
           "provider probe is still pending. This fills in with the first graded probe.")


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


def fmt_chars(v: float, unit: bool = True) -> str:
    """Characters the grader read per result, as a short number.

    Formatter contract as everywhere else: anything that is not a finite,
    non-negative number renders as a dash rather than as a claim. `unit`
    off is for the HTML table, whose header carries the unit and whose
    width is already spoken for.
    """
    if not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) or v < 0:
        return "—"
    if v >= 10_000:
        n = f"{v/1000:.0f}k"
    elif v >= 1_000:
        n = f"{v/1000:.1f}k"
    else:
        n = f"{v:.0f}"
    return f"{n} chars" if unit else n


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
        "| text/result | $/1k events | $/1k fresh answers | n |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for sc in sorted(scores, key=lambda s: (s.median_ttl is None, s.median_ttl or 0)):
        per_1k = (sc.spend_usd / sc.n_events * 1000) if sc.n_events else 0.0
        rows.append(
            f"| `{sc.provider}/{sc.mode}` | {fmt_pair(sc.median_bracket)} "
            f"| {fmt_pair(sc.p90_bracket)} | {_pct(sc.recall_24h)} "
            f"| {_pct(sc.staleness)} | {fmt_chars(sc.chars_per_result_p50)} | ${per_1k:.2f} "
            f"| {_cpf(sc.cost_per_fresh_24h)} | {sc.n_events} |"
        )
    return "\n".join(rows)


def summary_md(scores: list[ProviderScore], events: dict[str, Event],
               results: list[ProbeResult]) -> str:
    total_spend = sum(s.spend_usd for s in scores)
    skipped = sum(s.n_skipped_budget for s in scores)
    graded_provider = sum(s.n_calls for s in scores)
    graded_control = sum(1 for r in results
                         if r.provider == "origin" and r.verdict not in ("ERROR", "SKIPPED"))
    lines = [
        f"_Generated {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M UTC} · "
        f"{len(events)} events · {graded_provider} provider probes graded"
        + (f" · {graded_control} control probes" if graded_control else "")
        + f" · ${total_spend:.2f} spent_",
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
.wrap{max-width:1100px;margin:0 auto;padding:48px 24px 80px}
h1{font-size:30px;letter-spacing:-.02em;margin:0 0 6px;text-wrap:balance}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
   margin:44px 0 14px;font-weight:600}
.sub{color:var(--muted);margin:0 0 28px;font-size:14px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
       padding:20px 22px;margin-bottom:18px}
table{width:100%;border-collapse:collapse;font-size:13.5px;
      font-variant-numeric:tabular-nums}
th{text-align:left;font-weight:600;color:var(--muted);font-size:11px;
   text-transform:uppercase;letter-spacing:.06em;padding:0 10px 9px 0;
   border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 10px 9px 0;border-bottom:1px solid var(--grid)}
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


def corpus_html(sv, hist=None, changes=(), coverage=None) -> str:
    """The corpus half, rendered.

    Kept as a separate page from the provider leaderboard rather than a
    section of it, because the two measure different things and are usually
    collected on different schedules. A page that stitched them together
    would imply a joint analysis that only exists once both have run.

    Everything the terminal output refuses to claim, this page refuses too:
    unreachable, unstable and intercepted targets are shown as excluded with
    the reason, never folded into the rate.
    """
    esc = html.escape
    gen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    hit, n = sv.readable_rate()
    meta = sv.metadata_only()
    ratios = sv.text_ratios()
    pct = (hit / n * 100) if n else float("nan")

    MEANING = {
        "server_rendered": "readable — content in the served HTML",
        "static_html": "readable — plain server-delivered HTML",
        "metadata_only": "partial — JSON-LD or OpenGraph over an unreadable body",
        "client_shell": "not readable — a mount point and a bundle",
        "flight_payload": "at risk — content only in a hydration stream",
        "no_body": "no verdict — response too small to judge",
    }

    rows = "".join(
        "<tr>"
        f"<td class='k'>{esc(r.url[8:72])}</td>"
        f"<td class='k'>{r.prof.text_ratio*100:.2f}%</td>"
        f"<td class='k'>{r.prof.visible_chars:,}</td>"
        f"<td class='k'>{esc(r.prof.framework)}</td>"
        f"<td class='k{'' if r.readable else ' bad'}'>{esc(r.prof.posture)}</td>"
        # "0/12" is a checked robots.txt that blocks nobody. "0/0" would be a
        # robots.txt that could not be fetched, printed as if it had been.
        + (f"<td class='k'>{len(r.robots_blocked)}/{r.robots_checked}</td>" if r.robots_checked
           else "<td class='k' title='robots.txt could not be fetched'>not checked</td>")
        + "</tr>"
        for r in sorted(sv.usable, key=lambda x: x.prof.text_ratio))

    posture_rows = "".join(
        f"<tr><td class='k'>{esc(k)}</td><td class='k'>{v}</td>"
        f"<td>{esc(MEANING.get(k, ''))}</td></tr>"
        for k, v in sv.by_posture().most_common())

    cat_rows = "".join(
        f"<tr><td>{esc(c.replace('_', ' '))}</td>"
        f"<td class='k'>{h}/{t}</td>"
        f"<td class='k'>{h/t*100:.0f}%</td></tr>"
        for c, (h, t) in sv.by_category().items())

    empty = sv.open_and_empty()
    partial = [r for r in sv.open_but_unreadable() if r not in empty]
    empty_block = ""
    if empty:
        empty_block = (
            "<div class='panel'><p style='margin-top:0'><b>"
            f"{len(empty)} page(s) allow every AI crawler in robots.txt and ship "
            "them nothing at all</b> — no readable body and no metadata.</p><ul>"
            + "".join(f"<li class='k'>{esc(r.url)} "
                      f"<span style='color:var(--muted)'>"
                      f"({r.prof.visible_chars} visible chars)</span></li>"
                      for r in empty)
            + "</ul><p class='note'>Nobody chose this. It falls out of a rendering "
              "default, and the robots.txt records that the team wanted the "
              "opposite.</p>"
            + ("" if not partial else
               "<p class='note' style='border-color:var(--muted)'>"
               f"{len(partial)} more allow every crawler and ship metadata only: a "
               "summary of what the page is, not what it says.</p>")
            + "</div>")

    excluded = []
    if sv.intercepted:
        excluded.append(f"{len(sv.intercepted)} returned a body identical to another "
                        f"URL's — one page served for many is a challenge, block or "
                        f"proxy, not a rendering posture")
    if sv.unstable:
        excluded.append(f"{len(sv.unstable)} answered differently across repeat "
                        f"fetches")
    plain_unreachable = len(sv.unreachable) - len(sv.unstable) - len(sv.intercepted)
    if plain_unreachable > 0:
        excluded.append(f"{plain_unreachable} could not be fetched")
    excluded_block = ("" if not excluded else
                      "<div class='panel'><p style='margin-top:0'><b>Excluded from "
                      "every rate above:</b></p><ul>"
                      + "".join(f"<li>{esc(x)}</li>" for x in excluded)
                      + "</ul><p class='note'>A survey that counts failed fetches as "
                        "unreadable pages is measuring its own network.</p></div>")

    history_block = ""
    if coverage and coverage.runs >= 2:
        worse = [c for c in changes if c.worsened]
        change_rows = "".join(
            f"<tr><td class='k'>"
            f"{dt.datetime.fromtimestamp(c.at, dt.timezone.utc):%Y-%m-%d}</td>"
            f"<td class='k'>{esc(c.url[8:60])}</td>"
            f"<td class='k{' bad' if c.worsened else ''}'>{esc(c.describe())}</td>"
            "</tr>" for c in changes)
        history_block = f"""
<h2>What moved</h2>
<div class="panel">
  <p style="margin-top:0">{coverage.urls} URLs over {coverage.span_days:.1f} days
  and {coverage.runs} run{"s" if coverage.runs != 1 else ""}. <b>{len(changes)}</b> posture change(s),
  <b>{len(worse)}</b> of them regressions.</p>
  {"<div class='scroll'><table><thead><tr><th>when</th><th>page</th>"
   "<th>what changed</th></tr></thead><tbody>" + change_rows +
   "</tbody></table></div>" if changes else
   "<p>No posture changed between judged observations.</p>"}
  <p class="note">{"Under a day of history — 'nothing changed' describes the "
   "observation window, not the web." if coverage.span_days < 1 else
   "Nobody decides to become invisible to agents. They ship a refactor, and no "
   "build check, deploy gate or dashboard turns red when a route stops being "
   "readable. These are only ever visible in hindsight, and only if something "
   "was watching."}</p>
</div>"""

    ratio_line = ("" if not ratios else
                  f"Median visible-text ratio {statistics.median(ratios)*100:.1f}%, "
                  f"ranging {ratios[0]*100:.2f}% to {ratios[-1]*100:.1f}%.")

    return f"""<title>Can an Agent Read the Web</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap">
<style>{_CSS}</style>
<div class="wrap">
<h1>Can an Agent Read the Web</h1>
<p class="sub">Whether a page's content arrives in the served bytes as text, or as
instructions for producing text. Many crawlers — including several feeding large AI
systems — do not run those instructions. Generated {gen}.</p>

<div class="panel">
  <p style="margin-top:0"><span class="big">{hit} of {n}</span> pages were readable
  without executing JavaScript{f" ({pct:.0f}%)" if n else ""}.
  {f"<b>{len(meta)}</b> more shipped metadata over an unreadable body." if meta else ""}</p>
  <p class="note">{esc(ratio_line)} A page can be correct, fast, fully permitted by
  robots.txt, and still contribute nothing.</p>
</div>

{empty_block}

<h2>Every page judged</h2>
<div class="panel">
  <div class="scroll"><table>
    <thead><tr><th>page</th><th>visible text</th><th>chars</th><th>framework</th>
    <th>posture</th><th>robots blocks</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  <p class="note">Visible text is what remains once script, style, template and
  noscript blocks and all tags are stripped — roughly what a crawler that does not
  execute JavaScript reads. Framework is detected from served-byte markers and is
  reported, not blamed: posture predicts retrievability and framework only correlates
  with it. The same framework and version produce a fully server-rendered article and
  an empty shell, and which one you get is an application decision.</p>
</div>

<h2>Posture</h2>
<div class="panel">
  <div class="scroll"><table>
    <thead><tr><th>posture</th><th>pages</th><th>meaning</th></tr></thead>
    <tbody>{posture_rows}</tbody></table></div>
</div>

<h2>By category</h2>
<div class="panel">
  <div class="scroll"><table>
    <thead><tr><th>category</th><th>readable</th><th>rate</th></tr></thead>
    <tbody>{cat_rows}</tbody></table></div>
  <p class="note">Deep pages, not homepages. Homepages are marketing and are almost
  always server-rendered; the interesting failures are on the detail pages where the
  fact an agent was sent for actually lives.</p>
</div>

{excluded_block}
{history_block}

<footer>
Reproduce any row with <code>tti crawlability &lt;url&gt;</code>. Nothing here is
scored against a standard that does not exist: <code>llms.txt</code> is reported and
never graded, and a site that deliberately blocks AI crawlers is recorded as having
made a choice, not as having failed.
</footer>
</div>"""


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
                   render_table: dict | None = None,
                   prereg_panel: str = "",
                   fp_panel: str = "") -> str:
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

    # A run where every probe errored still produces arms, because arms are
    # derived from the results file and an ERROR is a result. The formatters
    # correctly refuse to invent numbers, so every cell reads "—" and the
    # page is not lying. It is, however, a rendered dashboard, and a rendered
    # dashboard reads as results. Say so at the top instead.
    scoreable = [s for s in scores if s.n_events]
    control_graded = sum(1 for r in results
                         if r.provider == "origin" and r.verdict not in ("ERROR", "SKIPPED"))
    if scoreable:
        empty_note = ""
    elif not scores and control_graded:
        # Not "every probe failed". Nothing failed; there is simply no
        # provider arm, which is the state before the first key arrives.
        empty_note = (
            "<div class='panel'><p style='margin-top:0'><b>Only the origin control "
            f"has results</b> — {control_graded} graded probe(s), no provider arm. "
            "The leaderboard compares provider arms and there are none: every "
            "provider key is unset, or every provider probe is still pending.</p>"
            "<p class='note'>The control panel below is the whole finding for "
            "this run. It is the yardstick, not a result about any provider.</p>"
            "</div>")
    else:
        empty_note = (
            "<div class='panel'><p style='margin-top:0'><b>No arm produced a "
            "scoreable observation.</b> Every probe in this run errored, was "
            "refused by the spend cap, or was skipped. The table below is a "
            "list of arms, not a set of results.</p>"
            "<p class='note'>Rendered rather than withheld, because "
            "\"every probe failed\" is itself the finding and refusing to "
            "draw the page would hide it.</p></div>")

    from .multiplicity import family_error_rate
    m_comparisons = sum(1 for r in powers if r.p_value == r.p_value)
    multiplicity_note = "" if m_comparisons <= 1 else (
        "<p class='note'><b>" + str(m_comparisons) + " comparisons, so the "
        "adjusted column is the one to read.</b> Judging each pair against a raw "
        "&alpha; = 0.05 would give a "
        f"{family_error_rate(m_comparisons) * 100:.0f}% chance that at least one "
        "pair is called different when neither is &#8212; a leaderboard with six "
        "arms invites fifteen comparisons, and that is how a benchmark ships a "
        "difference it invented. Holm&#8211;Bonferroni rather than plain "
        "Bonferroni: same control of the family-wise error rate, uniformly more "
        "power, and no independence assumption, which matters because pairs "
        "sharing an arm are correlated. The <b>read</b> column uses the adjusted "
        "value.</p>")

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
        f"<td class='k'>{fmt_chars(sc.chars_per_result_p50, unit=False)}</td>"
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
            f"<td class='k'>{fmt_p(r.p_value)}</td>",
            f"<td class='k'>{fmt_p(r.p_adjusted)}</td>",
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
            f"<tr><td class='k'>{e(a)} vs {e(b)}</td><td colspan='5' class='k'>p = {fmt_p(p)} (uncorrected)</td>"
            f"<td>{'distinguishable' if p < 0.05 else 'not distinguishable at this n'}</td></tr>"
            for a, b, p in pairs)   # fallback only; `powers` carries the adjusted verdict
        or "<tr><td colspan='7'>not enough events yet</td></tr>")

    km_rows = "".join(
        f"<tr><td class='k'>{e(sc.provider)}/{e(sc.mode)}</td>"
        f"<td class='k'>{fmt_pair(sc.median_bracket)}</td>"
        f"<td class='k'>{fmt_bracket(RUNGS, sc.median_ttl)}</td>"
        f"<td class='k'>{_overstatement(sc)}</td></tr>"
        for sc in ordered)

    origin_counts: dict[str, int] = {}
    confirmed_events: set[str] = set()
    for r in results:
        if r.provider != "origin" or r.verdict == "SKIPPED":
            continue  # a carry-forward row is bookkeeping, not a control observation
        key = (r.note or "origin:unknown").split()[0].replace("origin:", "")
        origin_counts[key] = origin_counts.get(key, 0) + 1
        if key == "found" and r.rung <= 86_400:
            confirmed_events.add(r.event_id)
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
    n_confirmed = len(confirmed_events)  # counted from the control rows, not from a provider score
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
    if stale_elig:
        stale_sentence = (
            '<p style="margin-top:0">Across every probe where the provider had not yet indexed '
            'the new answer and the question had a superseded one, it returned the superseded '
            f'answer <span class="big bad">{stale_pct}</span> of the time '
            f'({stale_total} of {stale_elig} opportunities).</p>')
    else:
        # A rate with no denominator is not a rate. Say what would create one.
        stale_sentence = (
            '<p style="margin-top:0"><b>No staleness opportunities yet.</b> An opportunity is '
            'a provider probe graded ABSENT or STALE on a question whose answer has a '
            'superseded value; none has been recorded'
            + (' because no provider arm has results.' if not ordered else '.') + '</p>')

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

{empty_note}
{prereg_panel}

<div class="panel">
  <div class="scroll"><table>
    <thead><tr><th>arm</th><th>median TTI</th>
    <th>95% CI<br><span style="text-transform:none;letter-spacing:0">on the median</span></th>
    <th>p90</th><th>24h recall</th>
    <th>24h recall<br><span style="text-transform:none;letter-spacing:0">vs origin</span></th>
    <th>staleness</th>{ph_head}<th>p50 latency</th>
    <th>text served<br><span style="text-transform:none;letter-spacing:0">chars / result</span></th>
    <th>$/1k events</th>
    <th>$/1k fresh<br><span style="text-transform:none;letter-spacing:0">answers</span></th>
    <th>events</th></tr></thead>
    <tbody>{rows or f"<tr><td colspan='{12 + (1 if any_phrasing else 0)}'>{NO_ARMS}</td></tr>"}</tbody></table></div>
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
  <p class="note">Text served is the median number of characters the grader read per
  returned result. Every arm is asked for the same 1,500; only the APIs that take a
  characters parameter honour it, and a snippet API returns ~150 regardless. The
  grader reads whatever came back, because that is what an agent gets &#8212; but a
  tenfold difference in this column is a tenfold difference in the surface a version
  string can appear on, and part of any recall gap lives there. The
  <code>snippet-window</code> sensitivity variant below re-grades every arm as though it
  had returned short snippets.</p>
  <p class="note">Median is a Turnbull nonparametric MLE for interval-censored data,
  reported as the interval the estimate actually pins down. An arm seen absent at 15m
  and fresh at 1h indexed somewhere in (15m, 1h] &#8212; it did not index <i>at</i> 1h, and
  printing a point would invent precision the ladder cannot supply. Events still
  un-indexed at 72h are censored, not dropped: discarding them reports every provider
  as faster than it is, and unevenly, since the bias is largest for whoever has the
  most un-indexed events. <b>&gt;72h</b> means the arm never accumulated half its mass
  inside the window, which is a different statement from "slow".</p>
</div>
{fp_panel}
<h2>Time to index</h2>
<div class="panel">
  {(survival_svg(ordered, "time to index, all sources") + f'<div class="legend">{legend}</div>')
   if ordered else
   f"<p class='note' style='margin-top:0'>No curve yet. {NO_ARMS} The control arm's outcomes are in the next panel.</p>"}
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
    <tbody>{km_rows or f"<tr><td colspan='4'>{NO_ARMS}</td></tr>"}</tbody></table></div>
  <p class="note">Kaplan&#8211;Meier needs a point event time, so feeding it the rung records
  an arm as indexing <i>at</i> the probe that first saw it. That overstates every latency
  by up to a bracket width, and it cannot represent a widened interval at all when a
  probe is dropped for budget, rung slip, or a provider error. This column is kept
  visible rather than deleted: if the overstatement is ever small, the ladder is fine
  enough that the choice of estimator does not matter, and that is worth knowing too.</p>
</div>

<h2>Staleness</h2>
<div class="panel">
  {stale_sentence}
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
{class_blocks or "<div class='panel'><p class='note' style='margin-top:0'>Per-class tables appear once a provider arm has events in a source class.</p></div>"}

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
    <th>p adjusted<br><span style="text-transform:none;letter-spacing:0">Holm–Bonferroni</span></th>
    <th>power</th><th>read</th></tr></thead>
    <tbody>{pair_rows}</tbody></table></div>
  {multiplicity_note}
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


def fp_panel_html(rep, verified: bool = False, synthetic: bool = False) -> str:
    """The pipeline's false-positive rate, per arm, beside the leaderboard.

    The plan lists this as a secondary endpoint "reported alongside recall
    rather than as a footnote, because it is recall's error bar". Until this
    panel existed it was a footnote: a separate command's stdout.
    """
    from .metrics import wilson
    e = html.escape
    # The control arm is re-graded too, but it is not a leaderboard row: its
    # figure is the grader's own rate on page bytes, and it goes in a sentence.
    arms = [a for a in (rep.arms if rep is not None else []) if a.provider != "origin"]
    control = next((a for a in (rep.arms if rep is not None else []) if a.provider == "origin"), None)
    control_note = ""
    if control is not None and control.graded:
        _, _, chi = wilson(control.hits, control.graded)
        control_note = (f" The origin control's own re-grade: {control.hits} of "
                        f"{control.graded} page fetches matched the counterfactual "
                        f"(upper bound {chi*100:.0f}%) — the grader's rate on raw page "
                        f"bytes, with no provider in the loop.")
    if not any(a.graded for a in arms):
        why = (NO_ARMS if not arms else
               "No stored payload could be re-graded: either nothing wrote a raw "
               "payload, or no event had a version-shaped answer to build a "
               "counterfactual from.")
        rows = f"<tr><td colspan='5'>{e(why)}</td></tr>"
    else:
        rows = ""
        for a in arms:
            p_, lo, hi = wilson(a.hits, a.graded)
            rows += (f"<tr><td class='k'>{e(a.provider)}/{e(a.mode)}</td>"
                     f"<td class='k'>{a.graded}</td>"
                     f"<td class='k{' bad' if a.hits else ''}'>{a.hits}</td>"
                     f"<td class='k'>{p_*100:.1f}% ({lo*100:.0f}–{hi*100:.0f})</td>"
                     f"<td class='k'>up to {hi*100:.0f}%</td></tr>")
    if synthetic:
        prov = ("Counterfactuals are unpublished by construction on a synthetic run; "
                "no registry was asked.")
    elif verified:
        prov = "Each counterfactual was confirmed absent with its registry before grading."
    else:
        prov = ("This render did not ask any registry whether the counterfactuals are "
                "really unpublished — the page is built offline. <code>tti decoy</code> "
                "does, and its figure is the one to quote.")
    skipped = ""
    if rep is not None and rep.events_skipped:
        reasons = "; ".join(f"{n} {e(r)}" for r, n in sorted(rep.skip_reasons.items()))
        skipped = f" {rep.events_skipped} event(s) could not be decoyed: {reasons}."
    return f"""
<h2>Pipeline false-positive rate</h2>
<div class="panel">
  <p style="margin-top:0">Every stored payload re-graded against a <b>counterfactual</b>
  answer: a version-shaped token of the same form as the real one that was never
  published. A FRESH verdict against it is a false positive by construction. This is
  recall's error bar, which is why it sits here and not in a footnote.</p>
  <div class="scroll"><table>
    <thead><tr><th>arm</th><th>payloads re-graded</th><th>false positives</th>
    <th>rate (95% CI)</th><th>of this arm's FRESH verdicts<br><span style="text-transform:none;letter-spacing:0">that could be spurious</span></th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  <p class="note">Two causes, both invisible in a leaderboard: the grader matching a
  version-shaped token in unrelated prose, or a provider's answer layer inventing one.
  Zero observed is not a zero rate — the last column is the Wilson upper bound, and
  it is the number that belongs beside each arm's recall. {prov}{e(skipped)}{e(control_note)}</p>
</div>
"""


def fp_md(rep, verified: bool = False, synthetic: bool = False) -> str:
    from .metrics import wilson
    arms = [a for a in (rep.arms if rep is not None else []) if a.provider != "origin"]
    if not any(a.graded for a in arms):
        return ""
    lines = ["", "## Pipeline false-positive rate", "",
             "| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |",
             "|---|---|---|---|---|"]
    for a in arms:
        p_, lo, hi = wilson(a.hits, a.graded)
        lines.append(f"| `{a.provider}/{a.mode}` | {a.graded} | {a.hits} | "
                     f"{p_*100:.1f}% ({lo*100:.0f}–{hi*100:.0f}) | {hi*100:.0f}% |")
    tail = ("Counterfactuals unpublished by construction (synthetic run)." if synthetic else
            "Counterfactuals confirmed absent with their registries." if verified else
            "Counterfactuals not registry-verified in this render; `tti decoy` verifies them.")
    lines += ["", f"_{tail} Zero observed is not a zero rate; quote the upper bound._"]
    return "\n".join(lines)


def prereg_panel_html(ps) -> str:
    """The pre-registration banner for the dashboard.

    `ps` is whatever `cli._plan_status` returned: the string "synthetic", None
    for an unreadable plan, or (plan, classification, lock status).

    Deliberately at the top of the page rather than in a footnote. The whole
    value of pre-registering is that a reader learns, before reading a single
    number, which of them were promised in advance — a disclosure at the
    bottom is one the reader reaches only after forming a view.
    """
    e = html.escape
    if ps == "synthetic":
        return ("<div class='panel'><p style='margin-top:0'><b>Synthetic run.</b> "
                "These arms are a generator whose latencies are already known. "
                "The pre-registered plan does not apply, because nothing here is "
                "a measurement of anybody's product.</p></div>")
    if ps is None:
        return ("<div class='panel' style='border-color:var(--bad)'>"
                "<p style='margin-top:0'><b>No analysis plan.</b> "
                "<code>docs/PREREGISTRATION.md</code> could not be read, so every "
                "quantity on this page is exploratory: nothing constrains which "
                "comparisons were chosen, or when.</p></div>")

    plan, cls, st = ps
    rows = []
    if st.drifted:
        rows.append(
            "<p style='margin-top:0'><b>The analysis plan changed after "
            f"collection began.</b> Locked <code>{e(st.locked or '')}</code>, "
            f"now <code>{e(st.current)}</code>.</p>"
            "<p class='note'>Not forbidden and not necessarily wrong — plans are "
            "sometimes wrong. Printed every time, because a plan edited after the "
            "data exists is a different kind of claim from one written before it, "
            "and only one of those two facts survives if nobody says which.</p>")
    elif st.locked:
        rows.append(
            "<p style='margin-top:0'><b>Pre-registered.</b> Plan "
            f"<code>{e(plan.hash)}</code> (v{plan.version}, registered "
            f"{e(plan.registered)}) was locked to this run on its first probe "
            "and has not changed since.</p>")
    elif st.started:
        rows.append(
            "<p style='margin-top:0'><b>No plan lock.</b> This run has results, "
            "but nothing records that the plan predates them.</p>")
    else:
        rows.append(
            "<p style='margin-top:0'><b>Plan registered, collection not "
            f"started.</b> <code>{e(plan.hash)}</code>, v{plan.version}.</p>")

    if cls.exploratory:
        rows.append("<p class='note' style='border-color:var(--bad)'><b>Exploratory, "
                    "not pre-registered:</b> " + e(", ".join(cls.exploratory)) +
                    ". These arms appear in the data and not in the plan. They are "
                    "shown, not hidden — the useful thing is the label.</p>")
    if cls.declared_but_silent:
        rows.append("<p class='note'><b>Declared in the plan, enabled, produced nothing:</b> " +
                    e(", ".join(cls.declared_but_silent)) +
                    ". Named because a table is built from what is in the ledger, so "
                    "an arm that failed everywhere is otherwise simply not a row — "
                    "which is how a benchmark loses its worst result without anybody "
                    "deciding to.</p>")
    if getattr(cls, "declared_not_enabled", None):
        rows.append("<p class='note'><b>Declared in the plan, not enabled in this run:</b> " +
                    e(", ".join(cls.declared_not_enabled)) +
                    ". No key was set, so no probe was ever dispatched to these arms. "
                    "That is a configuration state, not a result — they did not fail, "
                    "they were never asked.</p>")

    hyp = "".join(
        f"<tr><td><code>{e(h.id)}</code></td><td>{e(h.statement)}</td>"
        f"<td>{e(h.threshold)}</td><td>{e(h.falsified_if)}</td></tr>"
        for h in plan.hypotheses)
    rows.append(
        "<details><summary>The plan: what was promised, and what would falsify it"
        "</summary><div class='scroll'><table><thead><tr><th>id</th>"
        "<th>hypothesis</th><th>threshold</th><th>falsified if</th></tr></thead>"
        f"<tbody>{hyp}</tbody></table></div>"
        f"<p class='note'><b>Primary endpoint.</b> {e(plan.primary_endpoint)}</p>"
        f"<p class='note'><b>Stopping rule.</b> {e(plan.stopping_rule)}</p>"
        "</details>")
    return "<div class='panel'>" + "".join(rows) + "</div>"
