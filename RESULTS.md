# Results

_Generated 2026-09-19 16:06 UTC · 17 events · 26 provider probes graded · 13 control probes · $0.12 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | >10m | >10m | — | 14% (3–51) | 264 chars | $5.00 | no answers | 7 |
| `exa/auto` | >10m | >10m | — | 29% (8–64) | 1.5k chars | $7.00 | no answers | 7 |
| `parallel/advanced` | >10m | >10m | — | 33% (10–70) | 985 chars | $5.00 | no answers | 6 |
| `parallel/fast` | >10m | >10m | — | 0% (0–39) | 790 chars | $1.00 | no answers | 6 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 7 | 0 | 0.0% (0–35) | 35% |
| `exa/auto` | 7 | 0 | 0.0% (0–35) | 35% |
| `parallel/advanced` | 6 | 0 | 0.0% (0–39) | 39% |
| `parallel/fast` | 6 | 0 | 0.0% (0–39) | 39% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
