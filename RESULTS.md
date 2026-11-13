# Results

_Generated 2026-11-13 15:30 UTC · 86 events · 165 provider probes graded · 47 control probes · $0.74 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | >3.0d | 0% (0–66) | 23% (11–40) | 336 chars | $5.12 | no answers | 41 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 50% (15–85) | 21% (10–38) | 1.2k chars | $1.03 | $20.50 | 40 |
| `parallel/advanced` | 3.0d–3.0d | 3.0d–3.0d | 82% (52–95) | 37% (22–54) | 977 chars | $5.13 | $22.78 | 40 |
| `exa/auto` | 10m–3.0d | 10m–3.0d | 83% (44–97) | 50% (32–68) | 1.5k chars | $7.00 | $57.40 | 41 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 27 | 0 | 0.0% (0–12) | 12% |
| `exa/auto` | 26 | 0 | 0.0% (0–13) | 13% |
| `parallel/advanced` | 26 | 0 | 0.0% (0–13) | 13% |
| `parallel/fast` | 26 | 0 | 0.0% (0–13) | 13% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
