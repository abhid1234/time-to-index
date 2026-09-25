# Results

_Generated 2026-09-25 17:18 UTC · 33 events · 70 provider probes graded · 24 control probes · $0.32 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `parallel/advanced` | 7m–7m | >10m | 100% (70–100) | 29% (8–64) | 876 chars | $5.00 | $9.44 | 17 |
| `brave/web` | >10m | >10m | — | 12% (2–47) | 347 chars | $5.00 | no answers | 18 |
| `exa/auto` | >10m | >10m | 100% (21–100) | 25% (7–59) | 1.5k chars | $7.00 | $126.00 | 18 |
| `parallel/fast` | >10m | >10m | 100% (34–100) | 0% (0–35) | 1.2k chars | $1.00 | $8.50 | 17 |

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
