# Results

_Generated 2026-10-16 15:19 UTC · 57 events · 110 provider probes graded · 34 control probes · $0.50 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | >10m | >10m | — | 17% (6–39) | 336 chars | $5.00 | no answers | 28 |
| `exa/auto` | >10m | >10m | 100% (44–100) | 25% (10–49) | 1.5k chars | $7.00 | $65.33 | 28 |
| `parallel/advanced` | >10m | >10m | 100% (70–100) | 29% (13–53) | 914 chars | $5.00 | $15.00 | 27 |
| `parallel/fast` | >10m | >10m | 100% (34–100) | 12% (3–34) | 1.0k chars | $1.00 | $13.50 | 27 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 15 | 0 | 0.0% (0–20) | 20% |
| `exa/auto` | 15 | 0 | 0.0% (0–20) | 20% |
| `parallel/advanced` | 14 | 0 | 0.0% (0–22) | 22% |
| `parallel/fast` | 14 | 0 | 0.0% (0–22) | 22% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
