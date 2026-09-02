"""Tavily. POST https://api.tavily.com/search, bearer auth.

Verified against Tavily's published OpenAPI document and pricing page on
2026-09-02: `search_depth` is one of `basic`, `advanced`, `fast`,
`ultra-fast` (default `basic`); `max_results` default 5, max 20; `basic`,
`fast` and `ultra-fast` cost one credit, `advanced` two; pay-as-you-go is
$0.008 per credit. `include_answer` is off because this benchmark grades
retrieval, not summarisation. No `time_range` or date filter is sent.
"""

from __future__ import annotations

from .. import config, http
from . import register

ENDPOINT = "https://api.tavily.com/search"


class Tavily:
    name = "tavily"

    def modes(self) -> list[str]:
        return ["basic", "advanced", "fast", "ultra-fast"]

    def available(self) -> bool:
        return config.api_key("TAVILY_API_KEY") is not None

    def search(self, question: str, mode: str, *, max_results: int, max_chars: int) -> dict:
        key = config.api_key("TAVILY_API_KEY")
        if not key:
            raise RuntimeError("TAVILY_API_KEY not set")
        return http.post_json(
            ENDPOINT,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "query": question,
                "search_depth": mode,
                "max_results": max_results,
                "include_answer": False,   # we grade retrieval, not summarisation
                "include_raw_content": False,
            },
        )


@register("tavily")
def _factory() -> Tavily:
    return Tavily()
