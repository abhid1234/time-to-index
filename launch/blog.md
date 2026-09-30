# I built a benchmark to catch a specific lie. Then I told it twice.

*A search index that is wrong looks exactly like one that is fast. Here's the instrument that separates them — and the two places I nearly shipped the same mistake I built it to expose.*

---

I wanted to know one simple thing. When a fact becomes true on the web, how long until a search API will tell an agent about it?

Plenty of people measure retrieval, and some of them measure it well — there's a good benchmark of these exact APIs that launched last month, and I'll come back to it. But they all measure the same thing: ask a question, check whether the right answer came back, score it out of one.

Which quietly puts two completely different failures in the same bucket.

I couldn't find anyone separating them, so I spent a couple of weekends building the thing that does. What I got was a benchmark, 35 real events, a result I didn't expect, and a much better appreciation of how easy it is to lie with a grey square.

**[Play with it →](https://abhid1234.github.io/time-to-index/playground.html)** — run the ladder, then flip the scoring rule and watch the leaderboard invert. Real measured data underneath. There's a walkthrough video below if you'd rather watch than click.

## The two failures every benchmark scores the same

![ABSENT vs STALE](diagrams/absent-vs-stale.png)

**ABSENT** is a shrug. The API returns nothing relevant, your agent can *see* that it got nothing, and it retries, widens the query, or tells the user it doesn't know. It costs you latency and tokens, and the failure surfaces.

**STALE** is a lie with a citation attached. The API confidently returns the answer that was true yesterday. Nothing about the response marks it as old — it's well-formed, plausible, and wrong. The agent has no signal to retry on, so it stops and cites it. To your customer.

Scored out of one, both are zero. In production one of them wakes you up and the other one doesn't, which is exactly backwards from how much they cost.

## The trick is that I'm not crawling anything

This is the part people assume is hard, and it isn't. I'm not indexing the web, and I'm not racing Parallel or Exa at their own job — I'd lose badly.

![Architecture](diagrams/architecture.png)

I watch the places that **timestamp their own publications**. When `astro@7.3.1` is published, npm's registry says exactly when. That timestamp is `t=0`, on the publisher's clock, never mine.

That one property is load-bearing. You cannot measure lateness without an agreed zero — and asking a crawler when something appeared is asking the defendant to time the race.

From there it's mechanical: build a question only the new fact answers, ask every search API that same question at six fixed lags, and at every rung also fetch the source URL directly as a control.

**The control is what makes the rest interpretable.** Without it, *"the provider was slow"* and *"the document wasn't on the web yet"* look identical, and you end up blaming an index for a publisher's CDN.

## What the ladder can and cannot say

![Interval censoring](diagrams/interval.png)

Here's the part I'd defend hardest, and it's the least glamorous.

An arm that was ABSENT at fifteen minutes and FRESH at an hour started answering *somewhere in between*. I don't know where. So the recorded value is the interval `(15m, 1h]`, not a point. Taking the midpoint would invent precision the ladder cannot supply.

That's interval-censored survival data — the same maths clinical trials use when patients outlive the study, because most facts are still un-indexed at the final rung and throwing those away would report every provider as faster than it is. The estimator is checked against published Kaplan–Meier values from a 1963 leukemia trial, on the grounds that a survival estimator which can't reproduce a textbook isn't one I should be pointing at anybody's product.

## The first real measurement

`@cloudflare/workers-types@5.20260908.1` was published. My collector saw it 228 seconds later. Five minutes after publication, four search indexes were asked what the current version was.

**None of them had it.**

The origin control fetched the answer at that same moment — so the fact was published, on the web, and retrievable. The indexes simply hadn't seen it yet.

That cost 1.8 cents.

Now the bit where a project like this usually starts overselling, so let me get ahead of it: **four API calls on one package is not a result.** No median, no percentile, no ranking, no claim that anybody is faster than anybody. It's one draw from a distribution nobody has characterised.

## Then it caught the thing it was built for

Nearly four weeks in, the ladder has 35 events and 74 graded provider calls, for about 34 cents.

The clearest single catch is one row.

`uv 0.12.15` was released on GitHub. My collector saw it 274 seconds later. At t+5m, four search indexes and the origin control were asked what the current version was:

![The catch](diagrams/the-catch.png)

Five minutes after the release went live, **not one of the four indexes had the current answer, and half of them confidently asserted the old one** — the same wrong version, independently, at the same instant. The control had the right answer at that moment, so this is not a publishing delay. The release was on the web. The indexes had a stale answer and served it without a hint that it was stale.

That table is generated from the ledger at render time, not retyped. If the event ever leaves the repo, the diagram fails loudly rather than printing a picture of something that is no longer there.

Every conventional retrieval benchmark scores those middle two rows exactly the same as the bottom two: zero. In production they are not remotely the same event. One makes your agent retry. The other makes it cite `0.12.14` to your customer.

## Where it was published mattered more than who you asked

I didn't go looking for this, and it's the finding I'd lead with if I were writing this from scratch.

![By source](diagrams/by-source.png)

Every FRESH answer in the entire run — all 12 — came from **Federal Register** documents. Nine of the ten Federal Register events had at least one index returning the current fact five minutes after publication.

Across **npm, PyPI and GitHub releases: zero.** Not one fresh answer in 34 graded calls. That's a two-sided Fisher p of 0.0003 on 12/40 against 0/34, and it isn't close.

So the question *"how fast is this search API?"* turns out to be badly underspecified. Fast for **what**? A new US regulation was findable within five minutes more often than not. A new version of a package half the internet depends on, never — and when a package answer did come back, five times it was the version the release had just replaced.

I can't tell you *why* from this data. Government documents are few, heavily linked and crawled on a schedule; registries publish thousands of versions a day. Those are guesses. What the ladder can say is that the difference is real, large, and invisible to any benchmark that averages across sources.

**One thing I found while writing this up, and it matters.** The origin control fails on every Federal Register document — 10 of 10. It fetches the page and cannot find the document number in what comes back, while it works on every npm, PyPI and GitHub event it ran on. So for the Federal Register, the control that is supposed to separate *"the index was slow"* from *"the page wasn't live yet"* is not doing its job.

The fresh answers don't need it: an index returning the right document number five minutes after publication is proof on its own that the page was live. But the 28 ABSENT verdicts there cannot be checked against it. And I'm not going to patch the grader the night before launch. The plan is pre-registered, and changing how a control is graded *after* seeing the results is precisely the move pre-registration exists to stop. It's the first thing I'll fix, in the open, with the diff.

## And the leaderboard can finally rank — in part

For most of this run the dashboard refused to rank itself, because no pair of arms separated after correcting for the number of comparisons. That changed.

Two pairs now separate after Holm–Bonferroni: `parallel/advanced` against `brave/web` (adjusted p = 0.018) and against `exa/auto` (adjusted p = 0.036, 95% power). The other four pairs are still underpowered, and `tti power` says how many more events each one needs.

**Two things I have to say in the same breath.**

First, all nine of Parallel's fresh answers are Federal Register documents. On package registries it was never fresh either. So the accurate claim is narrow: *on the sources where anything was fresh at all, Parallel's advanced mode got there more often.* It is not "Parallel is faster," full stop.

Second — and this is the part I find most satisfying — **the fastest arm is also tied for the most stale answers.** Two apiece with Exa. Parallel's advanced mode is simultaneously the index most likely to have the new fact and one of the two most likely to hand you the old one as though it were current.

That single row is the whole argument of this project. Any benchmark that collapses retrieval into one number has to decide whether that arm is good or bad. It's both. Speed and staleness are different axes, and scoring them together is how you lose the one that costs you.

The staleness intervals still overlap heavily — this is 18 calls an arm, not a verdict on anybody's product. But it is exactly the shape I built the instrument to be able to see.

## Then I told the same lie. Twice.

Here's the part that actually taught me something.

The entire thesis of this project is: **don't confuse "we didn't ask" with "the index didn't have it."** I then wrote that exact bug into my own code, twice, in a week.

**The first one was a colour.** The measured-data panel draws a square per arm per rung. Rungs that haven't come round yet had no result, so they rendered as empty grey squares — sitting in a grid where grey already meant ABSENT. A reader would have counted absences that were never measured. On a page whose whole argument is that distinction.

Unmeasured rungs are now the only state in the entire palette drawn with **no fill at all** — an outline, with the reason written in it: *not due yet*, *due and not run*, *never scheduled*.

**The second was arithmetic.** The page prints totals under the words "across the whole run so far". I'd computed them from the events currently *rendered*, and separately added a cap on how many get rendered. Nothing was wrong yet — the run was far below the cap. But the moment it crossed, the run would have quietly understated its own sample size, on the page where a reader goes to judge whether it's big enough to believe.

```
❌  totals = f(events currently on screen)
✅  totals = f(every result in the ledger)
```

And then a third, after I'd written the first two up as a lesson. The same totals line counted every provider square as a "graded provider call" — including the ones never dispatched. It read *"124 graded provider calls — 0 fresh, 4 stale, 18 absent, 2 errored"*. Those four numbers add to twenty-four. It was overstating its own sample by five times, three lines below a legend explaining what a skip is.

Neither of the first two bugs was in the measurement. Nor was the third. All three were in the presentation — which is exactly where I'd been telling everyone else to look.

## Someone is benchmarking these APIs. It isn't this axis.

On 18 August, Artificial Analysis launched a [Search Index](https://artificialanalysis.ai/articles/search-api) for search APIs used by agents — 11 provider results across 7 providers at launch, expanding since. Published methodology, live leaderboard, every arm I probe and several I don't. If you're choosing a search API, read it before you read me.

It's also the cleanest illustration of the gap.

Their index is the mean of three benchmarks — DeepSearchQA, BrowseComp, AA-Omniscience. F1, exact-answer accuracy, accuracy. All three ask *did the agent get it right*, run through their Stirrup harness with the same candidate model throughout and a `model_only` baseline as the control, which is exactly the right way to isolate what the search provider contributes.

That's a good design for **how well can an agent answer with this search API behind it**. It can't separate the provider that had nothing from the provider that had yesterday's answer, because on a question both get wrong, both score zero.

And here's the bit I keep turning over.

**A twenty-five-turn agent loop absorbs ABSENT asymmetrically, and preserves STALE entirely.**

Give an agent that budget and an empty result set, and it retries, rephrases, widens, fetches — and usually gets there. Give the same agent a confidently superseded answer and it has no signal that anything is wrong, so it calls `finish` and submits.

The asymmetry isn't total, and their own methodology is why: a model that burns all 25 turns without calling `finish` submits nothing and scores zero. So an absence *can* cost correctness — but only in the tail where it exhausts the entire budget. Everywhere short of that, it costs turns, tokens and latency, and their cost and time columns capture all three. Their write-up is good on this: better results mean fewer searches and fewer tokens, and it shows up in dollars.

A stale answer costs none of those. It's fast, it's cheap, it's wrong, and the only column that could catch it is one measuring whether the answer was current.

Which means the more agentic the harness — the closer to how anyone actually runs these things — the more absence gets priced into cost, and the more staleness survives into the graded score. **The failure mode that matters most in production is the one a production-shaped benchmark is least able to see.**

I'm not saying their index is wrong. It measures answer quality, carefully, and their cost analysis is the most useful thing published on these APIs. I'm measuring a different axis. A provider can lead one and trail the other.

## What it isn't

It's an instrument, not a leaderboard. Nothing here scores answer quality, relevance, or ranking — and with 35 events it supports exactly two provider comparisons and says so — the dashboard marks the other four as underpowered rather than leaving you to infer an ordering from a sorted table.

It also isn't finished. I ran the collector on GitHub Actions, which asks for a cron every ten minutes and delivers one every few hours. An event only counts if it's noticed within ten minutes of publication, so roughly 97% of the world's packages go past unrecorded.

Worse, and I only worked this out watching it happen: with a five-hour cadence against a ten-minute tolerance, **every rung after the first has about a 1-in-30 chance of ever being graded.** The 5-minute rung gets measured because discovery and the first probe happen in the same run. The rest need a run to land inside a ten-minute window, and mostly it doesn't. That is why every verdict in this post is at t+5m, and why most provider squares in this run were never dispatched at all.

Dropping those is correct — a probe I can't place on the ladder is worth less than no probe. But it's why the run is small, and it stays small until the collector moves to a box with real timers.

## What it's built with

| Layer | Tool |
|---|---|
| **Sources** | npm, PyPI, GitHub releases, SEC EDGAR, arXiv, Federal Register — anything that timestamps itself |
| **Arms** | Parallel (advanced + fast), Exa (auto), Brave (web), with Tavily and Serper pre-registered but unkeyed |
| **Control** | Direct fetch of the canonical URL at every rung, excluded from the leaderboard by construction |
| **Estimator** | Turnbull NPMLE for interval-censored data, checked against Freireich 1963 |
| **Multiplicity** | Holm–Bonferroni across the whole pairwise family |
| **Pre-registration** | Plan hashed and locked on first probe; `tti verify` exits 2 if it drifts |
| **Runtime** | Python 3.10–3.13, stdlib plus `requests` and `PyYAML`. No framework, no database |
| **Ledger** | Append-only JSONL, committed to the repo, with every raw payload gzipped alongside |
| **Pages** | One hand-written HTML file each. No build step, no `package.json`, fonts self-hosted |
| **Tests** | 610, on GitHub Actions across four Python versions. One skips by design — it guards a page that only exists before the first run |
| **Built with** | Claude Code, which wrote most of it and caught all three bugs above |

The ledger choice is the one I'd defend. Every number on the dashboard can be traced to a raw API response sitting in the repo, so "I don't believe that" has an answer that isn't "trust me."

## Try it

>>> EMBED `time-to-index-launch.mp4` HERE — then delete this line. <<<

- **[The playground](https://abhid1234.github.io/time-to-index/playground.html)** — run the ladder, flip the scoring rule, then scroll to the real measured data at the bottom
- **[The code](https://github.com/abhid1234/time-to-index)** — MIT, full ledger, every raw payload and every price

If you work on one of these indexes and think my methodology is unfair to you, I'd genuinely like to hear it. The plan is pre-registered precisely so that argument can be about the method instead of the result.

And if you're building anything that renders a verdict: go and look at what your empty state actually says. Mine said ABSENT for a week, in grey, on a page arguing that the difference matters. It's a very easy lie to tell by accident.
