"""The HTTP layer against hostile responses.

Nothing capped response size. A 200 MB chunked body took this process from
28 MB resident to 432 MB, and the existing caps in `control` and `routes`
truncate only after the whole thing is already in memory. On the small
always-on box this is meant to run on, that is the machine.

It is also the one failure mode an origin can trigger deliberately, and an
unattended job has nobody to notice it fell over.
"""
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from conftest import QuietServer

from tti import http as H

CHUNK = b"x" * 65_536


HITS: list[float] = []


class Hostile(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _chunked(self, first: bytes, n: int, ctype="text/html"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            if first:
                self.wfile.write(b"%x\r\n" % len(first) + first + b"\r\n")
            for _ in range(n):
                self.wfile.write(b"%x\r\n" % len(CHUNK) + CHUNK + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass          # the client hit the cap and hung up, which is the point

    def _plain(self, body: bytes, ctype="text/html", extra=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/huge":
            self._chunked(b"", 400)                    # ~26 MB
        elif self.path == "/json-huge":
            self._chunked(b'{"a":"', 200, "application/json")
        elif self.path == "/json-bad":
            self._chunked(b"{not json", 0, "application/json")
        elif self.path == "/json-ok":
            self._plain(b'{"ok": true}', "application/json")
        elif self.path == "/declared-huge":
            self.send_response(200)
            self.send_header("Content-Length", "50000000")
            self.end_headers()
        elif self.path == "/charset-lie":
            self._plain("cafe naive".encode("latin-1"),
                        "text/html; charset=utf-8")
        elif self.path == "/small":
            self._plain(b"<html><body>fine</body></html>")
        elif self.path == "/rate-limited":
            # 429 with Retry-After on the first call, 200 after.
            HITS.append(time.time())
            if len(HITS) == 1:
                self.send_response(429)
                self.send_header("Retry-After", "2")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
            else:
                self._plain(b'{"ok": true}', "application/json")
        else:
            self._plain(b"", "text/plain")


@pytest.fixture
def hostile():
    srv = QuietServer(("127.0.0.1", 0), Hostile)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_huge_body_is_capped_not_loaded(hostile):
    body = H.get_text(hostile + "/huge", timeout=60, retries=0)
    assert len(body) <= H.MAX_RESPONSE_BYTES
    assert len(body) >= H.MAX_RESPONSE_BYTES - H._CHUNK


def test_the_cap_is_honoured_per_call(hostile):
    body = H.get_text(hostile + "/huge", timeout=60, retries=0, max_bytes=100_000)
    assert len(body) <= 100_000


def test_an_oversized_declared_length_is_refused_before_reading(hostile):
    """A server that announces 50 MB is taken at its word and hung up on,
    rather than read to find out."""
    with pytest.raises(H.ResponseTooLarge, match="declared Content-Length"):
        H.get_text(hostile + "/declared-huge", timeout=20, retries=0)


def test_oversized_json_is_refused_not_truncated(hostile):
    """Truncating JSON is worse than failing on it. At best it is a parse
    error; at worst it yields a *shorter valid document* — a registry
    response missing its newest entries, which reads as a quiet day rather
    than as a failure."""
    with pytest.raises(H.ResponseTooLarge):
        H.get_json(hostile + "/json-huge", timeout=60, retries=0)


def test_malformed_json_raises_the_module_error_type(hostile):
    """Every failure from this module is one exception type. A caller that
    catches HttpError and not JSONDecodeError would otherwise crash on a
    malformed body while handling every other failure cleanly."""
    with pytest.raises(H.HttpError, match="not valid JSON"):
        H.get_json(hostile + "/json-bad", timeout=20, retries=0)


def test_response_too_large_is_an_http_error(hostile):
    """A subclass, so existing `except HttpError` sites keep working: an
    oversized response is a failed fetch like any other."""
    assert issubclass(H.ResponseTooLarge, H.HttpError)
    with pytest.raises(H.HttpError):
        H.get_json(hostile + "/json-huge", timeout=60, retries=0)


def test_a_lying_charset_degrades_instead_of_raising(hostile):
    """Declared utf-8, sent latin-1. Bad bytes are replaced, never raised —
    one mis-encoded character must not discard an otherwise usable page."""
    assert H.get_text(hostile + "/charset-lie", timeout=10, retries=0)


def test_normal_responses_are_unaffected(hostile):
    assert H.get_json(hostile + "/json-ok", timeout=10, retries=0) == {"ok": True}
    assert "fine" in H.get_text(hostile + "/small", timeout=10, retries=0)
    assert H.get_bytes(hostile + "/small", timeout=10, retries=0).startswith(b"<html")


def test_raw_get_still_exposes_status_and_text(hostile):
    """`tti crawlability` needs the status code, and the capped read must be
    invisible to it beyond the truncation flag."""
    r = H.raw_get(hostile + "/huge", timeout=60, retries=0, max_bytes=200_000)
    assert r.status_code == 200
    assert len(r.text) <= 200_000
    assert r.tti_truncated is True
    small = H.raw_get(hostile + "/small", timeout=10, retries=0)
    assert small.tti_truncated is False and "fine" in small.text


def test_a_429_with_retry_after_is_retried_after_that_long(hostile):
    HITS.clear()
    assert H.get_json(hostile + "/rate-limited", retries=1) == {"ok": True}
    assert len(HITS) == 2
    assert 1.9 <= HITS[1] - HITS[0] < 2.7          # the header's 2s, not the 1.5s backoff


def test_retry_after_is_bounded_and_falls_back_on_dates():
    assert H._retry_delay(0, None) == 1.5
    assert H._retry_delay(1, None) == 3.0
    assert H._retry_delay(0, "4") == 4.0
    assert H._retry_delay(0, "3600") == H.RETRY_AFTER_CAP
    assert H._retry_delay(0, "Wed, 21 Oct 2026 07:28:00 GMT") == 1.5
