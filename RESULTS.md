# Results

_Generated 2026-10-13 22:00 UTC · 55 events · 102 provider probes graded · 32 control probes · $0.46 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | >10m | >10m | — | 19% (7–43) | 336 chars | $5.00 | no answers | 26 |
| `exa/auto` | >10m | >10m | 100% (34–100) | 27% (11–52) | 1.5k chars | $7.00 | $91.00 | 26 |
| `parallel/advanced` | >10m | >10m | 100% (70–100) | 33% (15–58) | 876 chars | $5.00 | $13.89 | 25 |
| `parallel/fast` | >10m | >10m | 100% (34–100) | 13% (4–38) | 1.0k chars | $1.00 | $12.50 | 25 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 14 | 0 | 0.0% (0–22) | 22% |
| `exa/auto` | 14 | 0 | 0.0% (0–22) | 22% |
| `parallel/advanced` | 13 | 0 | 0.0% (0–23) | 23% |
| `parallel/fast` | 13 | 0 | 0.0% (0–23) | 23% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
