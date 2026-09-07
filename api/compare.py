"""HTTP wrapper around `tti.live.compare`, for the demo page.

Deliberately thin: parse, delegate, set the cache header, serialise. Every
decision that matters -- which subjects are allowed, what is asked, how an
answer is graded, what a failed arm records -- lives in `tti/live.py` where
it can be tested without a socket.

The cache header is the cost control. Vercel serves a cached response from
the edge without invoking this function at all, so a page being read by fifty
people costs one fan-out rather than fifty. Removing it turns a public URL
into a way to spend someone else's provider budget.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import live  # noqa: E402

# The demo page is served from GitHub Pages, a different origin, so the
# browser needs this to read the response at all. Narrow by default; set
# TTI_ALLOW_ORIGIN to "*" only if you want anyone's page to spend your cap.
ALLOW_ORIGIN = os.environ.get(
    "TTI_ALLOW_ORIGIN", "https://abhid1234.github.io")


class handler(BaseHTTPRequestHandler):  # noqa: N801  (Vercel requires this name)

    def _send(self, status: int, body: dict, cache: int = 0) -> None:
        raw = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)
        self.send_header("Vary", "Origin")
        if cache:
            self.send_header(
                "Cache-Control",
                f"public, s-maxage={cache}, stale-while-revalidate={cache * 4}")
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        params = parse_qs(urlparse(self.path).query)
        pkg = (params.get("pkg") or ["astro"])[0].strip().lower()

        try:
            result = live.compare(pkg)
        except ValueError as exc:
            # A rejected subject is the allow-list working, not a fault.
            self._send(400, {
                "error": str(exc),
                "allowed": list(live.ALLOWED),
            })
            return
        except Exception as exc:  # noqa: BLE001
            # The traceback goes to the function log, never to the caller: it
            # names internal paths and, on an auth failure, sometimes the
            # header that failed.
            traceback.print_exc()
            self._send(500, {
                "error": f"{type(exc).__name__} while comparing {pkg!r}",
            })
            return

        self._send(200, result, cache=result["cache_seconds"])
