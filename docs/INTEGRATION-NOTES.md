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

