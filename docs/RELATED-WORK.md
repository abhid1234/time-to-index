# Related work: what the Artificial Analysis Search Index measures

In August 2026 Artificial Analysis launched a
[Search Index](https://artificialanalysis.ai/articles/search-api) for search
APIs used by agents, with
[published methodology](https://artificialanalysis.ai/methodology/search-api)
and a [live leaderboard](https://artificialanalysis.ai/agents/search-api).
Launched 18 August 2026 with 11 provider results across 7 search providers,
and expanding since: Brave, Exa, Firecrawl, Keenable, Parallel, Perplexity,
Tavily, TinyFish and You.com now appear on the leaderboard. It is the most
serious work in this area, and it covers every arm this project probes.

It is also the clearest example of the thing this project exists to point at.

Their index is the equal-weighted mean of three benchmarks — DeepSearchQA
(average F1), BrowseComp (exact-answer accuracy) and AA-Omniscience
(accuracy) — run through their Stirrup harness with `web_search` and
`web_fetch` tools, a 25-turn budget with unlimited tool calls inside it, and
one model held constant (GPT-5.6 Luna, medium) as both candidate and grader,
so the search API is the only thing that varies. There is also a `model_only`
baseline with no search tools, which is the right control: it shows how much
each provider lifts the model above its own parametric knowledge. That is a
good design for the question it asks, which is **how well can an agent answer
with this search API behind it.**

All three components are answer-correctness scores. So a provider that
returns nothing and a provider that confidently returns the superseded
answer both score zero on the same question, and the index cannot tell them
apart. That is not an oversight; it is what accuracy means. It is simply a
different axis from the one here.

Two things follow, and the second is the one worth arguing about.

**They are complementary, not competing.** Their axis is answer quality at
whatever freshness the index happens to have. This axis is how long until a
known-new fact is retrievable at all, and what comes back before it is. A
provider can lead one and trail the other. Nothing here ranks answer quality,
and nothing there measures latency to retrievability.

**A 25-turn agent loop absorbs ABSENT asymmetrically, and preserves STALE
entirely.** Given unlimited tool calls inside the budget, an agent that gets
nothing back can retry, rephrase, widen and fetch its way to the answer. An
agent handed a confidently superseded answer has no signal that anything went
wrong, so it calls `finish` and submits.

The asymmetry is not total, and their methodology is why: a model that burns
all 25 turns without calling `finish` submits nothing and scores zero. So an
absence *can* cost correctness — but only in the tail where it exhausts the
whole budget. Everywhere short of that it costs turns, tokens and latency,
all of which their cost and time columns do capture. A stale answer costs
none of those. It is fast, cheap, and wrong, and the only column that could
catch it is the one measuring whether the answer was current.

Which means the more agentic the harness — the closer to how these are
actually run — the more absence is absorbed into cost and the more staleness
survives into the graded answer. The harness that best models production use
is the one where the ABSENT/STALE distinction matters most and is least
visible. That is reasoning from their published design, not something
measured here.

Their leaderboard numbers are theirs to state and worth reading at the
source. This project deliberately publishes no competing quality score.


---
