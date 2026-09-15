"""Thumbnail built from the real page, not a mock of it.

A drawn approximation of a product always looks like a drawn approximation.
This screenshots the actual matrix at 2x -- the one visual that carries the
whole argument -- and sets the headline over it on the page's own background,
so the thumbnail, the video and the site are recognisably the same thing.

Composed in the browser rather than with PIL. The old version drew text with
PIL and needed TTF copies of the fonts sitting in a scratch directory; when
that directory went, so did the thumbnail's type. The page already self-hosts
woff2, so compositing in HTML uses the same files the site does and has no
dependency outside the repo.

The matrix used to bleed off the right edge on purpose, to read as an interface
continuing past the frame. It did not read that way: the cut landed mid-word
through the last column's STALE cell, which looks like a rendering fault rather
than a crop. It is scaled to fit whole now, and the t+72h column matters -- it
is the one where the wrong provider is *still* wrong.

Needs `python -m http.server 8890` running in docs/.
"""
from __future__ import annotations

import base64
import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
BUILD = HERE / "build"
URL = "http://127.0.0.1:8890/playground.html"
FONTS = "http://127.0.0.1:8890/fonts"
CHROME = "/opt/pw-browsers/chromium"
W, H = 1280, 720

PAGE = """
<style>
@font-face{{font-family:Newsreader;src:url({f}/newsreader-var.woff2)format("woff2");font-weight:400 700}}
@font-face{{font-family:"IBM Plex Sans";src:url({f}/plex-sans-var.woff2)format("woff2");font-weight:100 700}}
@font-face{{font-family:"IBM Plex Mono";src:url({f}/plex-mono-600.woff2)format("woff2");font-weight:600}}
*{{box-sizing:border-box}}
body{{margin:0;width:{w}px;height:{h}px;background:#FBFAF8;overflow:hidden;
  font-family:"IBM Plex Sans",sans-serif;-webkit-font-smoothing:antialiased}}
.wrap{{padding:58px 72px}}
.tag{{font-family:"IBM Plex Mono",monospace;font-size:18px;font-weight:600;
  letter-spacing:.14em;color:#2B5CA8;margin:0 0 14px}}
h1{{font-family:Newsreader,serif;font-size:58px;font-weight:500;line-height:1.08;
  letter-spacing:-.02em;color:#12161C;margin:0}}
.shot{{margin-top:34px;width:{inner}px}}
.shot img{{display:block;width:100%;height:auto}}
.cap{{margin-top:26px;font-size:25px;color:#464F5B}}
.cap b{{color:#BC3E12;font-weight:400}}
</style>
<div class="wrap">
  <p class="tag">TIME TO INDEX</p>
  <h1>A search index that is wrong<br>looks exactly like one that is fast.</h1>
  <div class="shot"><img src="{src}"></div>
  <p class="cap">Every benchmark scores both as zero. <b>This one doesn't.</b></p>
</div>
"""


def main() -> None:
    BUILD.mkdir(exist_ok=True)
    shot = BUILD / "thumb-matrix.png"
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, args=["--hide-scrollbars"])

        pg = b.new_page(viewport={"width": 1180, "height": 900},
                        device_scale_factor=2)
        pg.goto(URL, wait_until="load")
        pg.wait_for_timeout(1800)
        pg.click("#play")
        pg.wait_for_timeout(9000)          # let every rung resolve
        pg.locator(".matrixwrap").screenshot(path=str(shot))
        pg.close()

        src = "data:image/png;base64," + base64.b64encode(shot.read_bytes()).decode()
        card = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        card.set_content(PAGE.format(f=FONTS, w=W, h=H, inner=W - 144, src=src),
                         wait_until="load")
        card.wait_for_timeout(900)
        out = HERE / "thumbnail.png"
        card.screenshot(path=str(out))
        b.close()

    print(f"wrote {out}  {W}x{H}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
