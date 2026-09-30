# Running it: statistics, cost and verification

Reference for running the benchmark. The [README](../README.md) has the short version.

## Fifteen comparisons, one α

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

## The instrument's own false-positive rate

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
| `candid/base`  | 40 | 0 |  0.0% (0–9)  |

Each arm's recall carries its own upper error bar from the column above:
  guesser/base: up to 23% of its FRESH verdicts could be spurious.
  candid/base: up to 9% of its FRESH verdicts could be spurious.
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

## Where the cost column comes from

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

## Pre-registration

The analysis plan is in [docs/PREREGISTRATION.md](PREREGISTRATION.md),
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

## `tti verify` — the check that does not need the network

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

## Cost

With the shipped watchlist and six arms, the worst case is about **$2/day**
at list prices and roughly half that once carry-forward stops resolved
ladders (SETUP.md has the arithmetic). `data/settings.yaml` sets a hard daily cap; a probe that would cross
it is refused and written to the ledger as `SKIPPED`, and the dashboard
reports the count. A cap that silently stopped probing would look exactly
like a provider that silently stopped indexing.

Trim `data/watchlist.yaml` or `arms` in `data/settings.yaml` to spend less.
Both are where the volume is actually decided.

## Timing accuracy

GitHub Actions cron has minutes-to-tens-of-minutes of jitter, which is fine
for the ≥1h rungs and not fine for the 5m and 15m ones. Probes that fire too
late are dropped rather than misrecorded, so a jittery runner costs you the
short rungs instead of corrupting them. For the full ladder, run
`deploy/systemd/` on a small box with real timers.
