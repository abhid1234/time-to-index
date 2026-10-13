# Results

_Generated 2026-10-13 17:49 UTC · 54 events · 98 provider probes graded · 31 control probes · $0.44 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | >10m | >10m | — | 13% (4–38) | 342 chars | $5.00 | no answers | 25 |
| `exa/auto` | >10m | >10m | 100% (21–100) | 27% (11–52) | 1.5k chars | $7.00 | $175.00 | 25 |
| `parallel/advanced` | >10m | >10m | 100% (70–100) | 29% (12–55) | 914 chars | $5.00 | $13.33 | 24 |
| `parallel/fast` | >10m | >10m | 100% (34–100) | 7% (1–31) | 1.1k chars | $1.00 | $12.00 | 24 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 13 | 0 | 0.0% (0–23) | 23% |
| `exa/auto` | 13 | 0 | 0.0% (0–23) | 23% |
| `parallel/advanced` | 12 | 0 | 0.0% (0–24) | 24% |
| `parallel/fast` | 12 | 0 | 0.0% (0–24) | 24% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
