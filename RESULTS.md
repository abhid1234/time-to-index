# Results

_Generated 2026-11-13 00:33 UTC · 85 events · 161 provider probes graded · 46 control probes · $0.73 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | >3.0d | 0% (0–66) | 23% (12–41) | 342 chars | $5.13 | no answers | 40 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 50% (15–85) | 18% (8–36) | 1.2k chars | $1.03 | $20.00 | 39 |
| `parallel/advanced` | 3.0d–3.0d | 3.0d–3.0d | 82% (52–95) | 34% (20–53) | 979 chars | $5.13 | $22.22 | 39 |
| `exa/auto` | 10m–3.0d | 10m–3.0d | 83% (44–97) | 48% (30–67) | 1.5k chars | $7.00 | $56.00 | 40 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 26 | 0 | 0.0% (0–13) | 13% |
| `exa/auto` | 25 | 0 | 0.0% (0–13) | 13% |
| `parallel/advanced` | 25 | 0 | 0.0% (0–13) | 13% |
| `parallel/fast` | 25 | 0 | 0.0% (0–13) | 13% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
