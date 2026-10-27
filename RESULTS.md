# Results

_Generated 2026-10-27 17:56 UTC · 76 events · 137 provider probes graded · 40 control probes · $0.62 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | 10m–3.0d | 0% (0–79) | 21% (9–40) | 336 chars | $5.15 | no answers | 34 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 67% (21–94) | 17% (7–37) | 1.1k chars | $1.03 | $17.00 | 33 |
| `exa/auto` | >10m | >10m | 100% (51–100) | 43% (24–63) | 1.5k chars | $7.00 | $59.50 | 34 |
| `parallel/advanced` | >3.0d | >3.0d | 90% (60–98) | 38% (21–57) | 979 chars | $5.15 | $18.89 | 33 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 22 | 0 | 0.0% (0–15) | 15% |
| `exa/auto` | 21 | 0 | 0.0% (0–15) | 15% |
| `parallel/advanced` | 21 | 0 | 0.0% (0–15) | 15% |
| `parallel/fast` | 21 | 0 | 0.0% (0–15) | 15% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
