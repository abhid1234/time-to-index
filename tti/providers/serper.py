"""Serper (Google SERP relay). POST https://google.serper.dev/search.

Included as the control arm. Serper is a thin pass-through to Google's own
index, so it answers a question the other arms cannot: how much of a
provider's indexing lag is its own crawler, and how much is the open web
simply not having the document yet.
"""

from __future__ import annotations

from .. import config, http
from . import register

ENDPOINT = "https://google.serper.dev/search"


class Serper:
    name = "serper"

    def modes(self) -> list[str]:
        return ["search"]

    def available(self) -> bool:
        return config.api_key("SERPER_API_KEY") is not None

    def search(self, question: str, mode: str, *, max_results: int, max_chars: int) -> dict:
        key = config.api_key("SERPER_API_KEY")
        if not key:
            raise RuntimeError("SERPER_API_KEY not set")
        return http.post_json(
            ENDPOINT,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": question, "num": max_results},
        )


@register("serper")
def _factory() -> Serper:
    return Serper()
