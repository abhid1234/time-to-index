# Results

_Generated 2026-11-23 13:46 UTC · 90 events · 181 provider probes graded · 50 control probes · $0.82 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `parallel/advanced` | 3.0d–3.0d | 3.0d–3.0d | 69% (42–87) | 42% (27–59) | 979 chars | $5.23 | $25.00 | 43 |
| `parallel/fast` | 10m–3.0d | 3.0d–3.0d | 33% (10–70) | 25% (13–42) | 1.2k chars | $1.05 | $22.50 | 43 |
| `exa/auto` | 10m–3.0d | 10m–3.0d | 62% (31–86) | 50% (33–67) | 1.5k chars | $7.16 | $63.00 | 44 |
| `brave/web` | 3.0d–3.0d | 3.0d–3.0d | 20% (4–62) | 24% (13–41) | 332 chars | $5.23 | $230.00 | 44 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 29 | 0 | 0.0% (0–12) | 12% |
| `exa/auto` | 28 | 0 | 0.0% (0–12) | 12% |
| `parallel/advanced` | 28 | 0 | 0.0% (0–12) | 12% |
| `parallel/fast` | 28 | 0 | 0.0% (0–12) | 12% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
