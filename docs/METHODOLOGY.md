# Methodology

## The question

When a fact enters the world at a known instant, how long until each
web-search API will return it — and until it does, what does it return
instead?

The second half is the part that is not currently measured anywhere.

## Why not just use an existing benchmark

Several good ones exist. Artificial Analysis maintains a search index across
providers; `edendalexis/search-api-cost-benchmark` scores cost per correct
answer with paired significance testing; OpenRouter publishes live
leaderboards on an open harness. They measure retrieval quality against a
fixed answer key.

That design has a known problem, and the `search-api-cost-benchmark` authors
documented it themselves: grading time-sensitive questions against a frozen
answer key cost every provider 8–18 points, and it penalised the *freshest*
indexes hardest, because a provider returning today's correct answer is
marked wrong against an answer key written in April. They engineered around
it to protect their quality measurement.

The thing they engineered around is a measurement in its own right. A frozen
key applied to a time-sensitive question measures index age. Nobody points
that instrument at the question directly.

## Ground truth

The selection rule for a source is one sentence: **it must stamp its own
publication time.** That rules out most of the web. An article's "published"
field is whatever the CMS says and it moves when the page is edited. A
package registry's upload time is a receipt.

| source | ground-truth clock | supersession |
|---|---|---|
| npm | `time[version]`, written by the registry at publish | yes — previous stable version |
| PyPI | `upload_time_iso_8601` on the first artifact | yes — previous stable version |
| GitHub releases | `published_at` on the release object | yes — previous non-draft release |
| SEC EDGAR | `acceptanceDateTime` on the filing | yes — previous filing of the same form by the same CIK |
| arXiv | `published` on the Atom entry | no |
| Federal Register | `publication_date` + document number | no |

Supersession is what makes staleness measurable, and it is why package
registries and periodic filings carry most of the weight here. "What is the
latest version of X" had a correct answer yesterday that is wrong today. A
new arXiv paper does not make an older identifier wrong, so preprints and
Federal Register documents contribute to time-to-index and recall but are
excluded from the staleness denominator. That exclusion is enforced in code
by `Event.measures_staleness`, not by convention.

## Query construction

Each query is built from the event's own metadata and never from any
provider's output. If one provider's snippet shaped the question, that
provider would be graded on a question written from its own index.

The answer token is chosen for distinctiveness rather than naturalness: a
version string, a release tag, an SEC accession number, an arXiv identifier.
A match on `0000320193-26-000081` is near-conclusive evidence the document
was retrieved. A match on a date string is not.

## The ladder

Every event is probed at **t+5m, +15m, +1h, +6h, +24h, +72h** after
publication, per provider, per mode.

Geometric spacing, because indexing latency spans four orders of magnitude
and a linear ladder spends its whole budget resolving the tail.

Three rules discard data to keep the rest honest:

**Detection lag.** An event our collector noticed 40 minutes after
publication cannot be probed at the 5-minute rung. Rather than record it at
the wrong lag, the event is dropped. Threshold: 600 seconds.

**Rung slip.** If the runner was down and a probe fires 90 minutes past its
15-minute due time, recording it as a 15-minute observation is false and
recording it as a 105-minute observation biases the ladder. It is dropped,
and the drop is written to the ledger.

**Carry-forward.** Once an arm answers FRESH for an event, its remaining
rungs are skipped. Indexing is not observed to reverse, and the survival
estimator only needs the first FRESH.

## Grading

Three verdicts, from the flattened text of the provider's response:

- **FRESH** — the new answer token is present.
- **STALE** — the superseded token is present and the new one is not.
- **ABSENT** — neither.

Details that matter more than they look like they should:

*Boundary matching.* Tokens are matched on non-word, non-dot boundaries.
Plain substring matching scores `15.4.1` as present inside `15.4.10`, which
silently inflates freshness on exactly the fast-moving packages the
benchmark cares about most. There is a test for this.

*Both present means FRESH.* A changelog page lists every release, so it
contains the superseded token by construction. That page is a correct
retrieval, not a stale one.

*Content only.* Grading reads titles, snippets and extracted text. URLs are
excluded — a URL can carry a version string that the page body contradicts —
and so is any echo of the query.

## Statistics

**Time to index is a survival problem.** Most events are still un-indexed at
the last rung, so the observation is "longer than 72 hours", not a number.
Dropping those and taking the median of the rest is the obvious thing to do
and it is wrong in a specific direction: it discards exactly the slow cases.
Worse, the bias does not cancel across a leaderboard — it is largest for the
provider with the most un-indexed events, so it can reorder the ranking.

So: Kaplan–Meier with right-censoring at the last rung actually fired, and
Greenwood's formula on a log-log scale for the interval, which keeps the band
inside [0,1] where the plain version exits it. The implementation is checked
against the published values for the Freireich 1963 6-MP arm, the standard
worked example for the product-limit estimator.

**Medians are reported as brackets.** An arm first seen FRESH at the 1h rung
indexed somewhere in (15m, 1h]. It did not index at 1h. Printing "1h"
overstates the latency by up to the width of the bracket, so the ladder's
resolution is stated rather than hidden. A finer ladder would cost an order
of magnitude more per event.

**Rates get Wilson intervals**, not normal-approximation ones. At n≈40 events
per source class the normal approximation puts the lower bound of a 100%
recall below 90% and the upper bound of a 0% staleness above 0.

**Differences get a log-rank test.** "A is faster than B" needs a test that
handles censoring; a t-test on the indexed subset will find differences that
are artefacts of who ran out of window first.

## Cost

Every result carries its price, and the leaderboard reports dollars per 1,000
events alongside latency. A freshness win bought at 5× the price is a
different product decision than a freshness win at parity, and a leaderboard
that hides the denominator is advertising.

Prices come from `data/providers.yaml`, where each one carries the vendor
page it was read from and the date it was last checked by hand.

## Spend cap

A probe that would push the day's spend past the cap is never dispatched, and
its refusal is written to the ledger as `SKIPPED` with a reason. The
dashboard says how many were refused.

This is not politeness. A cap that silently stops probing is indistinguishable,
in the output, from a provider that silently stopped indexing — which is the
one confusion this project cannot afford to introduce.

## What would make these numbers wrong

Stated up front, because a benchmark that only lists its strengths is a
marketing page.

- **Watchlist composition.** Twenty npm packages and twelve issuers is not
  the web. A provider tuned for developer content will look better here than
  it would on a general corpus. The watchlist is a YAML file; fork it and
  find out.
- **Ladder resolution.** Anything faster than 5 minutes reads as "≤5m".
  Providers may differ meaningfully inside that bracket.
- **Single-query retrieval.** One query per event, five results. A real agent
  reformulates and re-queries. This measures the first shot, which is the
  floor rather than the ceiling.
- **Question phrasing.** Questions come from templates. A provider whose
  rewriting favours a different phrasing is being under-measured, and there
  is currently no phrasing-sensitivity arm.
- **Provider request shape.** Each adapter sends what that vendor's own
  documentation describes as the standard call. Parallel's API takes an
  objective plus literal queries, which is a different contract from the
  others; sending only the objective would compare its rewriter against other
  providers' raw matching, and sending only the literal query would discard
  what the product is for. Both are sent. Reasonable people could set that
  dial differently, and the adapter is twenty lines.
- **Geography and time of day.** All probes run from one region on one
  schedule. Crawl cadence is not uniform across either.

## Reproducing

Every provider response is stored verbatim under `runs/raw/`. `tti regrade`
re-scores those payloads with whatever rules are in `grader.py` and reports
how many verdicts moved, without making a single API call.

If you think the matching rules are wrong, change them and see how much the
leaderboard actually moves. That is the only reason to believe a number
published by one person.
