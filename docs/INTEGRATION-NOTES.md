# Integration notes

Friction encountered wiring each source and each provider into this harness.
Kept because it is the most reusable thing a benchmark produces and the part
that usually goes unwritten: the numbers describe a service, these notes
describe what it was like to build against one.

Two rules for this file. Everything under **Observed** was hit while building
this repo and is reproducible from it. Everything under **Open** is a
question the harness will answer on a real run and has not answered yet.
Nothing gets promoted from Open to Observed without a commit that shows it.

---

## Providers

**No provider API has been called yet.** This repo was built without keys, by
design: the adapters, the grader, the estimator and the control arm are all
testable without spending anything, and shipping a benchmark whose code has
only ever run against one vendor's live API is how bias gets in early.

That means this section is currently all Open. It is the section that
matters most, and filling it in honestly on first run is worth more than
anything already written here.

### Open — to record on first run, per provider

- **Time to first successful call** from a cold start: signup, key, first
  200. Measured in minutes, from the docs alone, without asking anyone.
- **Whether the documented request shape works verbatim.** Each adapter in
  `tti/providers/` sends what the vendor's own documentation describes. Any
  gap between documented and actual is a doc bug worth reporting, and it is
  the single most common one.
- **Error taxonomy under load.** What comes back at the rate limit: a 429
  with a `Retry-After`, a 200 with an empty result set, or a 500? A provider
  that returns 200-with-nothing at its limit is indistinguishable, to this
  harness, from a provider whose index does not have the document — and would
  silently score as a recall failure. `tti doctor` and the ERROR verdict
  exist to catch this, but only if the taxonomy is known.
- **Whether free-tier credit behaves as documented.** Specifically: does a
  free allowance ever return an insufficient-balance error while still inside
  the stated free quota? This is worth checking deliberately rather than
  discovering at 3am in a cron job.
- **Latency distribution, not mean.** p50 and p99 are both recorded per
  probe. A provider with a good p50 and a 30-second p99 is a different
  integration problem than its average suggests.
- **How the SDK or docs read to a coding agent.** Several vendors now state
  that agents are a primary audience for their documentation. That is a
  testable claim: point an agent at the docs cold and see whether it produces
  a working call without human correction. If it needs a hand-built type
  digest first, the claim is aspirational, and saying so is more useful than
  a compliment.

### Observed

- **Cost tables drift.** `data/providers.yaml` carries a `pricing_checked`
  date per provider for this reason. Any published cost-per-event number is
  only as current as that field, and a stale one is worse than none.
- **Mode naming is not comparable across vendors.** "basic/advanced",
  "turbo/fast/base/pro", "auto/keyword/neural" are not a shared axis. The
  leaderboard lists arms as `provider/mode` and never aggregates a provider's
  modes into one row, because averaging a cheap mode with an expensive one
  produces a number that describes no purchasable product.
- **One vendor's request contract is genuinely different.** Parallel's Search
  API v1 takes an `objective` plus literal `search_queries`, which assumes
  the caller is an agent that knows its own goal rather than a person typing
  keywords. That is a real design position and it does not fit a
  lowest-common-denominator harness cleanly: sending only the objective
  compares its query rewriting against other providers' raw matching, and
  sending only the literal query discards the thing the product is for. Both
  are sent, and `docs/METHODOLOGY.md` flags it as a dial a reasonable person
  would set differently.

---

## Sources

### Observed

- **npmjs.com returns 403 to any non-browser user agent** — including for
  `/robots.txt`. The origin control therefore cannot verify whether the
  crawler-facing npm page contains a new version, and falls back to
  `registry.npmjs.org`, recording `origin_rank=1` so the weaker claim is
  visible in the ledger. The fallback answers "the fact was public", not "the
  page a crawler indexes contained the fact". Those are different, and the
  difference is not roundable.
- **PyPI's project page is server-rendered and contains the version**, so
  origin verification succeeds at rank 0 in 30–45ms. It is the cleanest source
  in the set and a good first target for anyone forking this.
- **The npm `time` map contains two non-version keys**, `created` and
  `modified`. Iterating it as if every key were a version produces two
  garbage "releases" per package. Cheap to hit, quiet when you do.
- **PyPI release timestamps are per-artifact, not per-release.** A release
  with a source distribution and fifteen wheels has sixteen upload times
  spread over minutes. The harness takes the earliest, since that is when the
  release first became fetchable; taking `[0]` takes whichever artifact the
  API happened to list first.
- **Serial polling does not fit a five-minute cadence.** Seventy watchlist
  subjects took over two minutes sequentially, against a detection-lag budget
  of ten. With a bounded thread pool it is under nine seconds. Collector
  concurrency is capped per source rather than globally, because the limits
  are per-host: GitHub allows 60 requests/hour unauthenticated, arXiv asks for
  no more than one request every three seconds, and the SEC publishes a
  fair-access policy that a naive fan-out will trip.
- **SEC EDGAR and arXiv both require a real contact string in User-Agent.**
  Not a suggestion; requests without one get refused. `TTI_USER_AGENT` is
  checked by `tti doctor` for this reason.
- **A blocked host and a quiet source look identical in an event count.** The
  first version of the collectors caught exceptions per subject and moved on,
  so an unreachable API reported "0 new events" — the same output as a
  perfectly healthy day with no releases. Collectors now track per-subject
  errors, `tti discover` exits 2 and names unreachable sources, and a source
  where *every* subject failed is reported as broken rather than empty. This
  is the same failure class the benchmark measures in other people's systems,
  which is a good argument for assuming it is in your own.

### Environment, not vendor

While this repo was developed, `data.sec.gov`, `export.arxiv.org`,
`www.federalregister.gov` and `api.github.com` were unreachable — blocked by
the sandbox's egress proxy, not by those services. Their collectors are
written and unit-tested but have not been exercised against live endpoints.
Anyone running this outside such a sandbox should expect them to work and
should treat `tti doctor` as the first thing to run, not the last.

## Live-run notes

Dated observations from running collectors against real endpoints. Each one
changed code; none was visible from the fixture server.

**2026-09-02, npm registry, from a cloud container.** Twelve of forty-six
watched packages failed with `ResponseTooLarge` on the first live `discover`:
astro, @types/node, antd, langchain, firebase, next, playwright, prisma,
tailwindcss, vite, wrangler, storybook. The full packument is the only document
carrying the `time` map, and for big packages it runs 8–16 MB (measured: antd
8.4, @types/node 11.1, aws-sdk 10.6, typescript 15.6, react-native 15.8). The
abbreviated packument is smaller but has no `time` map. The packument fetch now
has its own 32 MB bound with a warning at 24 MB; every other fetch keeps the
8 MB module default. `discover` and `doctor` now name the failing subjects
rather than showing the first error and a count — the count-and-one-example
form is how `next` being broken took a separate script to learn.

**2026-09-02, later the same night — a correction to the entry above.** The
32 MB bound was wrong, and wrong for a reason worth recording. It was sized
from five packuments measured with `curl`, which reports compressed wire
bytes; the collector reads decompressed bytes, several times larger. And the
five did not include `next`, `prisma` or `vite`. Measured through the
collector's own path: prisma 43.8 MB, vite 38.9, next 31.2, firebase 30.2,
wrangler 29.6, storybook 24.1. The bound refused two packages and sat within a
megabyte of a third on its first live run. It is now 96 MB, from the
collector's own measurement of every package that had failed. The code
comment says which kind of megabyte.

Two structural changes came out of the same measurement, and matter more than
the number. First, the collector now asks npm's `/-/package/<pkg>/dist-tags`
endpoint (~300 bytes) before anything else, and fetches the full packument
only when `latest` differs from its high-water mark — so the 30 MB document is
a per-release cost, not a per-poll one. The abbreviated packument was
considered and rejected: no `time` map, and 25.5 MB for `next` regardless.
Second, a pre-existing bug the sizes made visible: events dropped as
detected-late were never written anywhere, so the collector had no memory of
them and re-fetched every packument on every poll. Against the live registry
that was roughly a gigabyte per five-minute cycle on a stale watchlist. Late
drops are now recorded in `runs/seen.jsonl`; a test asserts the second poll
fetches zero packuments.

**2026-09-02, npmjs.com, from a cloud container.** `www.npmjs.com/package/…`
returns 403 to this client; `pypi.org/project/…` returns 200. The control arm
already handles this by falling back to the registry document and recording
that it did. Consequence for anyone running `tti crawlability` against
npmjs.com: do it from a residential connection, not a cloud host.

**2026-09-02, cold start.** The first `discover` against the live registries
collected 82 events and dropped all 82 as detected-late. This is the documented
cold-start behaviour, not a fault: every watched package looks new on the first
poll and shipped days ago. A populated ledger needs the collector to be running
when a release lands, which is what the timers are for.

**2026-09-02, Parallel Search API, from the published spec.** The adapter
targeted `/v1beta/search`, sent the mode as `processor`, put `max_results`
and `max_chars_per_result` at the top level, and offered `base` and `pro` as
modes. Against the current OpenAPI document: the endpoint is `/v1/search`,
the field is `mode`, both settings live under `advanced_settings`, and the
modes are `turbo`, `fast`, `basic`, `advanced`. `base` and `pro` are Task API
processors. Their error catalogue lists `Forbidden: invalid processor in
request`; every probe would have returned it. Pricing was also off: ten
results are included per request, not five. Caught by reading the spec before
the first probe. The adapter now refuses an unknown mode locally, with a
message, rather than letting the API 403 and having that graded as an outage.
`search_queries` is kept as the same full sentence every other arm receives,
against Parallel's 3–6-keyword guidance, deliberately — see the adapter
docstring.

**2026-09-02, the other four adapters, from the published specs.** Same
exercise as Parallel, same night. Brave sent `freshness=pd` — a last-24-hours
filter no other arm carried and nothing in the repository justified; it is
gone, and the adapter docstring says why it was wrong in both directions. Exa
declared `keyword` and `neural`, neither a documented type any more, and was
priced at $5 with 25 results included when it is $7 with ten — a 29%
understatement of the configured arm's cost. Exa also reports the actual
charge in every response, and the ledger now records it. Tavily was correct in
every field. Serper's pricing was correct at the entry pack, and its docstring
called it "the control arm", which it is not — the origin fetch is; it is a
reference point, and treating a general index as ground truth for what is
indexable was never the claim.

A generic test now asserts that every mode any adapter *declares* is priced,
not only the configured ones. An unpriced mode is $0.00 in the cost column,
which is the cheapest way to win a benchmark.

**2026-09-02, Parallel `usage`.** The v1 response schema lists `usage`
(array or null, "usage metrics for the search request") with no field
detail in the published document. It may carry cost the way Exa's
`costDollars` does; it may not. No `reported_cost` hook was written for it,
because inventing a field name is the class of error this evening was spent
removing. First real call: store the raw response (the ledger does this
anyway under `runs/raw/`), read `usage`, and if it states a charge, add the
hook and the test alongside Exa's.

**2026-09-02, the four collectors that cannot be reached from a cloud
container, from their published terms.** arXiv's terms of use say one
request every three seconds and a single connection at a time; the collector
ran two concurrent workers with no spacing, under a comment that quoted the
rule. It is now one worker with a three-second gap, and the base class
enforces the gap rather than a comment describing it. EDGAR and the Federal
Register both anchored Eastern-time stamps to a fixed UTC offset, an hour
wrong for five months of the year; both use `zoneinfo` now. GitHub's
collector asked for five releases per repository, so a canary-heavy repo
could push the newest stable off the page and produce nothing; it asks for
thirty, same request, and sends an explicit `X-GitHub-Api-Version`. The
Federal Register source now states the public-inspection caveat: documents
are on the web before the issue time this source anchors to, so any error
flatters providers rather than penalising them.

**2026-09-02, live re-verification from a cloud container.** Two things that
had only ever run against the fixture server ran against the web.

*The origin control, end to end.* Three real PyPI events built from the live
registry (anthropic 1.3.0, requests 2.34.2, uv 0.12.9). Each probed
`found` on the canonical human page at origin rank 0 — not the API fallback
— classified `server_html`, and graded FRESH on the exact token with no
stale hit. The stored payload is the 1,601-character excerpt window by
design; the grader read that, not a full body. First real control-arm
result the project has produced.

*The crawlability figures the pitch memo cites*, each fetched three times
with agreement required:

| page | posture | visible / served |
|---|---|---|
| crates.io/crates/serde | sveltekit · client_shell | 32 / 5,056 |
| bitbucket.org/atlassian/aui/src/master/ | client_shell | 9 / 14,535 |
| gitlab.com/gitlab-org/gitlab | metadata_only | 469 / 63,132 |
| pkg.go.dev/…/gin-gonic/gin | static_html | 93,012 / 429,377 |
| packagist.org/packages/laravel/framework | static_html | 20,618 / 1,161,270 |
| pypi.org/project/requests/ | static_html | 13,494 / 251,342 |
| hex.pm/packages/phoenix | static_html | 3,309 / 149,712 |
| rubygems.org/gems/rails | static_html | 2,377 / 63,794 |

All eight allow all twelve AI crawler user-agents in robots.txt. The three
numbers the memo leads with — 32, 9, 93,012 — reproduce to the character.

One behaviour worth knowing about crates.io: with no `User-Agent` header at
all it returns 403; with a UA but no `Accept: text/html` it returned 404 on
one fetch tonight; with both it returns the 5,056-byte shell. A collector
that sends neither reads the site as refusing, not as a shell. The harness
sends both.

*Unreachable from this host, so not re-verified here:* www.npmjs.com (403),
github.com pages (403), arxiv.org, and every vercel.com / nextjs.org /
ai-sdk.dev / v0.app property. Those need a residential connection.

**2026-09-02, the forecast, before and after one bound.** `tti forecast`
against the live registries, same watchlist, same hour, the only change
being whether the twelve largest npm packuments were readable:

| | before | after |
|---|---|---|
| subjects readable | 82 | 94 |
| observed rate | 11.3 events/day | 13.1 events/day |
| effective subjects | 37 | 44 |
| top-subject share | 7.7% | 6.6% |
| days to 191 events (HR 1.5) | 17 | 15 |

The stopping rule reads the after column. The before column is what the
tool reported an hour earlier with a straight face, `next` listed as
unreachable, and nothing in the number to say a bound had been applied in
one module and not another. 13.1 per day is the rate the watchlist was
sized to when it was built; the bug had quietly returned the corpus to
roughly its pre-expansion rate.

**2026-09-02, the first real ledger.** A pipeline exercise, not the protocol:
detection-lag and rung-slip windows relaxed so eight already-published PyPI
releases entered the ladder and every past rung fired at once, origin arm
only, scratch directory. Eight probes at the 5-minute rung, all `found` at
rank 0, all `server_html`, all FRESH; carry-forward skipped the 28 later
rungs; twelve remained pending with due times in the future. The
pre-registration lock wrote itself on the first dispatched probe -- the first
time that mechanism has fired -- and `tti verify` read it back unchanged.
`tti decoy` on the eight control excerpts: 0 false positives, Wilson upper
bound 32%, reported as the bound and not as zero.

And a defect: `tti score` and `tti report` both said "no results yet" on a
ledger holding 36 results. The leaderboard excludes the control arm by
design, so a control-only run -- the state anyone is in before the first
provider key -- was told nothing had happened. Both now recognise that state,
summarise what the control found, and exit 0; the dashboard renders with its
control panel and a banner that says why the table is empty, rather than the
"every probe errored" wording, which would have been false.

**2026-09-02, `tti routes` against pypi.org.** Seven of eight sitemap-sampled
project and user routes returned the same 3,036-byte body with HTTP 200,
titled "Client Challenge". The interception guard excluded them, as designed
— and its docstring, written from an earlier observation, gives "the same
3,036 bytes with HTTP 200" as its example. The live web reproduced the
guard's own number to the byte. Two things followed. `routes` then said
"Uniformly readable across the sample" from the one survivor; it now refuses
a site-level sentence below three usable routes and says how many were
excluded and why. And the exclusion line now carries the intercepted body's
size and title, because "7 routes returned an identical 3,036-byte body
titled 'Client Challenge'" tells a reader the harness was challenged, while
"identical" only tells them something was.

PyPI challenges selectively: `/project/requests/` served a full page to a
single fetch minutes earlier; eight distinct routes in quick succession from
the same client drew the interstitial. A benchmark sampling a site looks
like a scraper. The output now says the exclusion describes how this client
was treated, not how the site renders for a crawler in good standing.

**2026-09-02, `tti survey` on the eight reachable pages, three fetches each.**
Five of eight readable, crates.io and Bitbucket named as allowing every AI
crawler and shipping nothing, GitLab metadata-only with breadcrumb JSON-LD, no
false interception across eight distinct hosts. The memo's narrative
reproduces end to end through the tool that produced it.

**2026-09-02, not a bug.** `tti prereg` appeared to exit 1 on the first real
ledger. It was `head` closing the pipe and Python dying on BrokenPipeError;
unpiped it exits 0 with the lock unchanged. Recorded so the next person who
sees it does not spend the twenty minutes.

**2026-09-02, the first real dashboard, four sentences.** Rendered from the
control-only ledger (8 events, 36 rows, no provider key), the page said four
things that were false and one of them was the headline. "36 control probes
graded": 28 of those rows are carry-forward SKIPPED rows — an event that was
already confirmed at rung one is not re-fetched at rungs two through five,
and the ledger records that as a row so the ladder stays complete. The
origin table now skips them, and the found count went from 36 to 8, which is
the number of pages actually fetched. "0 were confirmed retrievable": that
number was read off `max(score.n_origin_confirmed)`, and with no provider
arm there is no score. It is now counted from the control rows directly, and
reads 8. "36 graded probes" in RESULTS.md summed provider calls; it now says
"0 provider probes graded · 8 control probes", because a reader should not
have to know which of those a bare number meant. And the plan panel listed
every declared arm under "produced nothing", which describes a provider that
was asked and failed everywhere — none was asked. `classify` now takes the
set of enabled arms from `providers.available_arms()` and splits the silent
ones: enabled-and-silent is a finding; not-enabled is a configuration state,
and the panel says "no key was set, so no probe was ever dispatched".

None of the four was a wrong number in the analysis. Each was a true number
under a false heading, produced by code written before there was a real
ledger to render, on the assumption that a run always has a provider arm.
The first thing a real run did was violate the assumption. This is the same
lesson as the control-only branch in score and report the night before, one
layer up: it is not enough to detect the state, every sentence on the page
has to have been written knowing the state exists.
