"""Serper (Google SERP relay). POST https://google.serper.dev/search.

A reference arm, not the control. The control is the origin fetch, which
asks whether the document was reachable at all. Serper is a thin
pass-through to Google's index, so it offers a second reference point: how a
general-purpose index that is not selling itself as an agent tool fares on
the same questions at the same rungs. It is not ground truth for what is
indexable, and nothing here treats it as such.

Verified 2026-09-02: `X-API-KEY` header, `q`, `num`; results under
`organic[]` with `snippet`. One credit buys up to ten results, two credits
for eleven to a hundred; `num` here is five. Priced at the entry pack,
$1.00 per 1,000 queries; volume packs go to $0.30 and a benchmark is not
going to buy twelve million queries, so the entry rate is the truthful one.
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
