# Results

_Generated 2026-10-07 13:44 UTC · 48 events · 82 provider probes graded · 27 control probes · $0.37 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `parallel/advanced` | 7m–7m | >10m | 100% (70–100) | 30% (11–60) | 876 chars | $5.00 | $11.11 | 20 |
| `brave/web` | >10m | >10m | — | 9% (2–38) | 347 chars | $5.00 | no answers | 21 |
| `exa/auto` | >10m | >10m | 100% (21–100) | 18% (5–48) | 1.5k chars | $7.00 | $147.00 | 21 |
| `parallel/fast` | >10m | >10m | 100% (34–100) | 0% (0–28) | 1.1k chars | $1.00 | $10.00 | 20 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 9 | 0 | 0.0% (0–30) | 30% |
| `exa/auto` | 9 | 0 | 0.0% (0–30) | 30% |
| `parallel/advanced` | 8 | 0 | 0.0% (0–32) | 32% |
| `parallel/fast` | 8 | 0 | 0.0% (0–32) | 32% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
