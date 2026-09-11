# Results

_Generated 2026-09-11 11:15 UTC · 10 events · 12 provider probes graded · 9 control probes · $0.05 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | >9m | >9m | — | 33% (6–79) | 279 chars | $5.00 | no answers | 3 |
| `exa/auto` | >9m | >9m | — | 0% (0–56) | 1.4k chars | $7.00 | no answers | 3 |
| `parallel/advanced` | >9m | >9m | — | 33% (6–79) | 757 chars | $5.00 | no answers | 3 |
| `parallel/fast` | >9m | >9m | — | 0% (0–56) | 790 chars | $1.00 | no answers | 3 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 3 | 0 | 0.0% (0–56) | 56% |
| `exa/auto` | 3 | 0 | 0.0% (0–56) | 56% |
| `parallel/advanced` | 3 | 0 | 0.0% (0–56) | 56% |
| `parallel/fast` | 3 | 0 | 0.0% (0–56) | 56% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
