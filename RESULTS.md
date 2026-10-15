# Results

_Generated 2026-10-15 06:25 UTC · 56 events · 106 provider probes graded · 33 control probes · $0.48 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | >10m | >10m | — | 18% (6–41) | 342 chars | $5.00 | no answers | 27 |
| `exa/auto` | >10m | >10m | 100% (34–100) | 25% (10–49) | 1.5k chars | $7.00 | $94.50 | 27 |
| `parallel/advanced` | >10m | >10m | 100% (70–100) | 31% (14–56) | 914 chars | $5.00 | $14.44 | 26 |
| `parallel/fast` | >10m | >10m | 100% (34–100) | 12% (3–36) | 1.0k chars | $1.00 | $13.00 | 26 |

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
