# Time to Index

Time to Index measures how long a newly published fact takes to become
retrievable through a web-search API — and, until it does, what the API
returns instead. It separates two failures that other search benchmarks
score the same way: returning **nothing** (ABSENT) and confidently returning
**the answer that was just replaced** (STALE). It does not crawl, does not
rank providers it cannot separate statistically, and does not trust anyone's
clock but the publisher's.

![Five minutes after a uv release went live: the origin had 0.12.15, two search APIs confidently returned 0.12.14, two returned nothing](launch/diagrams/the-catch.png)

## See it first

- **[Short video (91s)](media/time-to-index-short.mp4)** — the problem, the clock, one real result, and what the ledger shows so far
- **[Interactive playground](https://abhid1234.github.io/time-to-index/playground.html)** — run the ladder, flip the scoring rule (a hand-authored simulation), then read every real probe from the committed ledger; nothing to install
- **[Live results](https://abhid1234.github.io/time-to-index/)** — the dashboard, regenerated from `ledger/` on every push
- **[Launch post](launch/blog.md)** — why a stale answer is worse than no answer, and what 37 new facts showed
- **[The ledger](ledger/)** — every event, probe and graded answer, plus the raw provider payloads, committed and checkable with `tti verify`

| | the agent's next move |
|---|---|
| **ABSENT** — provider returns nothing relevant | retries, widens, or says it doesn't know |
| **STALE** — provider confidently returns the answer that was superseded | cites it |

Scored as "wrong", these are identical. In production they are not remotely
the same event, because nothing downstream of a stale citation can tell that
it is wrong.

## What the ledger shows so far

Four search APIs (Parallel advanced and fast, Exa auto, Brave web), probed
five minutes after each new fact went live, 78 graded answers:

- **Where a fact is published matters more than who you ask.** New Federal
  Register documents came back current 12 times out of 40. New npm, PyPI and
  GitHub releases: 0 out of 38 — and 5 of those answers were the version
  that had just been replaced.
- **Fast and stale are not opposites.** The arm with the most current
  answers, `parallel/advanced`, is also tied for the most stale ones.
- **Only a partial ordering holds.** After Holm–Bonferroni correction the
  ledger supports 2 of 6 pairwise comparisons. The dashboard says so rather
  than printing a leaderboard.

A small, early sample over 27 days. [What can and cannot be
claimed](#what-can-and-cannot-be-claimed) lists every limit, including the
origin control that fails on Federal Register documents.

## Five-minute look (no keys, no spend)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m tti demo    # renders docs/demo.html and checks the estimator
```

(`tti` and `python -m tti` are the same program; the second also works when
the checkout path contains a space, which the console script's `sh` wrapper
does not. SETUP.md has the rest.)

`tti demo` runs a synthetic corpus with made-up providers (`provider-a/b/c`)
whose indexing latencies are drawn from a seeded generator, writes a payload
for every probe in each arm's text shape (long excerpts, short snippets,
mid-length text) and grades it with the real grader, then reports whether
the estimator recovered the latencies it was never shown. Because the
payloads exist, the demo page's sensitivity panel is computed, not
placeholder: under the `snippet-window` variant the snippet arm overtakes the
excerpt arm, which is the text-volume effect described above, made visible.

```
OK  provider-a/fast: estimated     5m–15m  true      8m  (n=106, indexed 105)
OK  provider-b/base: estimated  1.0h–6.0h  true    1.7h  (n=106, indexed 100)
OK  provider-c/base: estimated 24.0h–3.0d  true   34.3h  (n=106, indexed 72)
```

The demo writes `docs/demo.html` and never `docs/index.html`. It is evidence
about the instrument, not about any product.

---

## Related work

Artificial Analysis launched a Search Index for agent search APIs in August
2026. It measures answer quality; this measures time to retrievability and
separates ABSENT from STALE. [`docs/RELATED-WORK.md`](docs/RELATED-WORK.md)
sets out what each can and cannot see, and why a production-shaped agent
loop hides staleness.

## How it works

1. **Watch sources that stamp their own publication time.** npm and PyPI
   uploads, GitHub releases, SEC EDGAR acceptance times, arXiv announcements,
   Federal Register documents. The registry's clock is the ground truth; ours
   is never used.
2. **Build a question only the new content answers,** from the event's own
   metadata — never from any provider's output.
3. **Ask every provider at t+5m, +15m, +1h, +6h, +24h, +72h** — and at every
   rung, fetch the canonical URL directly as a control, so "the provider was
   slow" is never confused with "the document was not on the web yet". The
   control also records *where* the fact sat: visible HTML, a script-embedded
   data blob, or only an API fallback. An arm strong on the first and weak on
   the second is not slow — it does not execute JavaScript.
4. **Grade FRESH / STALE / ABSENT** against the new answer token and the one
   it replaced, in whatever text the API served. Arms differ by an order of
   magnitude in how much text that is — an excerpt API honours the 1,500
   characters asked for, a snippet API returns ~150 regardless — so the
   leaderboard shows text served per result beside recall, and `tti
   sensitivity` re-grades every arm as though it had returned short snippets.
5. **Estimate with Turnbull's NPMLE for interval-censored data.** An arm seen
   absent at 15m and fresh at 1h indexed somewhere in (15m, 1h]; it did not
   index *at* 1h. Kaplan–Meier needs a point event time and would overstate
   every latency, and it cannot represent a widened interval at all when a
   probe is dropped.
6. **Say when the numbers can't carry a claim.** `tti power` reports the
   hazard ratio, the achieved power, and how many more days of collection a
   real comparison would take.
7. **Re-grade under worse rules and report what moved.** `tti sensitivity`
   re-scores every stored payload under deliberately different grading
   choices, at zero API cost, and says whether the ranking is a finding or an
   artefact of the grader.

Optionally, ask each event more than one way. A provider that returns the new
fact for "latest version of next" but not for "which version of next shipped
most recently" *has* the document and does not reliably surface it — a
different failure from not having it, and one an agent hits far more often
than a benchmark does, because an agent asks whatever its planner produced
that turn. Off by default and rung-limited when on; see `phrasing_probe` in
`data/settings.yaml`.

Full design, and everything that could make the numbers wrong, in
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## The other half: can an agent read the page at all?

A provider can only return what it could read. `tti crawlability` and
`tti routes` measure the corpus rather than the providers, with no keys and
no ledger; [`docs/CRAWLABILITY.md`](docs/CRAWLABILITY.md) explains both.

## What can and cannot be claimed

The measured panel on the playground is real. It is also, as of this writing,
small — and the difference between "real" and "enough" is the whole reason
this section exists rather than a headline number.

**What the run supports right now.** That the instrument works end to end: a
package publishes, the collector notices it within minutes, four search arms
and an origin control are asked the same question at the same fixed lags, and
the answers come back graded and priced. The first event measured is the
argument in miniature — at t+5m none of the four indexes returned the new
version, while the origin control fetched it at that same moment, so the fact
was genuinely published and retrievable and the indexes simply had not seen it
yet.

**The first two STALE verdicts.** By 10 September the ladder had graded its
first dozen provider answers; ten came back ABSENT and two did not come back
empty at all. At t+5m on `@sentry/node@10.74.0`, `parallel`
in `advanced` mode returned `10.73.0` — the version that had been current
until five minutes earlier. At t+5m on
`@cloudflare/workers-types@5.20260910.1`, `brave/web` returned
`5.20260908.1`, the build from two days before. In both cases the origin
control fetched the current version at that same moment, so the new fact
was published, live and retrievable, and the index returned the superseded
answer with nothing in the response marking it as old. Both raw payloads
are in `ledger/raw/`.

That is one observation per arm, on two packages, at one rung. It is not a
rate, it is not a ranking, and it is not a claim that these two arms are
worse than the others — see the next paragraph, which applies to these two
verdicts exactly as much as to everything else here.

**What it does not support.** Any comparison between providers. Any median,
any percentile, any statement of the form "X is faster than Y". A handful of
graded calls on a handful of events is one draw from a distribution nobody has
characterised, and the arms have not yet been asked about enough events for a
difference between them to mean anything. `tti power` will tell you, for the
current run, which pairwise claims the data can carry — and until it says a
pair is separable, the leaderboard's ordering is noise with a confidence
interval drawn around it.

**Why the run is small.** Probes are enqueued when an event is discovered, and
an event is only accepted if it is discovered within
`max_detection_lag_seconds` of publication — 600 by default. The hosted runner
requests a ten-minute cron and is actually delivered one every few hours, so
almost every publish is noticed far too late and is dropped rather than
recorded at a lag the ladder cannot truthfully place. Dropping is the correct
behaviour; the fix is a runner with real timers, not a looser bound. See
`deploy/systemd/`.

**Why nothing here is quietly padded.** A rung with no result is never drawn
or counted as an ABSENT — not in the JSON, not on the page, not in the
estimator. It is not-yet-due, due-and-unrun, or never-scheduled, and each is
reported as itself. Carry-forward skips stay skips. An arm whose call failed
records ERROR and is excluded from every rate rather than being charged with
an absence caused by our own network. The interval-censored estimator brackets
an unobserved transition to `(previous rung, this rung]` rather than pinning
it to a point. All of this makes the numbers smaller and slower to arrive,
which is the trade being made on purpose.

## Run it for real

```bash
cp .env.example .env      # add whichever provider keys you have
export TTI_USER_AGENT="you@example.com"   # SEC and arXiv require a contact

tti prereg                # the analysis plan, its hash, and whether it drifted
tti verify                # offline: is this installation's arithmetic sound
tti doctor                # is every source and provider reachable
tti discover --dry-run    # what would be collected right now, writing nothing
tti discover              # poll sources, enqueue the ladder
tti probe                 # run whatever is due
tti status                # queue depth and today's spend
tti score                 # the leaderboard, as markdown (or --json)
tti power                 # can this run support the claim it invites?
tti sensitivity           # does the ranking survive the rules that produced it?
tti decoy                 # how often does this pipeline say FRESH about a
                          #   version that was never published? (no API calls)
tti report                # write RESULTS.md and docs/index.html
tti placeholder           # the pre-run docs/index.html, before any results exist
```

Eleven commands take `--json`: `score`, `status`, `power`, `sensitivity`,
`forecast`, `watch`, `crawlability`, `survey`, `verify`, `prereg`, `decoy`. Nothing that is not a finite
number is emitted as a bare `NaN` or `Infinity` token — those parse in Python
and almost nowhere else — so a missing value arrives as `null` rather than as
a parse error or a silently coerced token.

Whatever a command declines to claim in its human output it declines in JSON
too: an unreachable median is `null` on both ends, a sensitivity variant that
could not be evaluated says so rather than reporting perfect agreement, and
every command returns a parseable document on an empty ledger, because a
monitoring wrapper polls from the first minute. The set of commands carrying
the flag is read from the argument parser in a test, so a new one cannot ship
without a strictness check.

Every command exits `2` on a configuration error — distinct from `1`, so a
cron wrapper can tell "misconfigured" from "ran and found nothing". `tti
doctor` validates every config file before it checks anything else.

Statistics, cost, pre-registration, `tti verify` and timing accuracy are in
[`docs/RUNNING.md`](docs/RUNNING.md): why fifteen comparisons need one α,
the instrument's own false-positive rate, where the cost column comes from,
and what a jittery runner does to the short rungs.

## Reproducing a number you don't believe

Every provider response is stored verbatim under `runs/raw/`.

```bash
tti regrade               # re-score stored payloads, no API calls
tti regrade --write       # apply the new verdicts
tti sensitivity           # re-grade under every rule variant (eight now) and diff the ranking
```

`--write` is the only destructive operation here, so it is the most careful:
the new file is written alongside and renamed over the original, the previous
one is kept with a timestamp, and it refuses to run while a probe run holds
the lock — a concurrent append between the read and the write would be
silently discarded.

`tti sensitivity` is the one to run first. It re-scores everything under
deliberately worse rules — plain substring matching, no `v` prefix, no
aliases, titles only, every text field cut to a 160-character snippet — and
reports verdict churn, Kendall rank correlation
against the reported ordering, and how many arms stopped being measurable.

```
rule variant                  churn    tau  medians  lost  ranking
strict  (reported)                —   1.00      0/2     0  pv/base pw/base
no-v-prefix                   33.3%   1.00      1/2     1  pv/base pw/base
titles-only                  100.0%   1.00      2/2     2  pv/base pw/base

'titles-only' makes 2 of 2 arms unmeasurable rather than reordering them —
the ranking looks stable under it only because there is nothing left to rank
```

That last line is there because rank correlation alone was not enough, and
the harness caught it about itself: a variant that reads no content collapses
every arm equally, so the order never changes and tau reports a perfect 1.00
for a table that has stopped meaning anything.

## Pre-commitment

Results get published when the pre-registered stopping rule says so — thirty
days, or the plan's pre-registered event target (191), whichever comes first — regardless of which provider
wins, including if the provider I find most interesting comes last, and
including if the answer is that all of them are fine and the metric is
boring. The raw payloads ship with the results either way.

Corrections are issued in-repo rather than silently re-run. If a vendor shows
that an adapter sends a call their API was not designed for, the fix is a
commit and a note in `RESULTS.md`, not a quiet re-render.

## Tests

```bash
pip install -e ".[dev]"
pytest -q && ruff check tti tests
```

Over 600 tests, on Python 3.10 through 3.13, no network calls. The ones that
matter:

- **Turnbull reduces to Kaplan–Meier** on right-censored data — a theorem, so
  running it on the Freireich 1963 6-MP arm ties the reported estimator to
  published values rather than to my own arithmetic. Kaplan–Meier itself is
  checked against those values separately.
- **A missing rung widens rather than shifts.** Two arms index identically;
  one had probes dropped. The bracket gets wider, the upper bound does not
  move.
- **Schoenfeld sample sizes** against the standard tables: for a hazard ratio
  of 2 the tables give 66; for 1.5, 191; for 1.2, 945 (events needed).
- **The `15.4.1`-inside-`15.4.10` substring trap**, which silently inflates
  freshness on exactly the packages that ship most often — and its twin, the
  `v15.4.2` prefix, which a strict word boundary rejects even though the
  answer is plainly there. Both directions are pinned.
- **Page bodies never reach the ledger.** They are used to classify where the
  fact lived and dropped; only an excerpt and a SHA-256 are kept, because a
  full body per event per rung is tens of megabytes a day.
- **403 is `blocked`, not `absent`.** An origin refusing our client says
  nothing about whether a crawler can reach it, and scoring it as "not on the
  web" would let a bot-walled page make every provider look slow.
- **Non-content fields are never evidence** — URLs, ids, request ids, and our
  own query echoed back.
- **A phrasing run leaves time-to-index bit-identical.** A second wording of
  the same event is a second observation, not a second event; counting it
  would inflate recall and narrow every interval.
- **Two cron runs cannot overlap.** Cron fires on a schedule, not on
  completion, so the moment a provider is slow enough that `tti probe`
  outlasts its interval the next run starts alongside it. Measured: six
  queued probes became twelve provider calls, six duplicate rows, and exactly
  double the spend, with every later rate counting one observation twice.
- **A dashboard of em dashes says so.** A run where every probe errored still
  produces arms, because arms come from the results file and an error is a
  result. The formatters correctly refuse to invent numbers, so every cell
  reads "—" and the page is not lying — but a rendered dashboard reads as
  results, so it now says at the top that the table is a list of arms rather
  than a set of them.
- **A hostile origin cannot exhaust memory.** Nothing capped response size,
  so a 200 MB chunked body took the process from 28 MB resident to 432 MB —
  and the existing caps truncated only after the whole thing was in memory.
  Reads are now capped as they stream, which is the difference between a
  truncated page and a dead unattended job.
- **Malformed API responses never crash a run or invent an event.** 38 cases
  across all six collectors — null documents, error objects returned where a
  list was expected, unparseable dates, and EDGAR's parallel arrays
  disagreeing in length. Every one produces zero events and leaves a
  per-subject error behind, so a source that has started returning garbage is
  visible rather than quiet.
- **A torn write does not destroy a month of collection.** This appends
  JSONL unattended for weeks; a reboot mid-write left a partial last line and
  every read path then raised. Worse, the next run's append fused onto that
  fragment and lost its own record too — the recovery path was eating the
  data it existed to save.
- **A formatter never turns a non-number into a claim.** `fmt_bracket(nan)`
  rendered as ">15m" — asserting something was never reached inside the
  window, from a value that was not a number. Visible garbage gets noticed;
  a confident claim manufactured from a NaN does not.
- **A malformed config is refused, never defaulted.** A YAML typo used to
  parse to something unusable, every lookup fell back to a hard-coded
  default, and the daily spend cap silently became $5 while the file said $6
  — at exit code 0.
- **A full pipeline run** against a scripted provider on a virtual clock:
  the estimator recovers a 1-hour indexing latency it was never told,
  carry-forward stops paying once an arm is FRESH, and the budget cap refuses
  rather than truncates.

## Notes from building it

[`docs/INTEGRATION-NOTES.md`](docs/INTEGRATION-NOTES.md) records the friction
of wiring up each source and provider — what the docs got wrong, what needed
a contact header, what returns 403 to a non-browser client. It is the most
reusable thing a benchmark produces and the part that usually goes unwritten.
Everything in it is marked **Observed** (hit while building this, reproducible
from it) or **Open** (a question a real run will answer, and has not yet).

## Contributing

[`CONTRIBUTING.md`](CONTRIBUTING.md) — how to add a provider (about twenty
lines), add a source (one rule: it must stamp its own publication time), or
argue with a number without writing any code at all.

## Release status

0.1.0 is the first public release. [CHANGELOG.md](CHANGELOG.md) lists what
it contains, [SECURITY.md](SECURITY.md) covers keys and how to report a
problem, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) sets the terms for
arguing with a number.

## Citing

If you use the benchmark or its method, cite it; [CITATION.cff](CITATION.cff)
has the same record in machine-readable form.

```bibtex
@software{das_time_to_index_2026,
  author  = {Das, Abhijit},
  title   = {Time to Index: a freshness and staleness benchmark for web-search APIs},
  year    = {2026},
  version = {0.1.0},
  url     = {https://github.com/abhid1234/time-to-index},
  license = {MIT}
}
```

## License

MIT.
