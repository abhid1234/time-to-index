"""Brave Search. GET https://api.search.brave.com/res/v1/web/search."""

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
            params={"q": question, "count": max_results, "freshness": "pd"},
        )


@register("brave")
def _factory() -> Brave:
    return Brave()
