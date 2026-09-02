"""One place for outbound HTTP, so retries, timeouts and the contact header
are consistent and every call site is auditable."""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from . import config

_session = requests.Session()

# Nothing capped response size, so a broken or hostile origin could hand this
# process as much memory as it felt like. Measured: a 200 MB chunked response
# took RSS from 28 MB to 432 MB, and the existing caps in `control` and
# `routes` truncate only *after* the whole body is already resident. On the
# small always-on box this is meant to run on, that is the whole machine.
#
# 8 MB covers the largest thing legitimately fetched (a sitemap) with room to
# spare; the origin control caps itself at 2 MB on top of this.
MAX_RESPONSE_BYTES = 8_000_000

# Read in chunks small enough that the cap is enforced early rather than
# after one enormous read.
_CHUNK = 65_536


class HttpError(RuntimeError):
    """Any failed request. Callers catch this and record it as an error."""


class ResponseTooLarge(HttpError):
    """The body exceeded the cap, where truncation would corrupt the result.

    A subclass, so existing `except HttpError` sites keep working: an
    oversized response is a failed fetch like any other, and the distinction
    only matters where a caller wants to say so specifically.
    """

# Global retry ceiling. `tti doctor` lowers it to zero: a reachability check
# that spends four seconds of exponential backoff per unreachable host takes
# minutes to tell you something it knew immediately, and a diagnostic nobody
# waits for is a diagnostic nobody runs.
_max_retries: int | None = None


def set_retry_ceiling(n: int | None) -> None:
    global _max_retries
    _max_retries = n


def _read_capped(resp: requests.Response, max_bytes: int) -> tuple[bytes, bool]:
    """Body up to `max_bytes`, plus whether it was cut short.

    A declared Content-Length over the cap is refused before a byte is read;
    an undeclared or lying one is caught by the running total.
    """
    declared = resp.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        resp.close()
        raise ResponseTooLarge(
            f"declared Content-Length {int(declared):,} exceeds the "
            f"{max_bytes:,}-byte cap")
    buf = bytearray()
    for chunk in resp.iter_content(_CHUNK):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            resp.close()
            return bytes(buf[:max_bytes]), True
    return bytes(buf), False


def get_json_sized(url: str, *, headers: dict | None = None,
                   params: dict | None = None, timeout: float = 20.0,
                   retries: int = 2,
                   max_bytes: int = MAX_RESPONSE_BYTES) -> tuple[Any, int]:
    """Parsed JSON and the body size in bytes, refused if oversized.

    The size exists so a caller with a per-source bound can notice a document
    creeping toward it. Registry packuments only ever grow -- every release
    appends -- and the failure mode without this is a subject that works for
    a year and then starts erroring on the day it crosses the line, with
    nothing in any earlier output having said it was close.

    Truncating JSON produces a parse error at best and, worse, could produce
    a *shorter valid document* -- a registry response missing its newest
    entries, which would read as a quiet day rather than as a failure.
    """
    resp = _request("GET", url, headers=headers, params=params, timeout=timeout,
                    retries=retries, stream=True)
    raw, truncated = _read_capped(resp, max_bytes)
    if truncated:
        raise ResponseTooLarge(f"body exceeded the {max_bytes:,}-byte cap")
    try:
        return json.loads(raw.decode("utf-8", "replace")), len(raw)
    except json.JSONDecodeError as exc:
        # Wrapped so every failure from this module is one exception type.
        # Collectors catch broadly, but a caller that catches HttpError and
        # not JSONDecodeError would otherwise crash on a malformed body while
        # handling every other failure cleanly.
        raise HttpError(f"response was not valid JSON: {exc}") from exc


def get_json(url: str, *, headers: dict | None = None, params: dict | None = None,
             timeout: float = 20.0, retries: int = 2,
             max_bytes: int = MAX_RESPONSE_BYTES) -> Any:
    """Parsed JSON, refused rather than truncated if oversized."""
    return get_json_sized(url, headers=headers, params=params, timeout=timeout,
                          retries=retries, max_bytes=max_bytes)[0]


def get_text(url: str, *, headers: dict | None = None, params: dict | None = None,
             timeout: float = 20.0, retries: int = 2,
             max_bytes: int = MAX_RESPONSE_BYTES) -> str:
    """Decoded body, truncated at the cap.

    Truncation is right here and wrong for JSON: a page cut off at 8 MB is
    still classifiable, and refusing it would discard a real observation over
    a page's size.
    """
    resp = _request("GET", url, headers=headers, params=params, timeout=timeout,
                    retries=retries, stream=True)
    raw, _ = _read_capped(resp, max_bytes)
    return raw.decode(resp.encoding or "utf-8", "replace")


def post_json(url: str, *, json: dict, headers: dict | None = None,
              timeout: float = 45.0, retries: int = 1) -> Any:
    return _request("POST", url, json=json, headers=headers, timeout=timeout,
                    retries=retries).json()


def get_bytes(url: str, *, headers: dict | None = None, timeout: float = 20.0,
              retries: int = 1, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    """Raw body, for content whose encoding we must decide ourselves.

    Sitemaps are the reason. Large sites commonly serve `sitemap.xml.gz`, and
    reading that through a text decoder produces mojibake that parses as
    nothing -- which looks exactly like a site that declares no routes.
    """
    resp = _request("GET", url, headers=headers, timeout=timeout,
                    retries=retries, stream=True)
    raw, _ = _read_capped(resp, max_bytes)
    return raw


def raw_get(url: str, *, headers: dict | None = None, timeout: float = 25.0,
            retries: int = 1,
            max_bytes: int = MAX_RESPONSE_BYTES) -> requests.Response:
    """A GET whose status code the caller inspects.

    `get_text` raises on a non-200, which is right for collectors and wrong
    for `tti crawlability`: there, a 404 or a proxy error must be reported as
    a failed fetch rather than turned into a judgement about the page.
    """
    resp = _request("GET", url, headers=headers, timeout=timeout, retries=retries,
                    allow_error_status=True, stream=True)
    raw, truncated = _read_capped(resp, max_bytes)
    # Populate the cached body so `.text` and `.content` work normally from
    # here on, without the caller needing to know the read was capped.
    resp._content = raw
    resp._content_consumed = True
    resp.tti_truncated = truncated
    return resp


# The longest a Retry-After header is obeyed for. A provider that says "come
# back in an hour" gets an ERROR row now, not a probe run stalled for an hour
# with every other arm's rung slipping behind it.
RETRY_AFTER_CAP = 10.0


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    """Seconds to wait before the next attempt.

    Exponential backoff by default. On a 429 that carries Retry-After in
    seconds, that number instead, capped, because the vendor knows its own
    window and guessing past it just spends the retry.
    """
    if retry_after:
        try:
            return max(0.0, min(float(retry_after), RETRY_AFTER_CAP))
        except ValueError:
            pass                       # an HTTP-date form; fall back to backoff
    return 1.5 * (2 ** attempt)


def _request(method: str, url: str, *, retries: int = 2,
             allow_error_status: bool = False, **kw) -> requests.Response:
    if _max_retries is not None:
        retries = min(retries, _max_retries)
    h = {"User-Agent": config.contact_ua(), "Accept": "application/json"}
    h.update(kw.pop("headers", None) or {})
    last: Exception | None = None
    for attempt in range(retries + 1):
        retry_after = None
        try:
            r = _session.request(method, url, headers=h, **kw)
            if not allow_error_status and (r.status_code == 429
                                           or 500 <= r.status_code < 600):
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                raise HttpError(f"{r.status_code} {r.text[:200]}")
            if r.status_code >= 400 and not allow_error_status:
                raise HttpError(f"{r.status_code} {r.text[:400]}")
            return r
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(_retry_delay(attempt, retry_after))
    raise HttpError(str(last))
