# Results

_Generated 2026-09-15 17:10 UTC · 13 events · 22 provider probes graded · 12 control probes · $0.10 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | >10m | >10m | — | 17% (3–56) | 279 chars | $5.00 | no answers | 6 |
| `exa/auto` | >10m | >10m | — | 17% (3–56) | 1.5k chars | $7.00 | no answers | 6 |
| `parallel/advanced` | >10m | >10m | — | 40% (12–77) | 772 chars | $5.00 | no answers | 5 |
| `parallel/fast` | >10m | >10m | — | 0% (0–43) | 790 chars | $1.00 | no answers | 5 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 6 | 0 | 0.0% (0–39) | 39% |
| `exa/auto` | 6 | 0 | 0.0% (0–39) | 39% |
| `parallel/advanced` | 5 | 0 | 0.0% (0–43) | 43% |
| `parallel/fast` | 5 | 0 | 0.0% (0–43) | 43% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
