"""The short cut: ninety seconds, no voice, the argument carried by on-screen words.

Modelled on the AgentRoute launch video: one idea per scene, a two-tone headline
or a framed app window with a one-line caption beneath it, over a quiet
instrumental bed. That format is for people meeting the video in a feed with
the sound off, so every scene has to read on its own in the time it is up.

Rendered deterministically rather than screen-recorded. The page exposes
seek(t); each frame is drawn at an exact time and screenshotted, and the frames
go straight into ffmpeg over a pipe. A live recording drops frames under load
and eases on the browser's clock; this is identical every run and perfectly
smooth, and the frames never touch the disk.

    python -m http.server 8890   # in docs/, for the playground screenshot
    python make_short.py
"""
from __future__ import annotations

import base64
import html
import json
import pathlib
import subprocess
import sys

import story
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
BUILD = HERE / "build"
FONTS = HERE.parents[1] / "docs" / "fonts"
CHROME = "/opt/pw-browsers/chromium"
W, H, FPS = 1920, 1080, 30

# (scene id, start, end). Durations are set by how long the words take to
# read comfortably, not by anything else.
SCENES = [("s1", 0.0, 4.6), ("s2", 4.6, 15.4), ("s3", 15.4, 23.6),
          ("s4", 23.6, 34.8), ("s5", 34.8, 49.2), ("s6", 49.2, 62.0),
          ("s7", 62.0, 74.4), ("s8", 74.4, 83.0), ("s9", 83.0, 91.0)]
DURATION = SCENES[-1][2]


def b64(p: pathlib.Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def playground_shot() -> str:
    """The real playground, mid-argument: the ladder run, the rule flipped."""
    BUILD.mkdir(exist_ok=True)
    out = BUILD / "playground-shot.png"
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, args=["--hide-scrollbars"])
        pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
        pg.goto("http://127.0.0.1:8890/playground.html", wait_until="load")
        pg.wait_for_timeout(1500)
        pg.click("#play")
        pg.wait_for_timeout(9500)
        pg.click("#m-new")
        pg.wait_for_timeout(1200)
        pg.add_style_tag(content=".rail{position:static!important}")
        pg.wait_for_timeout(300)
        top = pg.evaluate("document.querySelector('#s3').getBoundingClientRect().top + scrollY - 40")
        bot = pg.evaluate("document.querySelector('.results').getBoundingClientRect().bottom + scrollY + 48")
        pg.screenshot(path=str(out), full_page=True,
                      clip={"x": 0, "y": top, "width": 1440, "height": bot - top})
        b.close()
    return b64(out, "image/png")


def page(f: dict, shot: str) -> str:
    fonts = "\n".join(
        f'@font-face{{font-family:"{fam}";src:url({b64(FONTS / fn, "font/woff2")}) '
        f'format("woff2");font-weight:{w}}}'
        for fam, fn, w in [("Plex", "plex-sans-var.woff2", "100 700"),
                           ("PlexMono", "plex-mono-600.woff2", "600"),
                           ("PlexMono", "plex-mono-400.woff2", "400")])

    e = html.escape
    uv = f["uv"]
    rows = "".join(
        f'<div class="row {r["verdict"].lower()}{" ctl" if r["control"] else ""}" data-in="{1.6 + 0.85 * i:.2f}">'
        f'<span class="who">{e(r["who"])}</span>'
        f'<span class="said">{e(r["said"])}</span>'
        f'<span class="tag">{"✓ " if r["verdict"] == "FRESH" else ("✗ " if r["verdict"] == "STALE" else "")}{e(r["note"])}</span></div>'
        for i, r in enumerate(uv["rows"]))

    mx = max(s["total"] for s in f["sources"])
    bars = "".join(
        f'<div class="src" data-in="{1.3 + 0.55 * i:.2f}">'
        f'<div class="lab">{e(s["plain"])}<small>{e(s["where"])}</small></div>'
        f'<div class="track" style="width:{100 * s["total"] / mx:.1f}%">'
        f'<div class="fill" data-grow="{1.6 + 0.55 * i:.2f}" data-w="{100 * s["fresh"] / max(s["total"], 1):.2f}"></div>'
        f'{"" if s["fresh"] else f"""<span class="zero" data-in="{2.4 + 0.55 * i:.2f}">not once</span>"""}</div>'
        f'<div class="num{" hot" if s["fresh"] else ""}"><b data-count="{s["fresh"]}" data-at="{1.6 + 0.55 * i:.2f}">0</b>'
        f'<i>/ {s["total"]}</i></div></div>'
        for i, s in enumerate(f["sources"]))

    tied = " and ".join(f["arm_tied_with"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{fonts}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:#F2F0EB}}
body{{font-family:Plex,system-ui,sans-serif;color:#12161C;-webkit-font-smoothing:antialiased}}
.grid{{position:fixed;inset:0;background-image:radial-gradient(rgba(18,22,28,.085) 1.4px,transparent 1.6px);
  background-size:30px 30px}}
.scene{{position:absolute;inset:0;visibility:hidden;will-change:opacity}}
[data-in]{{opacity:0}}
.h{{position:absolute;left:0;right:0;top:118px;text-align:center;font-size:66px;font-weight:600;
  letter-spacing:-.022em;line-height:1.14}}
.h em{{font-style:normal;color:#2B5CA8;display:block}}
.sub{{position:absolute;left:0;right:0;text-align:center;font-size:32px;color:#8C929B;font-weight:500;
  letter-spacing:-.005em}}
.cap{{position:absolute;left:0;right:0;bottom:62px;text-align:center;font-size:31px;color:#80868F;font-weight:500}}
.cap b{{color:#12161C;font-weight:600}}

/* s1 */
.logo{{position:absolute;left:0;right:0;top:396px;display:flex;align-items:center;justify-content:center;gap:34px}}
.logo svg{{width:128px;height:128px}}
.word{{font-size:92px;font-weight:600;letter-spacing:-.03em}}
.word + .tl{{display:block}}
.tagline{{position:absolute;left:0;right:0;top:586px;text-align:center;font-size:36px;color:#6B727C;font-weight:500}}

/* s2 */
.pair{{position:absolute;left:210px;right:210px;top:392px;display:grid;grid-template-columns:1fr 1fr;gap:48px}}
.card{{background:#fff;border-radius:20px;padding:38px 42px 40px;box-shadow:0 18px 50px rgba(18,22,28,.10),0 2px 6px rgba(18,22,28,.05)}}
.card .k{{font-family:PlexMono,monospace;font-size:21px;font-weight:600;letter-spacing:.14em}}
.card .q{{font-size:40px;font-weight:600;margin:22px 0 18px;letter-spacing:-.015em;line-height:1.22}}
.card .d{{font-size:27px;color:#6B727C;line-height:1.45}}
.card.none .k{{color:#6C7684}} .card.none{{border-top:6px solid #C9CFD8}}
.card.old .k{{color:#BC3E12}} .card.old{{border-top:6px solid #E0673A}}
.card.old .q{{color:#12161C}}

/* s3 */
.scores{{position:absolute;left:0;right:0;top:420px;display:flex;justify-content:center;align-items:center;gap:56px}}
.tile{{background:#fff;border-radius:22px;width:480px;padding:34px 0 38px;text-align:center;
  box-shadow:0 18px 50px rgba(18,22,28,.10)}}
.tile .l{{font-size:28px;color:#6B727C;font-weight:500}}
.tile .z{{font-size:150px;font-weight:600;line-height:1;margin-top:14px;letter-spacing:-.04em}}
.eq{{font-size:110px;color:#B8BEC7;font-weight:500}}

/* s4 */
.flow{{position:absolute;left:150px;right:150px;top:382px;display:grid;grid-template-columns:repeat(4,1fr);gap:26px}}
.step{{background:#fff;border-radius:18px;padding:30px 30px 34px;box-shadow:0 14px 40px rgba(18,22,28,.09);position:relative}}
.step .n{{width:48px;height:48px;border-radius:50%;background:#EDF2FA;color:#2B5CA8;font-weight:600;font-size:24px;
  display:flex;align-items:center;justify-content:center;margin-bottom:22px}}
.step .t{{font-size:31px;font-weight:600;line-height:1.2;letter-spacing:-.012em}}
.step .d{{font-size:24px;color:#6B727C;margin-top:12px;line-height:1.4}}
.step.ctl{{background:#EDF2FA}} .step.ctl .n{{background:#2B5CA8;color:#fff}}

/* windows */
.win{{position:absolute;left:170px;right:170px;top:92px;bottom:152px;background:#fff;border-radius:18px;
  box-shadow:0 26px 70px rgba(18,22,28,.14),0 2px 8px rgba(18,22,28,.05);overflow:hidden;display:flex;flex-direction:column}}
.bar{{height:62px;border-bottom:1px solid #ECEEF1;display:flex;align-items:center;justify-content:center;position:relative;
  font-size:22px;font-weight:600;flex:none}}
.dots{{position:absolute;left:24px;display:flex;gap:10px}}
.dots i{{width:15px;height:15px;border-radius:50%;display:block}}
.body{{flex:1;display:flex;min-height:0}}
.main{{flex:1;padding:36px 54px;position:relative}}
.side{{width:430px;background:#FAF9F6;border-left:1px solid #ECEEF1;padding:36px 34px}}
.pill{{display:table;margin:0 auto 32px;background:#EEEDE9;border-radius:999px;padding:12px 28px;font-size:25px;font-weight:600;color:#3A414B}}
.row{{display:grid;grid-template-columns:1.25fr .7fr .9fr;align-items:center;padding:20px 26px;border-radius:14px;
  margin-bottom:12px;font-size:29px;background:#F7F7F5}}
.row .who{{font-weight:600}}
.row .said{{font-family:PlexMono,monospace;font-size:31px;font-weight:600}}
.row .tag{{text-align:right;font-weight:600;font-size:25px}}
.row.fresh{{background:#E4F4EC}} .row.fresh .said,.row.fresh .tag{{color:#0B7A4F}}
.row.stale{{background:#FCE9E0}} .row.stale .said,.row.stale .tag{{color:#BC3E12}}
.row.absent .said,.row.absent .tag{{color:#8A929D}}
.row.ctl .who{{color:#2B5CA8}}
.side h4{{font-family:PlexMono,monospace;font-size:17px;letter-spacing:.14em;color:#8C929B;font-weight:600;margin-bottom:22px}}
.chk{{display:flex;gap:14px;align-items:flex-start;font-size:25px;line-height:1.35;margin-bottom:20px;color:#3A414B}}
.chk i{{flex:none;width:28px;height:28px;border-radius:7px;display:flex;align-items:center;justify-content:center;
  font-style:normal;font-size:19px;font-weight:700;color:#fff;margin-top:2px}}
.chk.y i{{background:#0B7A4F}} .chk.n i{{background:#BC3E12}}

/* s6 */
.srcs{{position:absolute;left:200px;right:200px;top:400px}}
.src{{display:grid;grid-template-columns:400px 1fr 180px;align-items:center;gap:34px;margin-bottom:34px}}
.src .lab{{font-size:32px;font-weight:600;line-height:1.1}}
.src .lab small{{display:block;font-size:22px;color:#8C929B;font-weight:500;margin-top:6px}}
.track{{height:56px;background:#E6E8EC;border-radius:12px;position:relative;overflow:hidden}}
.fill{{position:absolute;left:0;top:0;bottom:0;width:0;background:#3FA37A;border-radius:12px 0 0 12px}}
.zero{{position:absolute;left:20px;top:0;bottom:0;display:flex;align-items:center;font-size:23px;color:#8A929D;font-weight:600;white-space:nowrap}}
.track{{min-width:150px}}
.num{{font-size:26px;color:#8C929B;text-align:right}}
.num b{{font-size:54px;color:#12161C;font-weight:600;letter-spacing:-.02em}}
.num.hot b{{color:#0B7A4F}}
.num i{{font-style:normal;margin-left:6px}}
.legend6{{position:absolute;left:200px;top:352px;font-size:24px;color:#8C929B;font-weight:500}}
.legend6 b{{color:#0B7A4F}}

/* s7 */
.both{{position:absolute;left:260px;right:260px;top:398px;display:grid;grid-template-columns:1fr 1fr;gap:44px}}
.cell{{border-radius:20px;padding:34px 40px 38px;box-shadow:0 16px 46px rgba(18,22,28,.10)}}
.cell .who{{font-family:PlexMono,monospace;font-size:21px;letter-spacing:.12em;font-weight:600;color:#6B727C}}
.cell .on{{font-size:29px;margin:14px 0 20px;color:#3A414B;font-weight:500}}
.cell .v{{font-size:62px;font-weight:600;letter-spacing:-.02em}}
.cell .v small{{display:block;font-size:26px;font-weight:500;margin-top:8px;letter-spacing:0}}
.cell.f{{background:#E4F4EC}} .cell.f .v{{color:#0B7A4F}}
.cell.s{{background:#FCE9E0}} .cell.s .v{{color:#BC3E12}}

/* s8 */
.shotwrap{{position:absolute;inset:0;overflow:hidden;background:#FAF9F6}}
.shotwrap img{{position:absolute;left:0;top:0;width:100%;will-change:transform}}

/* s9 */
.end .logo{{top:250px}}
.end .tagline{{top:436px;font-size:38px;color:#3A414B}}
.links{{position:absolute;left:0;right:0;top:560px;text-align:center;font-size:31px;color:#2B5CA8;font-weight:600}}
.links span{{color:#B8BEC7;margin:0 18px}}
.stats{{position:absolute;left:0;right:0;top:660px;display:flex;justify-content:center;gap:56px;font-size:28px;color:#6B727C}}
.stats b{{color:#12161C;font-size:40px;font-weight:600;margin-right:10px}}
.fine{{position:absolute;left:0;right:0;top:790px;text-align:center;font-size:24px;color:#9AA0A8}}
</style></head><body><div class="grid"></div>

<svg width="0" height="0" style="position:absolute"><defs>
<symbol id="mark" viewBox="0 0 128 128">
  <circle cx="60" cy="64" r="44" fill="none" stroke="#2B5CA8" stroke-width="10"/>
  <path d="M60 36 V64 L79 76" fill="none" stroke="#12161C" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="98" cy="96" r="24" fill="#0B7A4F"/>
  <path d="M87 96 l7 7 l14 -15" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
</symbol></defs></svg>

<section class="scene" id="s1">
  <div class="logo" data-in="0.3"><svg><use href="#mark"/></svg><span class="word">time-to-index</span></div>
  <div class="tagline" data-in="1.2">How fast does a new fact reach AI search?</div>
</section>

<section class="scene" id="s2">
  <div class="h" data-in="0.3">When an AI searches the web,<em>two different things can go wrong.</em></div>
  <div class="pair">
    <div class="card none" data-in="2.0"><div class="k">IT FINDS NOTHING</div>
      <div class="q">“I couldn’t find that.”</div>
      <div class="d">Your AI says so. You notice. It’s fixable.</div></div>
    <div class="card old" data-in="3.8"><div class="k">IT FINDS YESTERDAY’S ANSWER</div>
      <div class="q">“The latest version is 0.12.14.”</div>
      <div class="d">It sounds sure. It’s out of date. Nobody notices.</div></div>
  </div>
  <div class="sub" style="top:846px" data-in="6.6">One is a shrug. The other is a confident mistake.</div>
</section>

<section class="scene" id="s3">
  <div class="h" data-in="0.3">Every benchmark I could find scores both<em>exactly the same: zero.</em></div>
  <div class="scores">
    <div class="tile" data-in="1.5"><div class="l">Found nothing</div><div class="z">0</div></div>
    <div class="eq" data-in="2.4">=</div>
    <div class="tile" data-in="2.9"><div class="l">Found the old answer</div><div class="z">0</div></div>
  </div>
  <div class="sub" style="top:808px" data-in="4.4">So the mistake that actually hurts you never shows up.</div>
</section>

<section class="scene" id="s4">
  <div class="h" data-in="0.3">So I built a clock for it.</div>
  <div class="sub" style="top:222px" data-in="0.9">It measures how long a brand-new fact takes to reach AI search.</div>
  <div class="flow">
    <div class="step" data-in="1.6"><div class="n">1</div><div class="t">Something new is published</div>
      <div class="d">a software release, a government notice</div></div>
    <div class="step" data-in="2.6"><div class="n">2</div><div class="t">Its publisher records the exact time</div>
      <div class="d">that’s time zero — not my guess</div></div>
    <div class="step" data-in="3.6"><div class="n">3</div><div class="t">Four AI search APIs are asked</div>
      <div class="d">“what’s the latest?” — five minutes later</div></div>
    <div class="step ctl" data-in="4.6"><div class="n">4</div><div class="t">The source is checked directly</div>
      <div class="d">so a slow index isn’t blamed for a slow publisher</div></div>
  </div>
  <div class="cap" data-in="6.6">Real APIs, real answers, every one saved. <b>{f["events"]} new facts tracked so far.</b></div>
</section>

<section class="scene" id="s5">
  <div class="win" data-in="0.2">
    <div class="bar"><div class="dots"><i style="background:#FF5F57"></i><i style="background:#FEBC2E"></i><i style="background:#28C840"></i></div>
      A real result · five minutes after a release went live</div>
    <div class="body">
      <div class="main">
        <div class="pill" data-in="0.9">What is the latest version of uv?</div>
        {rows}
      </div>
      <div class="side">
        <h4>WHAT HAPPENED</h4>
        <div class="chk y" data-in="2.0"><i>✓</i>Version {e(uv["version"])} was already live</div>
        <div class="chk y" data-in="2.9"><i>✓</i>{uv["n"]} AI search APIs were asked</div>
        <div class="chk n" data-in="5.8"><i>✗</i>None of them had it</div>
        <div class="chk n" data-in="6.7"><i>✗</i>{uv["stale_n"]} confidently gave the old version</div>
      </div>
    </div>
  </div>
  <div class="cap" data-in="7.8">None of the four had it — <b>and two confidently gave the old version.</b></div>
</section>

<section class="scene" id="s6">
  <div class="h" data-in="0.3">Where a fact is published<em>matters more than who you ask.</em></div>
  <div class="legend6" data-in="0.9">Answers that were <b>already current</b> five minutes after publication</div>
  <div class="srcs">{bars}</div>
  <div class="sub" style="top:900px" data-in="5.6">New government notices were often found in five minutes. New software releases: not once.</div>
</section>

<section class="scene" id="s7">
  <div class="h" data-in="0.3">The fastest API in the test was also<em>among the most out of date.</em></div>
  <div class="both">
    <div class="cell f" data-in="1.8"><div class="who">{e(f["arm"].upper())}</div>
      <div class="on">On a new government notice</div>
      <div class="v">✓ Current<small>found within five minutes</small></div></div>
    <div class="cell s" data-in="3.2"><div class="who">{e(f["arm"].upper())}</div>
      <div class="on">On the uv software release</div>
      <div class="v">✗ {e(f["arm_uv_said"])}<small>the old version, stated confidently</small></div></div>
  </div>
  <div class="sub" style="top:792px" data-in="5.0">Fastest to find new government notices — and tied with {e(tied)} for the most out-of-date answers.</div>
  <div class="cap" data-in="7.6">A single score would call it good or bad. <b>It’s both.</b></div>
</section>

<section class="scene" id="s8">
  <div class="win" data-in="0.2">
    <div class="bar"><div class="dots"><i style="background:#FF5F57"></i><i style="background:#FEBC2E"></i><i style="background:#28C840"></i></div>
      Playground — abhid1234.github.io/time-to-index</div>
    <div class="body"><div class="shotwrap"><img id="shot" src="{shot}"></div></div>
  </div>
  <div class="cap" data-in="1.4">Try it yourself — <b>flip the scoring rule and watch the ranking change.</b></div>
</section>

<section class="scene end" id="s9">
  <div class="logo" data-in="0.2"><svg><use href="#mark"/></svg><span class="word">time-to-index</span></div>
  <div class="tagline" data-in="0.9">A search answer can be fast — and wrong. Now you can tell which.</div>
  <div class="links" data-in="1.7">github.com/abhid1234/time-to-index<span>·</span>abhid1234.github.io/time-to-index</div>
  <div class="stats" data-in="2.5">
    <div><b>{f["events"]}</b>facts tracked</div><div><b>{f["graded"]}</b>graded answers</div>
    <div><b>{f["tests"]}</b>tests</div><div><b>MIT</b>open source</div></div>
  <div class="fine" data-in="3.3">An early, small sample. Every raw answer, the method and its limits are in the repo.</div>
</section>

<script>
const SCENES = {json.dumps(SCENES)};
const ease = p => (p = Math.min(1, Math.max(0, p)), p * p * (3 - 2 * p));
const FADE = 0.6;
const els = SCENES.map(([id]) => document.getElementById(id));
window.seek = (t) => {{
  SCENES.forEach(([id, t0, t1], i) => {{
    const el = els[i], local = t - t0, dur = t1 - t0;
    const first = i === 0, last = i === SCENES.length - 1;
    const inP = first ? 1 : ease(local / FADE);
    const outP = last ? 1 : ease((dur - local) / FADE);
    const v = (local < -0.001 || local > dur + 0.001) ? 0 : Math.min(inP, outP);
    el.style.opacity = v;
    el.style.visibility = v > 0.002 ? 'visible' : 'hidden';
    if (v <= 0.002) return;
    el.querySelectorAll('[data-in]').forEach(x => {{
      const p = ease((local - parseFloat(x.dataset.in)) / 0.7);
      x.style.opacity = p;
      x.style.transform = `translateY(${{(1 - p) * 18}}px)`;
    }});
    el.querySelectorAll('[data-grow]').forEach(x => {{
      const p = ease((local - parseFloat(x.dataset.grow)) / 1.5);
      x.style.width = (p * parseFloat(x.dataset.w)) + '%';
    }});
    el.querySelectorAll('[data-count]').forEach(x => {{
      const p = ease((local - parseFloat(x.dataset.at)) / 1.5);
      x.textContent = Math.round(p * parseFloat(x.dataset.count));
    }});
    if (id === 's8') {{
      const img = document.getElementById('shot');
      const box = img.parentElement.getBoundingClientRect();
      const travel = Math.max(0, img.getBoundingClientRect().height - box.height);
      const p = ease((local - 1.0) / (dur - 2.2));
      img.style.transformOrigin = '50% 30%';
      img.style.transform = `translateY(${{-p * travel}}px) scale(${{1 + 0.035 * p}})`;
    }}
  }});
}};
document.fonts.ready.then(() => {{ window.__ready = true; }});
</script></body></html>"""


def main() -> int:
    f = story.ledger_facts()
    story.check(f)
    BUILD.mkdir(exist_ok=True)
    shot = playground_shot()
    doc = BUILD / "short.html"
    doc.write_text(page(f, shot))

    ff = __import__("imageio_ffmpeg").get_ffmpeg_exe()
    raw = BUILD / "short-silent.mp4"
    enc = subprocess.Popen(
        [ff, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
         "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS), str(raw)], stdin=subprocess.PIPE)

    frames = int(round(DURATION * FPS))
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, args=["--hide-scrollbars",
                               "--force-color-profile=srgb"])
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pg.goto(doc.as_uri(), wait_until="load")
        pg.wait_for_function("window.__ready === true", timeout=20000)
        for i in range(frames):
            pg.evaluate("t => window.seek(t)", i / FPS)
            enc.stdin.write(pg.screenshot(type="jpeg", quality=94))
            if i % (FPS * 10) == 0:
                print(f"  {i / FPS:5.1f}s / {DURATION:.0f}s", flush=True)
        b.close()
    enc.stdin.close()
    enc.wait()
    print(f"wrote {raw}  ({frames} frames)")
    return mux(ff, raw)


def mux(ff: str, raw: pathlib.Path) -> int:
    """Music is the only audio: an original bed, levelled near the reference's -15 dB."""
    music = BUILD / "music.wav"
    subprocess.run([sys.executable, str(HERE / "make_music.py"), "--seconds", str(DURATION),
                    "--out", str(music)], check=True)
    out = HERE.parent / "time-to-index-short.mp4"
    fade = f"afade=t=in:d=1.2,afade=t=out:st={DURATION - 3.5}:d=3.5,loudnorm=I=-16:TP=-1.5:LRA=7"
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(raw), "-i", str(music),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", fade,
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest",
                    "-movflags", "+faststart", str(out)], check=True)
    small = HERE.parent / "time-to-index-short-720p.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(out), "-vf", "scale=1280:720",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "21", "-c:a", "copy",
                    "-movflags", "+faststart", str(small)], check=True)
    # VP9/Opus copy for browsers built without H.264 (open-source Chromium,
    # some Linux distributions). The page lists it after the MP4, so anything
    # that can play H.264 never downloads it.
    webm = HERE.parent / "time-to-index-short.webm"
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(small),
                    "-c:v", "libvpx-vp9", "-crf", "34", "-b:v", "0", "-row-mt", "1",
                    "-deadline", "good", "-cpu-used", "2",
                    "-c:a", "libopus", "-b:a", "128k", str(webm)], check=True)
    print(f"wrote {out}\nwrote {small}\nwrote {webm}")
    return publish(ff, out, small, webm)


def publish(ff: str, full: pathlib.Path, small: pathlib.Path, webm: pathlib.Path) -> int:
    """Copy the cut to where the repo serves it: the README links media/, the
    playground embeds docs/media/. Re-rendering is then one command, not four."""
    import shutil
    repo = HERE.parent.parent
    shutil.copy2(full, repo / "media" / "time-to-index-short.mp4")
    site = repo / "docs" / "media"
    site.mkdir(exist_ok=True)
    shutil.copy2(small, site / "time-to-index-short.mp4")
    shutil.copy2(webm, site / "time-to-index-short.webm")
    subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "3.8", "-i", str(small),
                    "-frames:v", "1", "-q:v", "3", str(site / "short-poster.jpg")], check=True)
    print(f"published to {repo / 'media'} and {site}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
