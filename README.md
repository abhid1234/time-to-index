# Time to Index

**How long does a newly published fact take to become retrievable through a
web-search API — and until it does, what does the API return instead?**

Retrieval benchmarks score whether a provider can find the right answer. This
one scores *when*, and it separates two failures that every other benchmark
collapses into one:

| | the agent's next move |
|---|---|
| **ABSENT** — provider returns nothing relevant | retries, widens, or says it doesn't know |
| **STALE** — provider confidently returns the answer that was superseded | cites it |

Scored as "wrong", these are identical. In production they are not remotely
the same event, because nothing downstream of a stale citation can tell that
it is wrong.

**[Walk through it interactively →](https://abhid1234.github.io/time-to-index/playground.html)** — two
things on one page. A simulation you can drive: run the ladder against four
anonymous indexes, then change the scoring rule and watch the ranking invert.
And below it, the real thing: every probe this project has actually run, named
providers, one square per arm per rung, read straight from the committed
ledger.

Read them for different things. The simulation is hand-authored and shows how
the instrument reasons, not how any product performs. The measured panel is
real but still small — see [What can and cannot be
claimed](#what-can-and-cannot-be-claimed) before drawing a conclusion from it.

---

## Related work: what the Artificial Analysis Search Index measures

In August 2026 Artificial Analysis launched a
[Search Index](https://artificialanalysis.ai/articles/search-api) for search
APIs used by agents, with
[published methodology](https://artificialanalysis.ai/methodology/search-api)
and a [live leaderboard](https://artificialanalysis.ai/agents/search-api).
It is the most serious work in this area and it covers the same products this
does — Parallel, Exa, Brave, Tavily, Firecrawl, You.com, Keenable.

It is also the clearest example of the thing this project exists to point at.

Their index is the equal-weighted mean of three benchmarks — DeepSearchQA
(average F1), BrowseComp (exact-answer accuracy) and AA-Omniscience
(accuracy) — run through a fixed agent harness with `web_search` and
`web_fetch` tools, 25 turns, and one model held constant so the search API is
the only thing that varies. That is a good design for the question it asks,
which is **how well can an agent answer with this search API behind it.**

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

**A 25-turn agent loop hides ABSENT and preserves STALE.** Given unlimited
tool calls, an agent that gets nothing back can retry, rephrase, widen, and
fetch its way to the answer, so an absence costs turns and tokens rather than
correctness. An agent that gets a confidently wrong superseded answer has no
signal that anything went wrong and stops. The more agentic the harness, the
more absence is absorbed and the more staleness survives into the graded
answer — which means the harness that best models production use is also the
one where the ABSENT/STALE distinction matters most and is least visible.
That is a claim from their published design, not something measured here.

Their numbers as of launch — Parallel Search advanced and Brave LLM-context
at 75, Exa auto at 74, Firecrawl at 73 — are theirs to state and worth
reading at the source. This project deliberately publishes no competing
quality score.


---

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

A provider can only return what it could read. Two commands, no keys and no
ledger required, measure the corpus rather than the providers:

```bash
tti crawlability https://yoursite.com --find "the fact you care about"
tti routes https://yoursite.com --sample 8    # sample the site's own sitemap
tti survey                                     # scan data/corpus.yaml
tti survey --out-dir docs                      # ...and render corpus.html
tti watch --out-dir docs                       # ...with the change history
```

The corpus half gets its own page rather than a section of the provider
dashboard, because the two measure different things on different schedules
and a combined page would imply a joint analysis that only exists once both
have run. It refuses whatever the terminal refuses: unreachable, unstable and
intercepted targets appear as excluded with the reason, never folded into the
rate.

`crawlability` answers the two questions that decide whether a page enters an
AI system: is the content in the served bytes as text, and is the crawler
allowed to fetch it. Run against three package registries:

```
crates.io/crates/serde       sveltekit   client_shell        32 chars visible of 5,056
pypi.org/project/httpx/      —           static_html      9,898 chars visible of 141,336
pkg.go.dev/…/gin             —           static_html     93,012 chars visible of 429,377
```

Same kind of site, same kind of fact, opposite outcomes. The sharpest
category the survey reports is pages that **allow every AI crawler in
robots.txt and ship them nothing at all** — no readable body and no metadata.
Nobody chose that. It falls out of a rendering default, and the robots.txt
records that the team wanted the opposite.

`tti watch` records each run and reports where posture *moved*. That is the
statement a single scan cannot make and the only one that is actionable:
nobody decides to become invisible to agents, they ship a refactor and no
signal turns red. There is no build check, no deploy gate and no dashboard
panel that goes red when a route stops being readable, so a regression is
only ever visible in hindsight — and only if something was watching.

```bash
tti watch                 # record a run
tti watch --report        # what moved, without fetching
```

It refuses to overclaim: one run is not a series, and under a day of history
"nothing changed" describes the observation window rather than the web. Both
are printed rather than assumed.

`tti routes` exists because one page is enough to prove a failure and not
enough to describe a site. Marketing pages are almost always server-rendered;
the interesting failures are on detail pages. It reads the site's own sitemap,
samples evenly across the sorted route list (deterministically, so two runs
examine the same routes and a site that changed is distinguishable from a
sample that moved), and reports the spread.

Four things keep these claims honest, and each was added because an earlier
version of one was wrong:

- **A verdict needs repeat fetches to agree.** The same URL returned 5,056
  bytes of client shell on one run and a zero-byte 404 on the next. A page
  that answers differently across fetches is excluded, not judged.
- **A response has to be big enough to be a page** before it can be called a
  bad one. An early version reported a proxy error as "client shell, not
  readable".
- **Metadata counts.** A shell that ships JSON-LD or OpenGraph is
  `metadata_only`, not unreadable: an agent learns what the page is without
  executing anything. It still does not learn what the page says, so it is a
  third state rather than a pardon.
- **Identical bodies across distinct URLs are interception, not a posture.**
  Six different PyPI project pages returned byte-identical 3,036-byte bodies
  with HTTP 200, and the first version of `tti routes` duly reported that PyPI
  is entirely client-rendered. It is not. CDN challenges, WAF blocks and
  soft-404s all answer 200 and all classify cleanly as a client shell. Every
  member of an identical group is now excluded — not all-but-one, because
  keeping a representative assumes one of them is the real page and in the
  interception case none of them is.

This half is deliberately vendor-neutral and framework-neutral. Posture
predicts retrievability; framework only correlates with it, and the
aggregation says so.

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
recorded at a lag the ladder cannot honestly place. Dropping is the correct
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

## Look at it without paying for it

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

### Fifteen comparisons, one α

Six arms make fifteen pairwise comparisons. Judging each against a raw
α = 0.05 gives a **54%** chance that at least one pair is called different when
neither is. That was this repository's behaviour in two places, and it is the
most ordinary statistical mistake there is — ordinary enough that a project
built around not over-claiming had it anyway.

Every pairwise log-rank p-value is now Holm–Bonferroni adjusted across the
whole family, both values are reported, and the verdict column uses the
adjusted one:

```
comparison                              HR  events        p    p adj  power   need  days  verdict
provider-a/fast vs provider-b/base    2.77     205  <0.0001  <0.0001   100%     30     0  distinguishable
```

A p-value below the printed precision reads `<0.0001`, never `0.0000`: no
finite sample supports a probability of exactly zero.

Holm rather than plain Bonferroni: same control of the family-wise error rate,
uniformly more power, and no independence assumption — which matters, because
pairs sharing an arm are correlated. Benjamini–Hochberg is deliberately not the
default: it controls the false discovery rate, which suits a screen producing
candidates for follow-up. A leaderboard is not a screen. Somebody reads one row
and picks a vendor.

### The instrument's own false-positive rate

Every recall number rests on one unchecked assumption: that when the pipeline
says FRESH, the provider really surfaced the new fact. Two ways that fails, and
neither shows up anywhere in a leaderboard — the grader matching a
version-shaped token in unrelated prose (`15.4.1` inside `15.4.10` was exactly
this, and it shipped), or a generative answer layer inventing a plausible
version number.

`tti decoy` measures it. For every event it mints a **counterfactual** — a
token of the same shape as the real answer, for the same subject, that the
registry confirms was never published — and re-grades every stored payload
against it. A FRESH verdict for a version that does not exist is a false
positive by construction.

```
| arm | payloads re-graded | false positives | rate (95% CI) |
|---|---|---|---|
| `guesser/base` | 40 | 4 | 10.0% (4–23) |
| `honest/base`  | 40 | 0 |  0.0% (0–9)  |

Each arm's recall carries its own upper error bar from the column above:
  guesser/base: up to 23% of its FRESH verdicts could be spurious.
  honest/base: up to 9% of its FRESH verdicts could be spurious.
```

Two properties make it worth running rather than merely worth describing:

- **It costs nothing.** The payloads are already stored; `tti decoy` makes zero
  provider calls. There is no budget argument for skipping it, so it can run
  beside every published number.
- **It cannot be gamed by tuning the grader.** Loosening the rules to raise
  recall raises the false-positive rate in the same motion, and both numbers
  are printed side by side.

The counterfactual is minted deterministically, not randomly — two people
running this against the same ledger must get the same number or it is not a
measurement. A fixed offset occasionally lands on a version that really was
released; the registry check catches those and they are dropped and counted,
because grading against a real release would score true retrieval as a false
positive. Where the publisher cannot be asked, the counterfactual is used and
tallied separately: weaker evidence, labelled as such.

When no false positive is observed, the reported number is **not** 0%. It is
the Wilson upper bound, which at small n is large — and that bound is the
figure that belongs beside the recall numbers. So that is where it is: the
dashboard carries this table directly under the leaderboard, computed offline
from the stored payloads on every `tti report`, with a line saying that render
did not ask the registries and that `tti decoy` is the verified figure.

### Where the cost column comes from

Every arm's `$/1k events` and `$/1k fresh answers` are computed from
`data/providers.yaml`, where each price carries the vendor page it was read
from and the date it was last checked by hand. That is this repository's
reading of a page that changes: on 2026-09-02 one vendor's entry was 29% low
and another's named two modes that were not products.

Where a vendor states its own charge in the response — Exa does, as
`costDollars.total` — the ledger records that number instead, marks the row
`cost_source: reported`, and settles the day's spend to it. The cap gates
dispatch on the list estimate; settlement records what was billed, with no
cap check, because a call that has already happened has already cost what it
cost. `tti status` sums how far reported charges have diverged from the table
across the whole ledger, so a stale price shows up as dollars before it shows
up on an invoice.

### Pre-registration

The analysis plan is in [docs/PREREGISTRATION.md](docs/PREREGISTRATION.md),
written before the first probe was ever dispatched. It names the primary
endpoint, the arms, four hypotheses with the condition that would falsify
each, six exclusion rules, and a stopping rule.

The point is not the document. Benchmarks have had methodology sections for
decades, and they are written after the fact as often as not. The point is
that the plan is **locked to the data**:

- The plan and the machine's copy are the same bytes — one fenced block that
  the document itself renders — so the two cannot drift apart.
- `tti prereg` hashes the *canonical* form: sorted keys, whitespace collapsed.
  Rewording a sentence does not move the hash. Moving a threshold, adding an
  arm, or dropping a rung does.
- The hash is written into the run directory on the first dispatched probe.
  Before that there is nothing to be tempted by, so a plan edited up to that
  moment is a plan being *written*, not one revised in the light of results.
- Afterwards, every `tti score`, `tti report` and `tti verify` says whether the
  plan has changed — in the output, unprompted, at the top of the page.

Editing the plan is not forbidden. Plans are sometimes wrong. It is made
**visible**, which is the property that was actually needed.

Four labels follow onto every leaderboard:

| label | meaning |
|---|---|
| pre-registered | declared before collection began |
| exploratory | in the data and not in the plan — shown, not hidden |
| declared, enabled, produced nothing | the plan named it, a key was set, and it never scored |
| declared, not enabled | the plan named it and no key was set — a configuration state, not a result |

The third one matters as much as the others. A leaderboard is built from what
is in the ledger, so an arm that failed everywhere is simply not a row — which
is how a benchmark loses its worst result without anybody deciding to.

A test asserts that the plan's declared arms and ladder match `data/settings.yaml`.
A plan naming arms the runner never dispatches would invert the whole
mechanism: every real arm would read as exploratory and every declared arm as
silent. That was a real defect here, and that test is what caught it.

### `tti verify` — the check that does not need the network

`doctor` asks whether five providers are up, which is somebody else's uptime.
`verify` asks whether the numbers this installation would produce are right,
which is ours, and it answers offline:

```
  ✓ config     settings, providers, watchlist and corpus parse and satisfy their invariants
  ✓ estimator  Turnbull reproduces published Kaplan-Meier values on Freireich 1963 (worst disagreement 6.02e-11)
  ✓ grader     4 version-boundary cases graded as expected
  ✓ ledger     runs/: every line parses, 1,284 result(s), no duplicate probe ids
  ✓ platform   advisory file locking available; overlapping discover/probe runs are prevented
  ✓ prereg     plan bac218770f209b20 · v1 · 4 hypotheses, each with a falsification condition — locked, unchanged
```

The test suite proves the repository is correct at the commit CI ran. It says
nothing about the copy on the box that will actually produce the numbers —
its edited config, its collected ledger, its Python, its floating point. Each
of the six checks exists because the failure it catches once produced a
plausible answer rather than a crash: a config that silently defaulted a
spend cap, a version prefix matching inside a longer version, two cron runs
overlapping and double-counting every rate.

Exit codes are graded, not binary. `0` clean; `1` warnings — nothing wrong
yet, but a way this installation could become wrong without saying so (a
platform with no advisory locking, a torn ledger line that reads will skip);
`2` a failure that means the numbers are not publishable.

The control arm runs automatically and costs nothing — it is a plain HTTP GET
per event per rung, robots.txt honoured, and the spend cap never refuses it.
Losing it would be the worst possible economy: without it, every ABSENT from
every paid provider is ambiguous.

`discover` and `probe` are the two that belong on a timer; both are idempotent
and safe to re-run. Everything else is read-only over the ledger.

**Providers with no key are skipped, never simulated.** There is no fixture
path that can leak into a published result.

**Cold start is real.** On the first poll every watched subject looks new but
was published days ago, so every event is dropped for detection lag. The first
usable event arrives when the first watched package actually ships. That is
working correctly, and `tti discover` says so.

### Cost

With the shipped watchlist and six arms, the worst case is about **$2/day**
at list prices and roughly half that once carry-forward stops resolved
ladders (SETUP.md has the arithmetic). `data/settings.yaml` sets a hard daily cap; a probe that would cross
it is refused and written to the ledger as `SKIPPED`, and the dashboard
reports the count. A cap that silently stopped probing would look exactly
like a provider that silently stopped indexing.

Trim `data/watchlist.yaml` or `arms` in `data/settings.yaml` to spend less.
Both are where the volume is actually decided.

### Timing accuracy

GitHub Actions cron has minutes-to-tens-of-minutes of jitter, which is fine
for the ≥1h rungs and not fine for the 5m and 15m ones. Probes that fire too
late are dropped rather than misrecorded, so a jittery runner costs you the
short rungs instead of corrupting them. For the full ladder, run
`deploy/systemd/` on a small box with real timers.

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
days, or 191 events, whichever comes first — regardless of which provider
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

Over 500 tests, on Python 3.10 through 3.13, no network calls. The ones that
matter:

- **Turnbull reduces to Kaplan–Meier** on right-censored data — a theorem, so
  running it on the Freireich 1963 6-MP arm ties the reported estimator to
  published values rather than to my own arithmetic. Kaplan–Meier itself is
  checked against those values separately.
- **A missing rung widens rather than shifts.** Two arms index identically;
  one had probes dropped. The bracket gets wider, the upper bound does not
  move.
- **Schoenfeld sample sizes** against the standard tables: 66 events for a
  hazard ratio of 2, 191 for 1.5, 945 for 1.2.
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

## License

MIT.
