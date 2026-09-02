"""Exa. POST https://api.exa.ai/search with an `x-api-key` header.

Verified against Exa's published OpenAPI document and pricing page on
2026-09-02. Search types are `auto` (default), `fast`, `instant`,
`deep-lite`, `deep`, `deep-reasoning`; `keyword` and `neural`, which this
adapter previously declared, are no longer documented types. Text contents
are requested with `maxCharacters` (still supported, maximum 10,000).

Pricing: $7 per 1,000 requests for auto/fast/instant with ten results and
text included, $12 for deep-lite and deep, $15 for deep-reasoning, plus $1 per
1,000 results above ten. The previous table here said $5 with 25 included,
which understated the cost of the configured arm by 29%.

Every response carries `costDollars.total`, the amount Exa actually charged.
`reported_cost` returns it so the ledger can record the vendor's own number
rather than this repository's reading of a price list.
"""

from __future__ import annotations

from .. import config, http
from . import register

ENDPOINT = "https://api.exa.ai/search"
MODES = ("auto", "fast", "instant", "deep-lite", "deep", "deep-reasoning")


class Exa:
    name = "exa"

    def modes(self) -> list[str]:
        return list(MODES)

    def available(self) -> bool:
        return config.api_key("EXA_API_KEY") is not None

    def search(self, question: str, mode: str, *, max_results: int, max_chars: int) -> dict:
        key = config.api_key("EXA_API_KEY")
        if not key:
            raise RuntimeError("EXA_API_KEY not set")
        if mode not in MODES:
            raise ValueError(f"exa type {mode!r} is not one of {MODES}")
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

    @staticmethod
    def reported_cost(payload) -> float | None:
        """The charge Exa states in its own response, or None if absent."""
        if not isinstance(payload, dict):
            return None
        total = (payload.get("costDollars") or {}).get("total")
        if isinstance(total, (int, float)) and not isinstance(total, bool) \
                and total >= 0:
            return float(total)
        return None


@register("exa")
def _factory() -> Exa:
    return Exa()
