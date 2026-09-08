# Results

_Generated 2026-09-08 18:48 UTC · 7 events · 4 provider probes graded · 7 control probes · $0.02 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | >6m | >6m | — | 0% (0–79) | 279 chars | $5.00 | no answers | 1 |
| `exa/auto` | >6m | >6m | — | 0% (0–79) | 1.4k chars | $7.00 | no answers | 1 |
| `parallel/advanced` | >6m | >6m | — | 0% (0–79) | 772 chars | $5.00 | no answers | 1 |
| `parallel/fast` | >6m | >6m | — | 0% (0–79) | 790 chars | $1.00 | no answers | 1 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 1 | 0 | 0.0% (0–79) | 79% |
| `exa/auto` | 1 | 0 | 0.0% (0–79) | 79% |
| `parallel/advanced` | 1 | 0 | 0.0% (0–79) | 79% |
| `parallel/fast` | 1 | 0 | 0.0% (0–79) | 79% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
