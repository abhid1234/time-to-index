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
   slow" is never confused with "the document was not on the web yet".
4. **Grade FRESH / STALE / ABSENT** against the new answer token and the one
   it replaced.
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

Full design, and everything that could make the numbers wrong, in
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Look at it without paying for it

```bash
pip install -e .
tti demo          # renders docs/demo.html and checks the estimator
```

`tti demo` runs a synthetic corpus with made-up providers (`provider-a/b/c`)
whose indexing latencies are drawn from a seeded generator, then reports
whether the estimator recovered the latencies it was never shown:

```
OK  provider-a/fast: estimated     5m–15m  true      7m  (n=106, indexed 105)
OK  provider-b/base: estimated   60m–6.0h  true    2.2h  (n=106, indexed 100)
OK  provider-c/base: estimated 24.0h–3.0d  true   40.3h  (n=106, indexed 65)
```

The demo writes `docs/demo.html` and never `docs/index.html`. It is evidence
about the instrument, not about any product.

## Run it for real

```bash
cp .env.example .env      # add whichever provider keys you have
export TTI_USER_AGENT="you@example.com"   # SEC and arXiv require a contact

tti doctor                # is every source and provider reachable
tti discover              # poll sources, enqueue the ladder
tti probe                 # run whatever is due
tti status                # queue depth and today's spend
tti power                 # can this run support the claim it invites?
tti sensitivity           # does the ranking survive the rules that produced it?
tti report                # write RESULTS.md and docs/index.html
```

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

~500 probes/day across five providers is roughly **$3–12/day** at list
prices. `data/settings.yaml` sets a hard daily cap; a probe that would cross
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
tti sensitivity           # re-grade under seven rule variants and diff the ranking
```

`tti sensitivity` is the one to run first. It re-scores everything under
deliberately worse rules — plain substring matching, no `v` prefix, no
aliases, titles only — and reports verdict churn, Kendall rank correlation
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

Results get published on the schedule below regardless of which provider
wins, including if the provider I find most interesting comes last, and
including if the answer is that all of them are fine and the metric is
boring. The raw payloads ship with the results either way.

Corrections are issued in-repo rather than silently re-run. If a vendor shows
that an adapter sends a call their API was not designed for, the fix is a
commit and a note in `RESULTS.md`, not a quiet re-render.

## Tests

```bash
pytest -q
```

72 tests. The ones that matter:

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
- **403 is `blocked`, not `absent`.** An origin refusing our client says
  nothing about whether a crawler can reach it, and scoring it as "not on the
  web" would let a bot-walled page make every provider look slow.
- **Non-content fields are never evidence** — URLs, ids, request ids, and our
  own query echoed back.
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

## License

MIT.
