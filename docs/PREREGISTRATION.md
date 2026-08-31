# Pre-registration

**Status: registered, no data collected.** Written before the first probe was
ever dispatched, and locked to the ledger the moment one is. Every number this
project eventually publishes is either declared below or is labelled
**exploratory** in the output, automatically, by code that reads this file.

## Why a benchmark should do this

The failure mode this guards against is not fraud. It is the ordinary,
comfortable version: run the collection, look at the results, and *then* decide
which arms to compare, which events to exclude, and where to stop. Every one of
those choices is defensible in isolation and every one of them is made after
seeing which way it moves the answer. The published table is then a selection,
and nothing in it says so.

An industry benchmark is unusually exposed to this, because the people running
it usually want a particular provider to win, and because nobody re-runs it.
The only real defence is to fix the analysis before the data exists and make
the record of that unforgeable.

So: the plan is below, in a block that is simultaneously the human document and
the machine's copy — one set of bytes, so the two cannot drift. `tti prereg`
prints its hash. The hash is written into the ledger on the first probe of a
run. Any later edit that changes the *plan* (not the prose around it) makes
every subsequent `tti score`, `tti report` and `tti verify` say so, in the
output, unprompted.

That does not make changing the plan forbidden. Sometimes a plan is wrong and
should change. It makes changing it **visible**, which is the only property
that was ever actually needed.

## The plan

```yaml prereg
plan_version: 1
registered: 2026-08-31

primary_endpoint: >
  Median time from publication to first FRESH answer, per provider arm,
  estimated by the Turnbull NPMLE over interval-censored observations and
  reported as a bracket between adjacent ladder rungs with a bootstrap
  confidence interval on the bracket's upper edge.

secondary_endpoints:
  - >
    Pipeline false-positive rate: the proportion of stored payloads that grade
    FRESH against a counterfactual answer of the same shape, confirmed never
    published, per arm, with Wilson score intervals. Reported alongside recall
    rather than as a footnote, because it is recall's error bar.

  - >
    Staleness rate: of the observations that were not FRESH, the proportion
    that returned the superseded answer (STALE) rather than nothing (ABSENT),
    per arm per rung, with Wilson score intervals.
  - >
    Recall at the final rung: the proportion of events for which the arm ever
    answered FRESH within 72 hours.
  - >
    Recall by render posture: the same, partitioned by whether the origin page
    was server-rendered, static, metadata-only, a Flight payload, or a client
    shell.

arms_declared_in_advance:
  - parallel/base
  - parallel/pro
  - exa/auto
  - tavily/basic
  - brave/web
  - serper/search
  - origin/direct        # control; excluded from the leaderboard by construction

ladder_seconds: [300, 900, 3600, 21600, 86400, 259200]

hypotheses:
  - id: H1
    statement: >
      Arms differ in time-to-index by more than sampling noise.
    test: >
      Log-rank test across the declared provider arms, on the Kaplan-Meier
      fit retained alongside Turnbull for exactly this purpose.
    threshold: p < 0.05
    falsified_if: >
      p >= 0.05, or the estimated hazard ratio between the fastest and slowest
      arm has a confidence interval containing 1.

  - id: H2
    statement: >
      ABSENT and STALE are not interchangeable: at least one arm returns the
      superseded answer, rather than nothing, for more than 20% of its
      not-yet-FRESH observations at the 1-hour rung.
    test: >
      Wilson score interval on the STALE proportion among non-FRESH
      observations at rung 3600 for each arm.
    threshold: lower bound of the Wilson interval > 0.20 for at least one arm
    falsified_if: >
      Every arm's upper Wilson bound at rung 3600 is at or below 0.20. That
      result would mean retrieval misses are overwhelmingly silent, and the
      distinction this project is built on would not matter in practice. It
      is a real possible outcome and is stated here so it cannot later be
      quietly dropped.

  - id: H3
    statement: >
      Time-to-index depends on the origin page's render posture.
    test: >
      Log-rank across render classes, pooled over arms, with per-class recall
      at the final rung reported alongside.
    threshold: p < 0.05
    falsified_if: >
      p >= 0.05, or fewer than 15 events land in any class being compared, in
      which case the comparison is reported as underpowered rather than null.

  - id: H4
    statement: >
      The pipeline's own false-positive rate is small enough that the recall
      ordering between arms is not an artifact of it.
    test: >
      `tti decoy` per arm; compare each arm's Wilson upper bound on the
      false-positive rate against the recall gaps in the leaderboard.
    threshold: >
      the upper bound is below half the smallest recall gap that the
      leaderboard is used to claim
    falsified_if: >
      Any arm's false-positive upper bound exceeds a recall difference the
      leaderboard reports as meaningful. In that case the ordering is reported
      as unresolved rather than as a result, and the grader is the thing that
      needs work, not the write-up.

exclusions_declared_in_advance:
  - id: X1
    rule: detection_lag > max_detection_lag_seconds
    reason: >
      The first rung has already passed by the time we saw the event. Its
      ladder cannot be honoured and attributing our collection delay to a
      provider would be false.
  - id: X2
    rule: rung_slip > max_rung_slip_seconds
    reason: >
      The runner was down. Recording a 105-minute observation at the 15-minute
      rung is a lie; recording it at 105 minutes biases the ladder.
  - id: X3
    rule: publication timestamp ahead of our clock by more than max_clock_skew_seconds
    reason: >
      The ladder would anchor to a t0 that has not happened.
  - id: X4
    rule: origin body below MIN_BODY_BYTES, or byte-identical across distinct URLs
    reason: >
      A challenge page or a proxy error, not a render posture. Classifying it
      as one would publish an artifact of our own network as a finding about
      somebody else's site.
  - id: X5
    rule: the origin/direct arm, in any leaderboard
    reason: >
      It fetches the canonical URL. It has near-perfect recall at zero cost by
      construction, and listing it beside the providers invites the exact
      comparison it exists to make unnecessary.
  - id: X6
    rule: any watchlist subject exceeding 6% of the collected event corpus
    reason: >
      Concentration. One extremely chatty package can make the benchmark a
      measurement of that package's CDN. Applied to the watchlist before
      collection, from measured 60-day history, not to the results after.

stopping_rule: >
  Collection stops at the earlier of: 30 days of wall-clock, or the point at
  which the number of events reaches the Schoenfeld requirement for the
  smallest effect declared interesting (HR 1.5, 191 events). The leaderboard is
  not to be inspected for the purpose of deciding when to stop; `tti forecast`
  projects the stopping date from collection rate alone, before any scoring.

analysis_not_declared_here: >
  Anything else. Subgroup comparisons, per-source breakdowns, arm subsets,
  alternative graders and re-ranked leaderboards may all be worth looking at
  and are all exploratory. They are labelled that way in the output rather
  than being forbidden, because the useful thing is the label, not the ban.
```

## What the lock actually does

`tti prereg` canonicalises the block above — sorted keys, normalised
whitespace, prose collapsed — and hashes that, not the file. Rewording this
paragraph does not change the hash. Adding an arm, moving a threshold, or
deleting a falsification condition does.

On the first probe of a run, that hash is written to the ledger. From then on:

| what happens | what the output says |
|---|---|
| plan unchanged | reported quantities are marked `pre-registered` |
| plan edited after collection began | every score, report and verify names the change and the arms it affects |
| an arm appears in the data that the plan never declared | that arm is marked `exploratory` in the leaderboard |
| an arm the plan declared produced nothing | named as a declared arm with no data, rather than silently absent |

The last row matters as much as the others. A declared arm that vanishes from a
table is how a benchmark loses its worst result without anybody deciding to.
