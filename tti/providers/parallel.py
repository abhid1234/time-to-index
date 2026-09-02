"""Parallel Search API, v1.

POST https://api.parallel.ai/v1/search with an `x-api-key` header. Verified
against the published OpenAPI document and the beta-to-GA migration guide on
2026-09-02; the previous version of this file targeted the retired
`/v1beta/search` contract and would have received 403 "invalid processor"
on every call.

The request carries an `objective` (what the caller is trying to learn) and
`search_queries` (literal strings to run), which is a different contract from
every other provider here -- the API is built to be called by an agent that
knows its own goal, not by a person typing keywords.

That distinction matters for this benchmark, and it is resolved in the
direction of comparability, not in Parallel's favour. Sending only
`objective` would let Parallel rewrite the query internally and compare its
rewriter against other providers' raw matching. Sending only the literal
question would throw away the thing the product is for. We send both, and
both are the same natural-language question every other arm receives.

Parallel's guidance is that `search_queries` should be concise, 3-6 keywords
each. Ours is a twelve-word sentence. It is within the hard limits (five
queries, 200 characters each) and it is deliberately not rewritten, because
the moment this harness hand-tunes one vendor's query it is measuring its own
tuning. A Parallel-optimal query would very likely do better than what this
benchmark sends. That is stated here so nobody reads the number as their
ceiling.

Modes are `turbo`, `fast`, `basic`, `advanced`. `base` and `pro` are Task API
processors and are not valid here.
"""

from __future__ import annotations

from .. import config, http
from . import register

ENDPOINT = "https://api.parallel.ai/v1/search"

# From the published pricing page: turbo and fast $1 per 1,000 requests,
# basic and advanced $5, ten results included in each. Kept here as the
# authoritative list; data/providers.yaml carries the prices.
MODES = ("turbo", "fast", "basic", "advanced")


class Parallel:
    name = "parallel"

    def modes(self) -> list[str]:
        return list(MODES)

    def available(self) -> bool:
        return config.api_key("PARALLEL_API_KEY") is not None

    def search(self, question: str, mode: str, *, max_results: int, max_chars: int) -> dict:
        key = config.api_key("PARALLEL_API_KEY")
        if not key:
            raise RuntimeError("PARALLEL_API_KEY not set")
        if mode not in MODES:
            # Fail here, with a message, rather than let the API return 403
            # and have it graded as an ERROR that looks like an outage.
            raise ValueError(f"parallel mode {mode!r} is not one of {MODES}")
        return http.post_json(
            ENDPOINT,
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json={
                "objective": question,
                "search_queries": [question],
                "mode": mode,
                # v1 moved result count and per-result excerpt length under
                # advanced_settings. max_results below the included ten does
                # not lower the price; it is set for parity with the other
                # arms, which are all asked for the same number.
                "advanced_settings": {
                    "max_results": max_results,
                    "excerpt_settings": {"max_chars_per_result": max_chars},
                },
            },
        )


@register("parallel")
def _factory() -> Parallel:
    return Parallel()
