# Results

_Generated 2026-09-29 18:36 UTC · 34 events · 74 provider probes graded · 25 control probes · $0.34 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `parallel/advanced` | 7m–7m | >10m | 100% (70–100) | 25% (7–59) | 876 chars | $5.00 | $10.00 | 18 |
| `brave/web` | >10m | >10m | — | 11% (2–43) | 347 chars | $5.00 | no answers | 19 |
| `exa/auto` | >10m | >10m | 100% (21–100) | 22% (6–55) | 1.5k chars | $7.00 | $133.00 | 19 |
| `parallel/fast` | >10m | >10m | 100% (34–100) | 0% (0–32) | 1.2k chars | $1.00 | $9.00 | 18 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 8 | 0 | 0.0% (0–32) | 32% |
| `exa/auto` | 8 | 0 | 0.0% (0–32) | 32% |
| `parallel/advanced` | 7 | 0 | 0.0% (0–35) | 35% |
| `parallel/fast` | 7 | 0 | 0.0% (0–35) | 35% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
