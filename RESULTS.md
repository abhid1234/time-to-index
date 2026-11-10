# Results

_Generated 2026-11-10 15:44 UTC · 82 events · 153 provider probes graded · 44 control probes · $0.69 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | >3.0d | 0% (0–66) | 21% (10–40) | 342 chars | $5.13 | no answers | 38 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 50% (15–85) | 15% (6–34) | 1.2k chars | $1.03 | $19.00 | 37 |
| `parallel/advanced` | 3.0d–3.0d | 3.0d–3.0d | 82% (52–95) | 33% (19–52) | 980 chars | $5.14 | $21.11 | 37 |
| `exa/auto` | 10m–3.0d | 10m–3.0d | 83% (44–97) | 43% (26–63) | 1.5k chars | $7.00 | $53.20 | 38 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 24 | 0 | 0.0% (0–14) | 14% |
| `exa/auto` | 23 | 0 | 0.0% (0–14) | 14% |
| `parallel/advanced` | 23 | 0 | 0.0% (0–14) | 14% |
| `parallel/fast` | 23 | 0 | 0.0% (0–14) | 14% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
