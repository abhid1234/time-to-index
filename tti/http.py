"""One place for outbound HTTP, so retries, timeouts and the contact header
are consistent and every call site is auditable."""

from __future__ import annotations

import time
from typing import Any

import requests

from . import config

_session = requests.Session()


class HttpError(RuntimeError):
    pass


def get_json(url: str, *, headers: dict | None = None, params: dict | None = None,
             timeout: float = 20.0, retries: int = 2) -> Any:
    return _request("GET", url, headers=headers, params=params, timeout=timeout,
                    retries=retries).json()


def get_text(url: str, *, headers: dict | None = None, params: dict | None = None,
             timeout: float = 20.0, retries: int = 2) -> str:
    return _request("GET", url, headers=headers, params=params, timeout=timeout,
                    retries=retries).text


def post_json(url: str, *, json: dict, headers: dict | None = None,
              timeout: float = 45.0, retries: int = 1) -> Any:
    return _request("POST", url, json=json, headers=headers, timeout=timeout,
                    retries=retries).json()


def _request(method: str, url: str, *, retries: int = 2, **kw) -> requests.Response:
    h = {"User-Agent": config.contact_ua(), "Accept": "application/json"}
    h.update(kw.pop("headers", None) or {})
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = _session.request(method, url, headers=h, **kw)
            if r.status_code == 429 or 500 <= r.status_code < 600:
                raise HttpError(f"{r.status_code} {r.text[:200]}")
            if r.status_code >= 400:
                raise HttpError(f"{r.status_code} {r.text[:400]}")
            return r
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(1.5 * (2 ** attempt))
    raise HttpError(str(last))
