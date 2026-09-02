"""Brave Search. GET https://api.search.brave.com/res/v1/web/search.

Verified against Brave's published query reference and pricing page on
2026-09-02: `X-Subscription-Token` header, `q`, `count` (max 20), results
under `web.results[]` with `description`; $5 per 1,000 requests.

Until that date this adapter sent `freshness=pd`, Brave's last-24-hours
filter. No other arm carried a recency filter, and nothing in the repository
said why this one did. It cut both ways: at the short rungs it removed stale
competitors from the result set, and at 72 hours it would have excluded the
correct document even when Brave had indexed it. Every arm now receives the
same request shape with no vendor-specific filters. A recency filter is a
legitimate product feature; it is not a legitimate difference between arms
in a freshness benchmark.
"""

from __future__ import annotations

from .. import config, http
from . import register

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class Brave:
    name = "brave"

    def modes(self) -> list[str]:
        return ["web"]

    def available(self) -> bool:
        return config.api_key("BRAVE_API_KEY") is not None

    def search(self, question: str, mode: str, *, max_results: int, max_chars: int) -> dict:
        key = config.api_key("BRAVE_API_KEY")
        if not key:
            raise RuntimeError("BRAVE_API_KEY not set")
        return http.get_json(
            ENDPOINT,
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            params={"q": question, "count": max_results},
        )


@register("brave")
def _factory() -> Brave:
    return Brave()
