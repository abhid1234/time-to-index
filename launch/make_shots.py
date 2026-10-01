"""Screenshot the playground for the launch post.

    python launch/make_shots.py      # -> launch/diagrams/playground-flip.png

Serves docs/ on a private port, runs the ladder, and captures the leaderboard
under each scoring rule, side by side: the one step the post asks readers to
try, shown the way they will see it.
"""
from __future__ import annotations

import functools
import http.server
import io
import pathlib
import threading

from PIL import Image
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
DOCS = HERE.parent / "docs"
OUT = HERE / "diagrams" / "playground-flip.png"
CHROME = "/opt/pw-browsers/chromium"
GROUND = (251, 250, 248)          # the playground's own --ground


def main() -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DOCS))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/playground.html"
    shots = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1280, "height": 900},
                                device_scale_factor=2, color_scheme="light")
        page.goto(url, wait_until="load")
        page.click("#play")
        page.wait_for_timeout(7000)            # six rungs at 0.9 s each
        card = page.locator(".results .card").first
        for button in ("#m-old", "#m-new"):
            page.click(button)
            page.wait_for_timeout(700)         # rows re-sort with a transition
            shots.append(Image.open(io.BytesIO(card.screenshot())).convert("RGB"))
        browser.close()
    server.shutdown()
    pad, gap = 56, 48
    h = max(s.height for s in shots)
    sheet = Image.new("RGB", (pad * 2 + gap + sum(s.width for s in shots), pad * 2 + h), GROUND)
    x = pad
    for s in shots:
        sheet.paste(s, (x, pad))
        x += s.width + gap
    sheet.save(OUT, optimize=True)
    print(f"wrote {OUT} {sheet.size}")


if __name__ == "__main__":
    main()
