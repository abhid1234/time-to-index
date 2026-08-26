"""Parallel Search API.

POST https://api.parallel.ai/v1beta/search with an `x-api-key` header.
The request carries an `objective` (what the caller is trying to learn) and
`search_queries` (literal strings to run), which is a different contract from
every other provider here -- the API is built to be called by an agent that
knows its own goal, not by a person typing keywords.

That distinction matters for this benchmark. Sending only `objective` would
let Parallel rewrite the query internally and would compare its rewriter
against other providers' raw matching. Sending only the literal query would
throw away the thing the product is for. We send both, identically shaped for
every event, and record which was used.
"""

from __future__ import annotations

from .. import config, http
from . import register

ENDPOINT = "https://api.parallel.ai/v1beta/search"


class Parallel:
    name = "parallel"

    def modes(self) -> list[str]:
        return ["base", "pro", "fast", "turbo"]

    def available(self) -> bool:
        return config.api_key("PARALLEL_API_KEY") is not None

    def search(self, question: str, mode: str, *, max_results: int, max_chars: int) -> dict:
        key = config.api_key("PARALLEL_API_KEY")
        if not key:
            raise RuntimeError("PARALLEL_API_KEY not set")
        return http.post_json(
            ENDPOINT,
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json={
                "objective": question,
                "search_queries": [question],
                "processor": mode,
                "max_results": max_results,
                "max_chars_per_result": max_chars,
            },
        )


@register("parallel")
def _factory() -> Parallel:
    return Parallel()
