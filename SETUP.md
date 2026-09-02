# Running it

The code is finished enough to produce results. Nothing else about this
project matters until it has.

## Where it can run

**Not from a Claude cloud session.** All five provider APIs are unreachable
from that sandbox's egress proxy — `api.parallel.ai`, `api.exa.ai`,
`api.tavily.com`, `api.search.brave.com`, `google.serper.dev` all fail at
the tunnel, before any auth. So do `data.sec.gov`, `export.arxiv.org`,
`www.federalregister.gov` and `api.github.com`.

Three real options:

| where | what you get | what you lose |
|---|---|---|
| **A small VPS** | the whole ladder, accurate timing | ~$5/mo, ten minutes of setup |
| **GitHub Actions** | free, no machine to keep alive | the 5m and 15m rungs — cron jitter exceeds the slip window, so those probes are dropped rather than misrecorded |
| **Your laptop** | free, already exists | every rung due while it is asleep or offline |

Recommended: the VPS, with `deploy/systemd/`. `AccuracySec=30s` is the line
that matters; systemd's default batches timers to let the CPU sleep, which
is exactly wrong for a five-minute rung.

The GitHub Actions path is not a bad fallback — it just measures a shorter
ladder, and `tti probe` reports how many probes it dropped for rung slip, so
the loss is visible rather than silent.

## Keys

Five providers, each skipped rather than simulated when its key is absent.
You do not need all five; three is enough for a meaningful comparison.

| provider | where | env var |
|---|---|---|
| Parallel | docs.parallel.ai | `PARALLEL_API_KEY` |
| Exa | exa.ai | `EXA_API_KEY` |
| Tavily | tavily.com | `TAVILY_API_KEY` |
| Brave | brave.com/search/api | `BRAVE_API_KEY` |
| Serper | serper.dev | `SERPER_API_KEY` |

Also worth setting:

- `GITHUB_TOKEN` — raises the releases collector from 60 to 5,000 requests/hour.
  Without it, that source cannot cover a real watchlist.
- `TTI_USER_AGENT` — a real contact string. SEC's fair-access policy and
  arXiv's terms both require one and will refuse requests without it.
  `tti doctor` checks.

Free tiers change; check each provider's current one rather than trusting a
number written here. The daily cap in `data/settings.yaml` is what actually
protects you.

## Cost

Computed from `data/providers.yaml` list prices, not estimated:

```
per full rung sweep across 6 arms      $0.027
worst case, 13.1 events/day, 6 rungs   $2.12/day
with carry-forward stopping ladders    ~$1.15/day
```

(List prices as of 2026-09-02, five results per request. The two Parallel
arms are `advanced` at $5/1k and `fast` at $1/1k; if you change the arms in
`data/settings.yaml`, the plan in `docs/PREREGISTRATION.md` must change with
them, and a test will tell you if it has not.)

Carry-forward is why the real number is roughly half the worst case: once an
arm answers FRESH for an event, its remaining rungs are skipped. The cap in
`data/settings.yaml` is $6/day, and a probe that would cross it is refused
and written to the ledger as `SKIPPED` rather than dropped quietly.

## The four commands

```bash
git clone <your-repo> && cd time-to-index
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m tti verify         # install is sound: config, estimator, grader, ledger, locking
cp .env.example .env         # add your keys
set -a && source .env && set +a

python -m tti doctor         # every source and provider reachable? ~6s
python -m tti forecast       # how long until this can support a claim?
python -m tti discover && python -m tti probe    # then put both on a timer
```

Then `deploy/systemd/` or `.github/workflows/probe.yml`, and leave it.

`python -m tti` and `tti` are the same program. Prefer the first: the `tti`
console script is a `#!/bin/sh` wrapper that breaks when the checkout path
contains a space (macOS `~/Documents/Personal projects/…` did exactly this,
with a misleading `ModuleNotFoundError`). Recent macOS ships no `pip`
outside a venv, which is the other reason the venv line is there.

Before the first `probe` with a key, read "Which mode of each provider" in
`docs/METHODOLOGY.md` and decide whether the two Parallel arms are the ones
you want. The first dispatched probe locks the plan; changing arms after
that is a new plan, not an edit.

## How long to leave it

`tti forecast` answers this from the watchlist's real published cadence, not
from a guess. With the shipped list:

```
observed rate     13.1 events/day
concentration   top subject  6.6% · 44 effective subjects

to detect a hazard ratio of       events    days
  2.0                                 65       5
  1.5                                191      15
  1.2                                944      72
```

So: **five days before a large difference is defensible, about fifteen before
a moderate one is.** Publishing at day three would be publishing noise with a
leaderboard around it. `tti power` will keep saying "underpowered" until it
is not, and that is the number to wait on rather than a calendar.

The watchlist itself was selected against measured cadence — 150 candidates
probed, 32 dropped for shipping nothing in sixty days, two dropped for
contributing more than 6% of the corpus each. Re-run `tti forecast` on your
own machine; the GitHub and EDGAR rates could not be measured where this list
was built, so the 13.1 figure is a floor.

## What to do first, in order

1. **`tti doctor`.** Four sources were unreachable where this was built. Find
   out which are unreachable for you before drawing conclusions from a
   partial run.
2. **`tti forecast`.** With releases and filings reachable the rate should
   climb well above 13/day, which shortens everything above.
3. **Run for a week.** Check `tti power` rather than the leaderboard.
4. **Fill in `docs/INTEGRATION-NOTES.md`.** Every adapter was checked
   against its provider's published API document on 2026-09-02, but no
   provider API has ever been called from this code: the "Open" items are
   the behaviours a spec cannot tell you. Filling them in honestly is worth
   more than any number in the results table — it is the part a vendor
   cannot get anywhere else.
5. **Then publish**, and only then.
