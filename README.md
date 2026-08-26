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
3. **Ask every provider at t+5m, +15m, +1h, +6h, +24h, +72h.**
4. **Grade FRESH / STALE / ABSENT** against the new answer token and the one
   it replaced.
5. **Estimate with Kaplan–Meier**, right-censored at 72 hours, because most
   events are still un-indexed when the window closes and dropping them
   reports every provider as faster than it is.

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
tti report                # write RESULTS.md and docs/index.html
```

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
```

Change the matching rules in `tti/grader.py`, re-grade, and see how much the
leaderboard actually moves. That is the only reason to believe a benchmark
published by one person.

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

21 tests. The ones that matter:

- Kaplan–Meier checked against the published values for the Freireich 1963
  6-MP arm, the standard worked example for the product-limit estimator.
- The `15.4.1`-inside-`15.4.10` substring trap, which silently inflates
  freshness scores on exactly the packages that ship most often.
- A full pipeline run against a scripted provider on a virtual clock,
  asserting the estimator recovers a 1-hour indexing latency it was never
  told, that carry-forward stops paying once an arm is FRESH, and that the
  budget cap refuses rather than truncates.

## License

MIT.
