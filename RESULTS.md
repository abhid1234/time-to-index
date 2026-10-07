# Results

_Generated 2026-10-07 19:35 UTC · 50 events · 86 provider probes graded · 28 control probes · $0.39 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `parallel/advanced` | 7m–7m | >10m | 100% (70–100) | 27% (10–57) | 876 chars | $5.00 | $11.67 | 21 |
| `brave/web` | >10m | >10m | — | 8% (1–35) | 342 chars | $5.00 | no answers | 22 |
| `exa/auto` | >10m | >10m | 100% (21–100) | 17% (5–45) | 1.5k chars | $7.00 | $154.00 | 22 |
| `parallel/fast` | >10m | >10m | 100% (34–100) | 0% (0–26) | 1.1k chars | $1.00 | $10.50 | 21 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 10 | 0 | 0.0% (0–28) | 28% |
| `exa/auto` | 10 | 0 | 0.0% (0–28) | 28% |
| `parallel/advanced` | 9 | 0 | 0.0% (0–30) | 30% |
| `parallel/fast` | 9 | 0 | 0.0% (0–30) | 30% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
