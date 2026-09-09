# Results

_Generated 2026-09-09 16:03 UTC · 9 events · 8 provider probes graded · 8 control probes · $0.04 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | >9m | >9m | — | 0% (0–66) | 279 chars | $5.00 | no answers | 2 |
| `exa/auto` | >9m | >9m | — | 0% (0–66) | 1.5k chars | $7.00 | no answers | 2 |
| `parallel/advanced` | >9m | >9m | — | 50% (9–91) | 772 chars | $5.00 | no answers | 2 |
| `parallel/fast` | >9m | >9m | — | 0% (0–66) | 790 chars | $1.00 | no answers | 2 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 2 | 0 | 0.0% (0–66) | 66% |
| `exa/auto` | 2 | 0 | 0.0% (0–66) | 66% |
| `parallel/advanced` | 2 | 0 | 0.0% (0–66) | 66% |
| `parallel/fast` | 2 | 0 | 0.0% (0–66) | 66% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
