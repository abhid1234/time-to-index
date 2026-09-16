"""Drive the live playground and record it.

This is a screen recording of the real page, not a slide deck about it. The
first version of this launch was a deck read by a synthesiser and it was
rightly thrown out: the product *is* the argument, so the video has to be the
product moving.

Three things make a headless capture look deliberate rather than robotic:

  * an injected cursor, because a page where things click themselves reads as
    a bug;
  * smoothstep easing on every move and scroll, because linear motion is the
    single clearest tell that nothing human is driving;
  * beats padded to a budget computed from the narration (budgets.py), so the
    picture never runs out from under the words and never sits still for a
    minute waiting for them.

Writes build/screen-raw.mp4 and build/beats.json. Needs
`python -m http.server 8890` running in docs/.
"""
from __future__ import annotations

import json
import math
import pathlib
import shutil
import sys
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
BUILD = HERE / "build"
URL = "http://127.0.0.1:8890/playground.html"
CHROME = "/opt/pw-browsers/chromium"

# Recorded at 1440x810 and upscaled to 1920x1080 at mux time. Recording at
# 1080 directly makes the page's own type render small relative to the frame;
# this way the layout is sized for a 1440px viewport and the whole frame is
# the page.
VW, VH = 1440, 810

CURSOR = """
(() => {
  const c = document.createElement('div');
  c.id = '__cur';
  c.style.cssText = `position:fixed;left:0;top:0;width:22px;height:22px;
    z-index:2147483647;pointer-events:none;will-change:transform;
    transform:translate(-100px,-100px)`;
  c.innerHTML = `<svg viewBox="0 0 22 22" width="22" height="22">
    <path d="M3 2 L3 17 L7.2 13.2 L10 19.4 L12.6 18.2 L9.9 12.2 L15.4 12z"
      fill="#12161C" stroke="#fff" stroke-width="1.3" stroke-linejoin="round"/>
  </svg>`;
  document.body.appendChild(c);
  window.__moveCur = (x, y) => {
    c.style.transform = `translate(${x}px, ${y}px)`;
  };
  window.__ripple = (x, y) => {
    const r = document.createElement('div');
    r.style.cssText = `position:fixed;left:${x - 13}px;top:${y - 13}px;
      width:26px;height:26px;border-radius:50%;z-index:2147483646;
      pointer-events:none;border:2px solid #2B5CA8;opacity:.85;
      transition:transform .45s ease-out, opacity .45s ease-out`;
    document.body.appendChild(r);
    requestAnimationFrame(() => {
      r.style.transform = 'scale(2.4)';
      r.style.opacity = '0';
    });
    setTimeout(() => r.remove(), 500);
  };
})()
"""


class Cam:
    """A cursor and a viewport, both of which move like something is holding them."""

    def __init__(self, page):
        self.pg = page
        self.x, self.y = VW * 0.5, VH * 0.62

    @staticmethod
    def _ease(p: float) -> float:
        return p * p * (3 - 2 * p)          # smoothstep

    def move(self, x: float, y: float, ms: int = 620) -> None:
        x0, y0 = self.x, self.y
        steps = max(2, int(ms / 16))
        for i in range(1, steps + 1):
            p = self._ease(i / steps)
            cx, cy = x0 + (x - x0) * p, y0 + (y - y0) * p
            self.pg.evaluate("([x,y]) => window.__moveCur(x,y)", [cx, cy])
            time.sleep(0.016)
        self.x, self.y = x, y

    def to(self, selector: str, ms: int = 620, dx: float = 0, dy: float = 0):
        loc = self.pg.locator(selector).first
        box = loc.bounding_box()
        if not box:
            return
        # A bounding box is viewport-relative. Pointing at a row that has
        # scrolled off sends the cursor to a clamped edge position -- it once
        # sat in the middle of the legend while the narration named a matrix
        # cell. Bring it into view first, gently, then point.
        top, bot = box["y"], box["y"] + box["height"]
        if top < 90 or bot > VH - 70:
            want = top - (VH * 0.42)
            self.pg.evaluate(
                """(dy) => new Promise(res => {
                    const y0 = window.scrollY, y1 = y0 + dy;
                    const t0 = performance.now(), ms = 620;
                    const ease = p => p * p * (3 - 2 * p);
                    (function step(now) {
                      const p = Math.min(1, (now - t0) / ms);
                      window.scrollTo(0, y0 + (y1 - y0) * ease(p));
                      p < 1 ? requestAnimationFrame(step) : res();
                    })(performance.now());
                })""", want)
            time.sleep(0.75)
            box = loc.bounding_box()
            if not box:
                return
        self.move(box["x"] + box["width"] / 2 + dx,
                  box["y"] + box["height"] / 2 + dy, ms)

    def click(self, selector: str, ms: int = 620, settle: int = 320):
        self.to(selector, ms)
        self.pg.evaluate("([x,y]) => window.__ripple(x,y)", [self.x, self.y])
        time.sleep(0.12)
        self.pg.locator(selector).first.click()
        self.hold(settle)

    def scroll_to(self, selector: str, ms: int = 900, offset: int = -110):
        """requestAnimationFrame scroll, not scrollIntoView.

        scrollIntoView({behavior:'smooth'}) is the browser's curve, not ours,
        and it finishes whenever it likes -- which desynchronises every beat
        after it.
        """
        self.pg.evaluate(
            """([sel, ms, off]) => new Promise(res => {
                const el = document.querySelector(sel);
                if (!el) return res();
                const y0 = window.scrollY;
                const y1 = y0 + el.getBoundingClientRect().top + off;
                const t0 = performance.now();
                const ease = p => p * p * (3 - 2 * p);
                (function step(now) {
                  const p = Math.min(1, (now - t0) / ms);
                  window.scrollTo(0, y0 + (y1 - y0) * ease(p));
                  p < 1 ? requestAnimationFrame(step) : res();
                })(performance.now());
            })""", [selector, ms, offset])
        time.sleep(ms / 1000 + 0.1)

    def hold(self, ms: int) -> None:
        time.sleep(ms / 1000)


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    budgets = json.loads((BUILD / "budgets.json").read_text())
    vid = BUILD / "raw"
    shutil.rmtree(vid, ignore_errors=True)
    vid.mkdir(parents=True)

    marks: list[dict] = []

    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME,
                               args=["--hide-scrollbars", "--disable-gpu-vsync",
                                     "--font-render-hinting=none"])
        ctx = b.new_context(viewport={"width": VW, "height": VH},
                            record_video_dir=str(vid),
                            record_video_size={"width": VW, "height": VH})
        pg = ctx.new_page()
        pg.goto(URL, wait_until="load")
        pg.wait_for_timeout(1500)
        pg.evaluate(CURSOR)
        cam = Cam(pg)

        t0 = time.time()

        def now() -> float:
            return time.time() - t0

        state = {"beat": None, "started": 0.0}

        def pad() -> None:
            """Hold the picture until the current beat has used its budget."""
            if state["beat"] is None:
                return
            want = budgets.get(state["beat"], 0.0)
            left = want - (now() - state["started"])
            if left > 0:
                time.sleep(left)

        def beat(name: str) -> None:
            pad()
            state["beat"], state["started"] = name, now()
            marks.append({"beat": name, "t": round(now(), 2)})
            print(f"  {now():7.1f}s  {name}")

        # --- the argument, in the order the page makes it -------------------
        beat("hero")
        cam.move(VW * 0.44, VH * 0.46, 900)
        cam.hold(900)
        cam.scroll_to(".herogrid", 900)
        cam.hold(1200)

        beat("ground_truth")
        cam.scroll_to("#s1", 950)
        cam.hold(1400)
        cam.to("#lv-ver", 800)
        cam.hold(1600)

        beat("ladder_run")
        cam.scroll_to("#s2", 900)
        cam.hold(900)
        cam.click("#play", ms=700, settle=1200)
        cam.hold(2400)

        beat("matrix_read")
        cam.scroll_to(".matrixwrap", 800, offset=-150)
        cam.hold(1600)
        cam.to("#body tr:last-child td:nth-child(2)", 900)
        cam.hold(2200)

        beat("scoring_old")
        cam.scroll_to("#s3", 900)
        cam.hold(1500)
        cam.to(".board", 800)
        cam.hold(1800)

        beat("scoring_new")
        cam.click("#m-new", ms=800, settle=1600)
        cam.hold(2400)

        beat("brackets")
        cam.scroll_to("#brackets", 850, offset=-200)
        cam.hold(1800)

        beat("takeaway")
        cam.scroll_to(".takeaway", 850)
        cam.hold(1300)

        # The Artificial Analysis paragraph is a distinct claim and deserves
        # its own shot; pinned to the end of the takeaway beat it meant fifty
        # seconds of narration over one motionless panel.
        beat("aa_note")
        cam.scroll_to(".takeaway p.aa", 800, offset=-200)
        cam.hold(1400)

        # --- the real measured data -----------------------------------------
        beat("measured")
        cam.scroll_to("#meas", 950)
        cam.hold(1500)

        beat("measured_punch")
        cam.hold(1800)

        # This beat carries four lines now -- the control, both stale arms,
        # and the bound on all of it. Left as two clicks it was six seconds of
        # motion under a minute of speech, which reads as the recording having
        # frozen. The event buttons are newest-first and the two newest are the
        # events that produced a STALE, so walking them is both the
        # illustration and the pacing.
        beat("measured_events")
        cam.click("#meas-evs button:nth-child(2)", ms=700, settle=1600)
        cam.scroll_to("#meas-head", 800, offset=-150)
        cam.hold(2400)
        cam.to("#meas-body tr:nth-child(5) td:nth-child(2)", ms=900)   # origin FRESH
        cam.hold(4200)
        cam.to("#meas-body tr:nth-child(2) td:nth-child(2)", ms=900)   # exa STALE
        cam.hold(4600)
        cam.to("#meas-body tr:nth-child(3) td:nth-child(2)", ms=800)   # parallel STALE
        cam.hold(4200)
        cam.to("#meas-body tr:nth-child(1) td:nth-child(2)", ms=800)   # brave, nothing
        cam.hold(2600)
        cam.to("#meas-body tr:nth-child(4) td:nth-child(2)", ms=700)   # parallel/fast
        cam.hold(3000)

        # The uv row is one event. This beat is the claim that it is not the
        # only one, so it walks the other two events that produced a STALE
        # rather than holding on the first.
        beat("measured_scope")
        cam.scroll_to("#meas-evs", 800, offset=-170)
        cam.hold(1000)
        cam.click("#meas-evs button:nth-child(4)", ms=800, settle=1500)  # workers-types
        cam.scroll_to("#meas-head", 750, offset=-150)
        cam.hold(1400)
        cam.to("#meas-body tr:nth-child(1) td:nth-child(2)", ms=900)     # brave STALE
        cam.hold(3400)
        cam.scroll_to("#meas-evs", 750, offset=-170)
        cam.click("#meas-evs button:nth-child(5)", ms=800, settle=1400)  # sentry
        cam.scroll_to("#meas-head", 750, offset=-150)
        cam.hold(1400)
        cam.to("#meas-body tr:nth-child(3) td:nth-child(2)", ms=900)     # parallel STALE
        cam.hold(3200)
        cam.scroll_to("#meas-tot", 850, offset=-260)
        cam.hold(2800)

        beat("legend")
        cam.scroll_to("#meas-legend", 700)
        cam.hold(1600)

        beat("end")
        cam.scroll_to("header", 1100)
        cam.hold(1300)

        pad()
        total = now()
        ctx.close()
        b.close()

    src = next(vid.glob("*.webm"))
    out = BUILD / "screen-raw.webm"
    if out.exists():
        out.unlink()
    src.rename(out)
    (BUILD / "beats.json").write_text(json.dumps(marks, indent=2))
    print(f"\nwrote {out}  ({out.stat().st_size / 1e6:.1f} MB, {total:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
