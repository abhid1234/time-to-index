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

**Clock skew.** Every ladder is anchored to the publisher's timestamp, not
one we observed — that is the point, since it is the only clock describing
when the fact entered the world. It also means the measurement inherits
whatever that clock says. A publisher a few seconds ahead is ordinary; one
days ahead anchors the ladder to a time that has not happened, so every lag
it produces describes nothing while the event looks entirely normal on the
way in. Beyond 120 seconds of forward skew the event is dropped and counted
separately from a late detection, because the causes differ: one is our
polling interval, the other is someone else's clock.

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

## The phrasing axis

The first version of this listed "no phrasing-sensitivity arm" as a
limitation. This closes it.

Questions come from one template per source. An agent does not ask the
question a template would write — it asks whatever its own planner produced
that turn. If a provider returns the new fact for "latest version of next"
but not for "which version of the next npm package was released most
recently", the freshness number attached to it is about the phrasing as much
as the index.

So `tti` can ask the same event, at the same rung, through the same provider,
three ways: a full natural-language question, a differently-worded question
with the same content, and a terse keyword string of the kind a planner emits
once it has decided what it is looking for. Phrasing 0 is always the
canonical question verbatim, so a run with the axis on is directly comparable
to one with it off.

The metric is **agreement**: of the events where *any* wording came back
fresh, what share of wordings did? An arm at 100% is phrasing-insensitive at
that rung. An arm at 40% has the document and does not reliably surface it —
a different failure from not having it, and one an agent hits far more often
than a benchmark does.

Two design constraints:

- **Off by default, and rung-limited when on.** Three wordings at every rung
  triples the bill. Three at one rung adds two probes per event.
- **Phrasing probes are excluded from every primary metric.** A second
  wording of the same event is a second observation, not a second event.
  Counting it would inflate recall and narrow every interval. The exclusion
  is enforced in `metrics.py` and there is a test that a phrasing run leaves
  time-to-index bit-identical.

Templates that cannot be filled from an event's metadata are skipped rather
than rendered with an empty slot: a question with a hole in it measures the
hole.

## Refusing to answer

A recurring shape in this repo: the failure that looks most like a finding is
an infrastructure failure. Every guard below exists because that mistake was
actually made here, in this repository, in the form described.

| what it looked like | what it was | guard |
|---|---|---|
| "client shell, not readable" | a zero-byte proxy error | a response must exceed a minimum size before it can be judged |
| a confident render verdict | a URL that answered differently on the next fetch | repeat fetches must agree |
| "this whole registry is client-rendered" | one challenge page served for six routes | byte-identical bodies across distinct URLs are excluded |
| "0 new events" | an unreachable host | collectors track per-subject errors; an all-failed source is reported broken |
| a $5 daily spend cap | a config file saying $6, with a YAML typo | every config file is validated on load and refused, never defaulted |
| ">15m" on the dashboard | a NaN reaching a formatter | formatters render "—" for anything not a finite, non-negative number |
| an unreadable month of data | one interrupted write | malformed lines are skipped and counted, and `tti status` names the damage |
| twice the spend and every rate doubled | two cron runs overlapping | an advisory lock; a second run exits zero saying it was early |
| "Eight commands take `--json`" | a sentence written once and never re-read | the README's list and its count are checked against the argument parser |
| "distinguishable, p = 0.03" | one of fifteen pairwise tests, each judged against a raw 0.05 — a 54% chance of at least one spurious call | Holm–Bonferroni across the whole family; the verdict uses the adjusted value |
| 78% recall | possibly 78% minus an unmeasured false-positive rate | every payload is re-graded against a counterfactual answer that was never published |
| an analysis plan declaring `exa/base` | the runner dispatches `exa/auto`; every real arm would have read "exploratory" and every declared arm "produced nothing" | the plan's arms and ladder are asserted equal to `data/settings.yaml` |

The pattern is the same every time: something that is not a measurement
classifies perfectly as one. Each guard costs data — dropped events, excluded
routes, a smaller denominator — and the trade is deliberate. A benchmark that
publishes an artifact of its own network has not measured anything and cannot
tell that it has not.

Five of these guards run as a command rather than only as tests. `tti verify`
re-checks, offline and on the machine that will produce the numbers, that the
config is valid, that Turnbull still reproduces published Kaplan-Meier values
on Freireich 1963, that the version-boundary cases still grade correctly, that
the ledger on disk parses with no duplicate probe ids, and that advisory
locking is available on this platform. CI proves the repository was correct at
a commit; this proves the installation is correct now. The distinction is not
pedantic — the spend-cap bug and the overlapping-cron bug were both properties
of a deployment, not of a diff.

## The number of comparisons a leaderboard invites

Six arms make fifteen pairwise comparisons. Testing each at α = 0.05 and
calling anything below it "distinguishable" gives a family-wise error rate of
1 − 0.95¹⁵ = **54%**: more likely than not, at least one pair is reported as
different when neither is.

That was this repository's behaviour, in two places — the dashboard's pairwise
panel and the power table — and it is the most ordinary statistical mistake
there is. Ordinary enough that a project built entirely around not
over-claiming had it anyway, which is the useful part of writing it down.

Holm–Bonferroni, not plain Bonferroni: a step-down procedure that controls the
family-wise error rate exactly as strictly, is uniformly more powerful, and —
the reason it matters here — assumes nothing about independence. Pairwise
comparisons share arms, so their p-values are correlated, and a procedure that
needed independence would be the wrong tool.

Benjamini–Hochberg is deliberately not the default. It controls the false
discovery rate, which is right when a screen produces candidates for follow-up.
A leaderboard is not a screen. Somebody reads one row and picks a vendor, so
the quantity to control is the chance that *any* claimed difference is
spurious, not the expected share of them.

Both p-values are reported, raw and adjusted. Publishing only the adjusted one
would make the correction unauditable; the verdict column uses the adjusted
one, and says so.

A comparison that could not be computed — too few events, an arm with nothing
in it — carries through as no value and is excluded from the family size.
Counting a test that never ran would shrink every other comparison's adjusted
value for nothing.

## Measuring our own false positives

A leaderboard can only be read if the FRESH verdicts in it are real. Two ways
they are not, both of which leave the payload looking entirely ordinary: the
grader matches a version-shaped token that is not the answer, or the provider
invents one. Neither is visible in any statistic this project otherwise
computes, and both inflate recall in the same direction.

`tti decoy` re-grades every stored payload against a **counterfactual**: a
token of the same shape as the real answer, for the same subject, confirmed
absent from the publisher. A hit is a false positive by construction, and the
rate is the error bar that belongs on every recall figure.

Three details that decide whether the number means anything:

**Same shape as the real answer.** A decoy that does not look like a plausible
release measures the decoy — the grader declines it for the wrong reason and
the false-positive rate is an artifact of the decoy's weirdness. So the
counterfactual is a semantic version derived from the real one, and events
whose answers are not semver (SEC filings, arXiv identifiers) are skipped with
a stated reason rather than given an invented token.

**Deterministic, not random.** Two people running this against the same ledger
must get the same number. A random offset would make the check unreproducible,
which is the property it exists to supply.

**Verified absent, or labelled unverified.** A fixed offset lands on a real
release occasionally. Grading against one would score true retrieval as a false
positive, so it is dropped and counted. Where the publisher cannot be asked,
the counterfactual is used and tallied separately — an unverified
counterfactual is weaker evidence, and pretending otherwise would overstate the
check that exists to keep us honest.

The reported figure at zero observed hits is not 0%. It is the Wilson upper
bound, which at small n is large, and that is the number that goes beside the
recall column. Reporting 0% would be the same mistake as reporting a median
from the events that happened to index.

## Pre-registration

See [PREREGISTRATION.md](PREREGISTRATION.md) for the plan itself. The
mechanism, and why it is a mechanism rather than a promise:

The plan lives in one fenced block that the human document renders — the same
bytes serve both readers, so there is no second copy to fall out of date.
`tti prereg` hashes its *canonical* form (sorted keys, collapsed whitespace),
which means re-wrapping a sentence leaves the hash alone while moving a
threshold does not. That distinction is the whole design: a lock that fires on
typo fixes gets ignored, and an ignored lock is not a lock.

The hash is written into the run directory by the first probe that is actually
dispatched. Editing the plan before that point is writing it; editing it after
is revising it in the light of data, and only the second is worth flagging.
From then on every `score`, `report` and `verify` reports the comparison.

One subtlety was a bug. Whether collection has started is normally read from
`bool(ledger.results())` — which is empty when *every* line of the results file
is torn, because the reader skips malformed lines by design. The run would look
like it never began, the drift check would be skipped, and a plan edited after
the data would pass silently, at exactly the moment ledger damage should be
making everyone more careful. The lock file only exists because a probe ran, so
its presence now outranks the inference.

Nothing here forbids changing the plan. It makes the change visible, which is
the only property that was ever actually needed.

## Statistics

**Time to index is a survival problem.** Most events are still un-indexed at
the last rung, so the observation is "longer than 72 hours", not a number.
Dropping those and taking the median of the rest is the obvious thing to do
and it is wrong in a specific direction: it discards exactly the slow cases.
Worse, the bias does not cancel across a leaderboard — it is largest for the
provider with the most un-indexed events, so it can reorder the ranking.

**And it is interval-censored, not right-censored.** This is the part that
took a second pass. An arm seen ABSENT at 15m and FRESH at 1h did not index
*at* 1h — it indexed somewhere in (15m, 1h]. Kaplan–Meier needs a point event
time, so feeding it the rung overstates every latency by up to a bracket
width. Worse, when a probe is dropped — budget cap, rung slip, provider error
— the true interval widens to (15m, 6h], and Kaplan–Meier cannot represent
that at all. It either invents a rung nobody observed or discards the event.

So the reported estimator is **Turnbull's nonparametric MLE for
interval-censored data** (Turnbull 1976, in the EM formulation of Gentleman
and Geyer 1994). Each observation is an interval; right-censored ones run to
infinity. The estimator finds the support intervals where the data can
actually locate probability mass and solves for the mass by self-consistency.

A dropped probe then *widens* an interval instead of removing an event. That
is not a rounding detail: it means a run with a flaky provider, an exhausted
budget, or a missed cron tick still contributes its events at honest, wider
precision.

Kaplan–Meier is kept alongside it and the dashboard prints the gap between
the two, rather than deleting the comparison. If the gap is ever small, the
ladder is fine enough that the choice of estimator does not matter — worth
knowing too.

Correctness is anchored rather than asserted. Turnbull's estimator provably
reduces to Kaplan–Meier when every observation is either an exact event or
right-censored, so the test suite runs it on the Freireich 1963 6-MP data —
whose Kaplan–Meier values are published, and separately checked — and
requires the two to agree to 1e-6.

**Medians are reported as brackets.** The survival function is genuinely
undefined *inside* a support interval: the data cannot say where in (15m, 1h]
the mass sits. Reporting a point median would be inventing that information.

**Non-convergence is reported, not swallowed.** The EM fit carries a
converged flag, and an arm whose estimator hit the iteration ceiling is
called out on the dashboard. A non-converged fit still renders a
plausible-looking median, which is exactly why it needs saying.

**Rates get Wilson intervals**, not normal-approximation ones. At n≈40 events
per source class the normal approximation puts the lower bound of a 100%
recall below 90% and the upper bound of a 0% staleness above 0.

**Differences get a log-rank test.** "A is faster than B" needs a test that
handles censoring; a t-test on the indexed subset will find differences that
are artefacts of who ran out of window first.

**And a power calculation, printed next to it.** A leaderboard invites a
claim, and after two days of collection that claim is usually unsupportable.
The failure mode is not a wrong number — it is a true number with a
confidence interval nobody printed, repeated until it sounds settled. So
`tti power` reports, per pair: the hazard ratio from the log-rank O/E
statistic, the power the run currently has, the events Schoenfeld's formula
says 80% power would take, and how many more days that is at the observed
event rate. A hazard ratio of 2 needs 66 events; a ratio of 1.2 needs 945.
That gap is the whole argument for saying "not distinguishable yet" out loud
instead of ranking arms that sit inside each other's noise.

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
- **Question phrasing.** Questions come from templates, and the phrasing arm
  below is off by default and rung-limited when on, so most runs measure a
  single wording per event.
- **Provider request shape.** Each adapter sends what that vendor's own
  documentation describes as the standard call. Parallel's API takes an
  objective plus literal queries, which is a different contract from the
  others; sending only the objective would compare its rewriter against other
  providers' raw matching, and sending only the literal query would discard
  what the product is for. Both are sent. Reasonable people could set that
  dial differently, and the adapter is twenty lines.
- **Geography and time of day.** All probes run from one region on one
  schedule. Crawl cadence is not uniform across either.
- **Origin verification is not universal.** Where an origin blocks
  non-browser clients, conditional recall simply has fewer events, and npm —
  one of the highest-volume sources here — is one of those. The fallback to
  a registry document answers a weaker question, and events verified only at
  rank 1 should be read as such.
- **Render classification is not a browser.** A fact placed by JavaScript at
  runtime from data not present in the served bytes reads as `not_present`
  here even though a rendering crawler would find it. The class is a
  statement about the raw response, not about what is reachable in principle.
- **The control shares our network.** If a CDN serves us differently than it
  serves a commercial crawler, the control measures our view of the origin,
  not the crawler's. It bounds the confound rather than eliminating it.

**Medians carry a bootstrap interval.** A median printed without one is the
most common way a short run gets over-read: at forty events a bracket can
land a rung either side on luck alone, and the ordering of the table is
exactly what that luck moves. The interval is a nonparametric bootstrap on
the bracket's upper edge, seeded so it does not change when the page is
re-rendered. Where the median is not reached inside the window in some
resamples, that share is printed instead of hidden — for a slow arm it is the
finding, not a caveat.

## Does the ranking survive the rules that produced it

Every grading rule above is a judgement call. Match on token boundaries or
not. Count a `v` prefix. Trust aliases. Read titles only. Treat a URL as
evidence. Each is defensible; none is forced.

A benchmark published by one person should be able to say how much of its
ranking survives those calls being made differently, so `tti sensitivity`
re-grades every stored payload under deliberately worse rule sets and reports
what moved. It makes no API calls — this is what the verbatim payloads are
for.

Three numbers, because the first two are not enough:

- **Verdict churn** — the share of individual probe verdicts that change.
- **Kendall's tau** — rank correlation against the reported ordering.
- **Arms lost** — how many arms stopped being measurable at all.

That third one exists because the harness caught a flaw in itself. A variant
that reads no content collapses every arm identically: the ordering never
changes, tau comes back a perfect 1.00, and the table has stopped meaning
anything. Rank correlation alone would have called that robustness. High
churn with a stable tau is the *good* case — the rule matters locally and
washes out in aggregate. A high arms-lost count with a stable tau is the
trap.

A variant that reorders the top of the table is not a bug to be suppressed.
It is the most important thing on the page, and it belongs beside the ranking
rather than in a footnote.

## Reproducing

Every provider response is stored verbatim under `runs/raw/`. `tti regrade`
re-scores those payloads with whatever rules are in `grader.py` and reports
how many verdicts moved, without making a single API call.

If you think the matching rules are wrong, change them and see how much the
leaderboard actually moves. That is the only reason to believe a number
published by one person.
