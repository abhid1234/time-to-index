"""A local origin, so the whole pipeline can be exercised without a network.

Everything above this file is unit-tested, and a real bug still reached the
repo: `tti report` referenced an undefined name and the suite did not notice,
because nothing ran the CLI. Ruff caught it. Ruff will not catch the next one.

So: a threading HTTP server that serves the shapes this project actually
consumes -- registry documents with real `time` maps, pages in each render
posture, a robots.txt, and an endpoint that answers differently on alternate
requests. Collectors and the survey are pointed at it, and the CLI is driven
through its real argument parser.

Deliberately stdlib-only. A test harness that needs its own dependency is a
test harness people skip.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z")


PROSE = "A paragraph of perfectly ordinary documentation prose. " * 40
PRELOADS = "".join(f'<link rel="preload" href="/_/{i}.js" as="script">'
                   for i in range(60))

PAGES = {
    "/page/ssr": f"<html><head><title>t</title></head><body><h1>Release "
                 f"9.9.9</h1><p>{PROSE}</p></body></html>",
    "/page/shell": f"<html><head>{PRELOADS}</head><body>"
                   f'<div id="root"></div><script src="/b.js"></script></body></html>',
    "/page/metadata": f"<html><head>{PRELOADS}"
                      f'<script type="application/ld+json">'
                      f'{{"@type":"SoftwareApplication","name":"demo",'
                      f'"softwareVersion":"9.9.9","description":"{"d" * 300}"}}'
                      f"</script></head><body><div id=\"root\"></div></body></html>",
    "/page/next-ssr": f'<html><head>{PRELOADS}</head><body>'
                      f'<script>self.__next_f.push([1,"x"])</script>'
                      f"<article>{PROSE}</article></body></html>",
    "/page/hidden": f"<html><head>{PRELOADS}"
                    f'<script id="__NEXT_DATA__">{{"v":"9.9.9","pad":"{"x" * 40000}"}}'
                    f'</script></head><body><div id="__next"></div></body></html>",',
}

ROBOTS_OPEN = "User-agent: *\nAllow: /\n"
ROBOTS_BLOCK_AI = ("User-agent: *\nAllow: /\n\n"
                   "User-agent: GPTBot\nDisallow: /\n\n"
                   "User-agent: ClaudeBot\nDisallow: /\n")


class Origin(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.hits: dict[str, int] = {}
        self.robots = ROBOTS_OPEN
        self.npm: dict[str, dict] = {}
        self.pypi: dict[str, dict] = {}

    @property
    def base(self) -> str:
        host, port = self.server_address[:2]
        return f"http://127.0.0.1:{port}"

    def publish_npm(self, pkg: str, versions: list[tuple[str, float]]) -> None:
        """versions: [(version, unix_ts)], newest last."""
        self.npm[pkg] = {
            "dist-tags": {"latest": versions[-1][0]},
            "time": {v: _iso(t) for v, t in versions},
        }

    def publish_pypi(self, pkg: str, versions: list[tuple[str, float]]) -> None:
        self.pypi[pkg] = {
            "info": {"version": versions[-1][0]},
            "releases": {v: [{"upload_time_iso_8601": _iso(t)}] for v, t in versions},
        }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silence
        pass

    def _send(self, code: int, body: str, ctype="text/html; charset=utf-8"):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        srv: Origin = self.server  # type: ignore[assignment]
        path = self.path.split("?")[0]
        srv.hits[path] = srv.hits.get(path, 0) + 1

        if path == "/robots.txt":
            return self._send(200, srv.robots, "text/plain")
        if path.startswith("/npm/"):
            pkg = path[len("/npm/"):]
            doc = srv.npm.get(pkg)
            return self._send(200, json.dumps(doc), "application/json") if doc \
                else self._send(404, "{}", "application/json")
        if path.startswith("/pypi/"):
            pkg = path[len("/pypi/"):].removesuffix("/json")
            doc = srv.pypi.get(pkg)
            return self._send(200, json.dumps(doc), "application/json") if doc \
                else self._send(404, "{}", "application/json")
        if path == "/flaky":
            # Alternates: the exact failure that made single-fetch verdicts
            # untrustworthy in the real survey.
            n = srv.hits[path]
            return self._send(200, PAGES["/page/ssr"]) if n % 2 else self._send(404, "")
        if path == "/slow":
            time.sleep(3)
            return self._send(200, PAGES["/page/ssr"])
        if path in PAGES:
            return self._send(200, PAGES[path])
        return self._send(404, "not found")


@pytest.fixture
def origin():
    srv = Origin(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def wired(origin, monkeypatch, tmp_path):
    """Collectors pointed at the local origin, with a clean ledger."""
    from tti import config
    from tti.sources import npm as npm_mod
    from tti.sources import pypi as pypi_mod

    monkeypatch.setattr(npm_mod, "API", origin.base + "/npm/{pkg}")
    monkeypatch.setattr(pypi_mod, "API", origin.base + "/pypi/{pkg}/json")
    monkeypatch.setattr(config, "RUNS", tmp_path)
    monkeypatch.setitem(config._cache, "watchlist", {"npm": [], "pypi": []})
    return origin
