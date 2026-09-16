"""Diagrams for the post. SVG/CSS source, PNG for Substack.

Substack strips inline SVG, so each one is rasterised at 2x through the same
headless Chromium that renders the playground -- which also means the diagrams
inherit the page's palette and type exactly, rather than approximating them.

Three diagrams, in the order the post needs them:

  1. absent-vs-stale  the two failure paths and what each costs downstream
  2. architecture     where t=0 comes from and what happens after it
  3. interval         the six rungs, one arm's verdicts, and the bracket

Needs `python -m http.server 8890` running in docs/ (for the fonts).
"""
from __future__ import annotations

import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "diagrams"
FONTS = "http://127.0.0.1:8890/fonts"
CHROME = "/opt/pw-browsers/chromium"

SHELL = """
<style>
@font-face{{font-family:Newsreader;src:url({f}/newsreader-var.woff2)format("woff2");font-weight:400 700}}
@font-face{{font-family:"IBM Plex Sans";src:url({f}/plex-sans-var.woff2)format("woff2");font-weight:100 700}}
@font-face{{font-family:"IBM Plex Mono";src:url({f}/plex-mono-400.woff2)format("woff2");font-weight:400}}
@font-face{{font-family:"IBM Plex Mono";src:url({f}/plex-mono-600.woff2)format("woff2");font-weight:600}}
:root{{
  --ink:#12161C;--ink2:#464F5B;--ink3:#767F8C;--rule:#E2E5EA;--rule2:#CFD5DD;
  --panel:#FFFFFF;--inset:#F2F3F5;--ground:#FBFAF8;
  --accent:#2B5CA8;--accent-soft:#EDF2FA;
  --fresh:#0B7A4F;--fresh-bg:#E4F4EC;--fresh-line:#8FCFB1;
  --stale:#BC3E12;--stale-bg:#FCE9E0;--stale-line:#EFA786;
  --absent:#6C7684;--absent-bg:#EDEFF3;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);font-family:"IBM Plex Sans",sans-serif;
  color:var(--ink);-webkit-font-smoothing:antialiased}}
.d{{padding:34px 38px}}
.t{{font-family:Newsreader,serif;font-size:25px;font-weight:500;
  letter-spacing:-.015em;margin:0 0 4px}}
.s{{font-size:14px;color:var(--ink3);margin:0 0 26px;max-width:74ch;
  line-height:1.5}}
.mono{{font-family:"IBM Plex Mono",monospace}}
.nb{{white-space:nowrap}}
.cap{{font-family:"IBM Plex Mono",monospace;font-size:10px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--ink3)}}
{css}
</style>
<div class="d">{body}</div>
"""

# --------------------------------------------------------------------------
ABSENT_STALE = dict(
    w=1000, h=380, name="absent-vs-stale",
    css="""
.two{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:6px}
.col{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  overflow:hidden;display:flex;flex-direction:column}
/* The two columns are a comparison, so their rows have to line up. The flow
   grows to fill whatever height the taller card sets, which pins both cost
   boxes to the same baseline; the fixed step height keeps steps 2 and 3 level
   even though only the STALE side wraps to two lines. */
.col .flow{flex:1}
.col .hd{padding:14px 18px;border-bottom:1px solid var(--rule);display:flex;
  align-items:center;gap:10px}
.col .hd .tag{font-family:"IBM Plex Mono",monospace;font-size:12.5px;
  font-weight:600;letter-spacing:.1em}
.a .hd{background:var(--absent-bg)} .a .tag{color:var(--absent)}
.s2 .hd{background:var(--stale-bg)} .s2 .tag{color:var(--stale)}
.col .hd .q{font-size:13px;color:var(--ink2)}
.flow{padding:16px 18px 20px}
.step{display:flex;gap:12px;align-items:flex-start;padding:9px 0;
  min-height:60px}
/* Only the steps that something below them has to line up with need a
   reserved height. The last one has the cost box directly under it in both
   columns, so holding two lines open there just prints a gap. */
.step:last-child{min-height:0}
.step .n{font-family:"IBM Plex Mono",monospace;font-size:10.5px;
  color:var(--ink3);width:14px;flex-shrink:0;padding-top:3px}
.step .x{font-size:14px;line-height:1.45;color:var(--ink2)}
.step .x b{color:var(--ink)}
.arrow{height:14px;border-left:1px dashed var(--rule2);margin-left:6px}
.out{margin:10px 18px 18px;padding:12px 15px;border-radius:7px;
  font-size:13.5px;line-height:1.45;min-height:62px;display:flex;
  align-items:center}
.a .out{background:var(--inset);color:var(--ink2)}
.s2 .out{background:var(--stale-bg);color:var(--stale);font-weight:500}
.score{margin-top:22px;text-align:center;font-size:14.5px;color:var(--ink2)}
.score b{color:var(--ink)}
""",
    body="""
<p class="t">Two failures. One score.</p>
<p class="s">The same question, asked of two search APIs, five minutes after the
answer changed. Both are graded wrong by every retrieval benchmark I can find.
Only one of them is visible to anything downstream.</p>
<div class="two">
  <div class="col a">
    <div class="hd"><span class="tag">ABSENT</span>
      <span class="q">returns nothing relevant</span></div>
    <div class="flow">
      <div class="step"><span class="n">1</span><span class="x">Agent asks for the
        current version.</span></div>
      <div class="arrow"></div>
      <div class="step"><span class="n">2</span><span class="x">Empty result set.
        <b>The agent can see this.</b></span></div>
      <div class="arrow"></div>
      <div class="step"><span class="n">3</span><span class="x">It retries, widens
        the query, or says it doesn't know.</span></div>
    </div>
    <div class="out">Cost: latency and tokens. The failure surfaces.</div>
  </div>
  <div class="col s2">
    <div class="hd"><span class="tag">STALE</span>
      <span class="q">returns yesterday's answer</span></div>
    <div class="flow">
      <div class="step"><span class="n">1</span><span class="x">Agent asks for the
        current version.</span></div>
      <div class="arrow"></div>
      <div class="step"><span class="n">2</span><span class="x">A confident,
        well-formed, superseded answer. <b>Nothing marks it as old.</b></span></div>
      <div class="arrow"></div>
      <div class="step"><span class="n">3</span><span class="x">It stops, and
        cites it.</span></div>
    </div>
    <div class="out">Cost: a wrong answer with a citation, delivered to your user.</div>
  </div>
</div>
<p class="score">Scored out of one, both are <b>0</b>. That is the number this
project refuses to accept.</p>
""")

# --------------------------------------------------------------------------
ARCHITECTURE = dict(
    w=1000, h=520, name="architecture",
    css="""
.row{display:flex;align-items:stretch;gap:0;margin-top:4px}
.box{background:var(--panel);border:1px solid var(--rule);border-radius:9px;
  padding:14px 16px;flex:1;min-width:0}
.box .h{font-size:14.5px;font-weight:600;margin:0 0 5px}
.box .p{font-size:12.5px;color:var(--ink3);line-height:1.45;margin:0}
.box ul{margin:7px 0 0;padding-left:15px}
.box li{font-size:12px;color:var(--ink2);line-height:1.6}
.arr{display:flex;align-items:center;justify-content:center;width:46px;
  color:var(--rule2);flex-shrink:0;font-size:20px}
.zero{border-color:var(--fresh-line);background:var(--fresh-bg)}
.zero .h{color:var(--fresh)}
.ctl{border-color:var(--accent);background:var(--accent-soft)}
.ctl .h{color:var(--accent)}
.lad{margin-top:22px;background:var(--panel);border:1px solid var(--rule);
  border-radius:9px;padding:16px 18px}
.rungs{display:flex;gap:8px;margin-top:11px}
.rung{flex:1;text-align:center;padding:11px 4px;border-radius:6px;
  background:var(--inset);border:1px solid var(--rule);
  font-family:"IBM Plex Mono",monospace;font-size:12.5px;font-weight:600;
  color:var(--accent)}
.note{font-size:12.5px;color:var(--ink3);margin:12px 0 0;line-height:1.5}
.note b{color:var(--ink2)}
""",
    body="""
<p class="t">How the clock starts, and what happens after it</p>
<p class="s">No crawler anywhere in this diagram. The whole design rests on
sources that publish their own timestamps, because you cannot measure lateness
without an agreed zero — and asking a crawler when something appeared is asking
the defendant to time the race.</p>
<div class="row">
  <div class="box zero">
    <p class="h">1 · Publishers</p>
    <p class="p">Sources that timestamp themselves. Their clock is <span
      class="mono nb">t=0</span>, never mine.</p>
    <ul><li>npm, PyPI</li><li>GitHub releases</li><li>SEC EDGAR, arXiv</li>
      <li>Federal Register</li></ul>
  </div>
  <div class="arr">→</div>
  <div class="box">
    <p class="h">2 · Collector</p>
    <p class="p">Polls, and builds a question only the new fact answers.</p>
    <ul><li>Noticed &gt; 10 min late? <b>dropped</b></li>
      <li>Never reads provider output</li></ul>
  </div>
  <div class="arr">→</div>
  <div class="box">
    <p class="h">3 · Scheduler</p>
    <p class="p">Enqueues one probe per arm per rung, at publish time + lag.</p>
    <ul><li>Fires late? <b>dropped, not fudged</b></li>
      <li>Daily spend cap</li></ul>
  </div>
  <div class="arr">→</div>
  <div class="box ctl">
    <p class="h">4 · Grader + ledger</p>
    <p class="p">FRESH / STALE / ABSENT against the new token and the one it
      replaced.</p>
    <ul><li>Call failed? <b>ERROR, not ABSENT</b></li>
      <li>Raw payload kept</li></ul>
  </div>
</div>
<div class="lad">
  <span class="cap">The same question, at six fixed lags — plus a direct fetch of
  the source URL at every one</span>
  <div class="rungs">
    <div class="rung">t + 5m</div><div class="rung">t + 15m</div>
    <div class="rung">t + 1h</div><div class="rung">t + 6h</div>
    <div class="rung">t + 24h</div><div class="rung">t + 72h</div>
  </div>
  <p class="note">That direct fetch is the control, and it is what makes the rest
  interpretable. <b>Without it, "the provider was slow" and "the document was not
  on the web yet" look identical</b> — and you end up blaming an index for a
  publisher's CDN.</p>
</div>
""")

# --------------------------------------------------------------------------
LADDER = dict(
    w=1000, h=430, name="interval",
    css="""
.grid{display:grid;grid-template-columns:150px repeat(6,1fr);gap:7px;
  align-items:center;margin-top:8px}
.hd{font-family:"IBM Plex Mono",monospace;font-size:10.5px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink3);text-align:center;
  padding-bottom:4px}
.hd.l{text-align:left}
.arm{font-size:14px;font-weight:600}
.arm span{display:block;font-size:11.5px;color:var(--ink3);font-weight:400}
.c{height:46px;border-radius:6px;display:flex;align-items:center;
  justify-content:center;font-family:"IBM Plex Mono",monospace;font-size:10.5px;
  font-weight:600;letter-spacing:.05em;border:1px solid transparent}
.c.f{background:var(--fresh-bg);color:var(--fresh);border-color:var(--fresh-line)}
.c.a{background:var(--absent-bg);color:var(--absent)}
.c.sk{border:1px dashed var(--rule2);color:var(--ink3);font-weight:400}
.band{margin-top:20px;background:var(--panel);border:1px solid var(--rule);
  border-radius:9px;padding:16px 18px}
.bar{position:relative;height:54px;margin:14px 0 6px}
.bar .track{position:absolute;left:0;right:0;top:20px;height:2px;
  background:var(--rule2)}
.bar .win{position:absolute;top:8px;height:26px;border-radius:5px;
  background:color-mix(in srgb,var(--accent) 16%,transparent);
  border:1px solid var(--accent);left:16.6%;width:33.3%}
.bar .lab{position:absolute;top:12px;left:calc(16.6% + 10px);
  font-family:"IBM Plex Mono",monospace;font-size:12px;font-weight:600;
  color:var(--accent)}
.bar .tick{position:absolute;top:14px;width:1px;height:14px;background:var(--ink3)}
.bar .tl{position:absolute;top:40px;font-family:"IBM Plex Mono",monospace;
  font-size:10.5px;color:var(--ink3);transform:translateX(-50%)}
/* Centring every label on its tick pushed the first and last ones half out of
   the panel, which read as the diagram being clipped. The ends align inward. */
.bar .tl.st{transform:none}
.bar .tl.en{transform:translateX(-100%)}
.note{font-size:13px;color:var(--ink3);margin:10px 0 0;line-height:1.55}
.note b{color:var(--ink2)}
""",
    body="""
<p class="t">What the ladder can and cannot tell you</p>
<p class="s">One arm, one event. It was absent at fifteen minutes and fresh at an
hour — so it started answering somewhere in between, and nobody knows where.</p>
<div class="grid">
  <div class="hd l">Arm</div>
  <div class="hd">t + 5m</div><div class="hd">t + 15m</div><div class="hd">t + 1h</div>
  <div class="hd">t + 6h</div><div class="hd">t + 24h</div><div class="hd">t + 72h</div>
  <div class="arm">provider A<span>a real search index</span></div>
  <div class="c a">ABSENT</div><div class="c a">ABSENT</div><div class="c f">FRESH</div>
  <div class="c sk">skipped</div><div class="c sk">skipped</div><div class="c sk">skipped</div>
</div>
<div class="band">
  <span class="cap">What gets recorded</span>
  <div class="bar">
    <div class="track"></div>
    <div class="win"></div>
    <div class="lab">indexed somewhere in here</div>
    <div class="tick" style="left:0"></div><div class="tl st" style="left:0">t=0</div>
    <div class="tick" style="left:16.6%"></div><div class="tl" style="left:16.6%">15m</div>
    <div class="tick" style="left:49.9%"></div><div class="tl" style="left:49.9%">1h</div>
    <div class="tick" style="left:99.8%"></div><div class="tl en" style="left:99.8%">72h</div>
  </div>
  <p class="note">The recorded value is the interval <b class="mono">(15m, 1h]</b>,
  not a point. Picking the midpoint would invent precision the ladder cannot
  supply. <b>Once an arm answers FRESH the later rungs are skipped</b> — carrying
  the result forward rather than paying to ask a question already answered, which
  is why those three squares are empty rather than absent.</p>
</div>
""")


# --------------------------------------------------------------------------
# The one diagram that is not illustrative. Every value in it is read from the
# ledger at render time, so it cannot drift from what the repo actually holds
# -- and if the event ever disappears, this fails loudly instead of printing a
# stale picture.
THE_CATCH = dict(
    w=1000, h=430, name="the-catch",
    css="""
.sub{font-size:13px;color:var(--ink3);margin:0 0 20px}
.tbl{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  overflow:hidden}
.r{display:grid;grid-template-columns:1.35fr 1fr .62fr .58fr;align-items:center;
  padding:13px 18px;border-top:1px solid var(--rule)}
.r:first-child{border-top:0}
.r.h{background:var(--inset);font-family:"IBM Plex Mono",monospace;
  font-size:10px;letter-spacing:.13em;text-transform:uppercase;color:var(--ink3)}
.r .arm{font-size:14px;font-weight:600;color:var(--ink)}
.r .arm span{display:block;font-size:11.5px;font-weight:400;color:var(--ink3)}
.r .got{font-family:"IBM Plex Mono",monospace;font-size:14px;font-weight:600}
.r .got em{font-style:normal;font-size:11.5px;font-weight:400;color:var(--ink3);
  display:block;letter-spacing:.02em}
.r .num{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink2);
  text-align:right}
.r.ctl{background:var(--accent-soft)}
.r.ctl .arm{color:var(--accent)}
.r.ctl .got{color:var(--fresh)}
.r.stale{background:var(--stale-bg)}
.r.stale .got{color:var(--stale)}
.r.none .got{color:var(--absent)}
.kick{margin-top:20px;font-size:14px;line-height:1.55;color:var(--ink2)}
.kick b{color:var(--ink)}
.foot{margin-top:12px;font-size:12px;color:var(--ink3);line-height:1.5}
""",
    body=None)   # built at render time from the ledger


SOURCE_NAMES = {"github_release": "GitHub", "npm": "npm", "pypi": "PyPI",
                "sec_edgar": "SEC EDGAR", "arxiv": "arXiv",
                "federal_register": "the Federal Register"}


def catch_body(repo):
    """Read the uv event out of the ledger and lay it out."""
    import json
    led = repo / "ledger"
    events = [json.loads(x) for x in
              (led / "events.jsonl").read_text().splitlines() if x.strip()]
    ev = next((e for e in events if e["subject"] == "astral-sh/uv"
               and e["answer"] == "0.12.15"), None)
    if ev is None:
        raise SystemExit("the uv 0.12.15 event is not in the ledger any more "
                         "-- the diagram and the copy both need rewriting")

    seen, rows = set(), []
    for line in (led / "results.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["event_id"] != ev["event_id"] or r["rung"] != 300:
            continue
        if r["probe_id"] in seen:
            continue
        seen.add(r["probe_id"])
        rows.append(r)

    order = {"origin": 0}
    rows.sort(key=lambda r: (order.get(r["provider"], 1), r["verdict"] != "STALE",
                             r["provider"]))
    lag = round(ev["discovered_at"] - ev["published_at"])

    out = ['<p class="t">Five minutes after the release went live</p>',
           f'<p class="sub">{ev["subject"]} {ev["answer"]}, published on '
           f'{SOURCE_NAMES.get(ev["source"], ev["source"])} and noticed {lag} '
           f'seconds later. '
           f'Every arm asked the same question at t+5m. Read from the ledger, '
           f'not retyped.</p>',
           '<div class="tbl">',
           '<div class="r h"><span>Arm</span><span>Returned at t + 5m</span>'
           '<span class="num">Latency</span><span class="num">Cost</span></div>']

    for r in rows:
        control = r["provider"] == "origin"
        if r["verdict"] == "STALE":
            cls, got, note = "stale", r["matched_stale"][0], "superseded"
        elif r["verdict"] == "FRESH":
            cls, got, note = "ctl", ev["answer"], "the current answer"
        else:
            cls, got, note = "none", "—", "nothing relevant"
        if control:
            cls = "ctl"
        name = (f'{r["provider"]} · {r["mode"]}' if not control
                else "origin control")
        sub = ("fetches the release page directly" if control
               else "a real search index")
        cost = r.get("cost_usd") or 0.0
        out.append(
            f'<div class="r {cls}"><div class="arm">{name}<span>{sub}</span></div>'
            f'<div class="got">{got}<em>{note}</em></div>'
            f'<div class="num">{r["latency_ms"]:,} ms</div>'
            f'<div class="num">{"free" if control else f"${cost:.4f}"}</div></div>')

    out.append("</div>")
    n_stale = sum(1 for r in rows if r["verdict"] == "STALE")
    n_prov = sum(1 for r in rows if r["provider"] != "origin")
    out.append(
        f'<p class="kick"><b>Not one of the {n_prov} indexes had the current '
        f'answer, and {n_stale} of them confidently asserted the old one</b> — '
        f'the same wrong version, independently, at the same instant. The '
        f'control had it, so the release was live and fetchable right then. '
        f'Every conventional benchmark scores those {n_stale} rows exactly the '
        f'same as the empty ones: zero.</p>')
    out.append(
        '<p class="foot">One event. Not a rate, not a ranking — at this sample '
        'size no pair of arms separates, and the dashboard refuses to rank '
        'itself for that reason.</p>')
    return "\n".join(out)


def render(spec: dict, pg) -> None:
    html = SHELL.format(f=FONTS, css=spec["css"], body=spec["body"])
    pg.set_viewport_size({"width": spec["w"], "height": spec["h"]})
    pg.set_content(html, wait_until="load")
    pg.wait_for_timeout(700)
    path = OUT / f"{spec['name']}.png"
    pg.locator(".d").screenshot(path=str(path))
    print(f"  {path.name:<24} {path.stat().st_size // 1024} KB")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, args=["--hide-scrollbars"])
        pg = b.new_page(device_scale_factor=2)
        THE_CATCH["body"] = catch_body(HERE.parent)
        for spec in (ABSENT_STALE, ARCHITECTURE, LADDER, THE_CATCH):
            render(spec, pg)
        b.close()


if __name__ == "__main__":
    main()
