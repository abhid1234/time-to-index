# Results

_Generated 2026-11-11 16:06 UTC · 84 events · 157 provider probes graded · 45 control probes · $0.71 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | >3.0d | 0% (0–66) | 24% (12–42) | 336 chars | $5.13 | no answers | 39 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 50% (15–85) | 15% (6–32) | 1.2k chars | $1.03 | $19.50 | 38 |
| `parallel/advanced` | 3.0d–3.0d | 3.0d–3.0d | 82% (52–95) | 32% (18–51) | 979 chars | $5.13 | $21.67 | 38 |
| `exa/auto` | 10m–3.0d | 10m–3.0d | 83% (44–97) | 46% (28–65) | 1.5k chars | $7.00 | $54.60 | 39 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 25 | 0 | 0.0% (0–13) | 13% |
| `exa/auto` | 24 | 0 | 0.0% (0–14) | 14% |
| `parallel/advanced` | 24 | 0 | 0.0% (0–14) | 14% |
| `parallel/fast` | 24 | 0 | 0.0% (0–14) | 14% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
