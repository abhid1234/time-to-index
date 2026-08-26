"""Exa. POST https://api.exa.ai/search with an `x-api-key` header."""

from __future__ import annotations

from .. import config, http
from . import register

ENDPOINT = "https://api.exa.ai/search"


class Exa:
    name = "exa"

    def modes(self) -> list[str]:
        return ["auto", "keyword", "neural"]

    def available(self) -> bool:
        return config.api_key("EXA_API_KEY") is not None

    def search(self, question: str, mode: str, *, max_results: int, max_chars: int) -> dict:
        key = config.api_key("EXA_API_KEY")
        if not key:
            raise RuntimeError("EXA_API_KEY not set")
        return http.post_json(
            ENDPOINT,
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json={
                "query": question,
                "type": mode,
                "numResults": max_results,
                "contents": {"text": {"maxCharacters": max_chars}},
            },
        )


@register("exa")
def _factory() -> Exa:
    return Exa()
