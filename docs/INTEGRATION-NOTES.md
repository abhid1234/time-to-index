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
- **One vendor's request contract is genuinely different.** Parallel's search
  endpoint takes an `objective` plus literal `search_queries`, which assumes
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
