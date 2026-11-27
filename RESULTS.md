# Results

_Generated 2026-11-27 17:26 UTC · 94 events · 193 provider probes graded · 53 control probes · $0.87 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `parallel/fast` | 10m–3.0d | 3.0d–3.0d | 33% (10–70) | 29% (16–45) | 1.3k chars | $1.04 | $24.00 | 46 |
| `exa/auto` | 10m–3.0d | 10m–3.0d | 62% (31–86) | 55% (38–71) | 1.5k chars | $7.15 | $67.20 | 47 |
| `brave/web` | 3.0d–3.0d | 3.0d–3.0d | 20% (4–62) | 25% (14–41) | 332 chars | $5.21 | $245.00 | 47 |
| `parallel/advanced` | 3.0d–3.0d | 3.0d–3.0d | 69% (42–87) | 44% (30–60) | 985 chars | $5.22 | $26.67 | 46 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 32 | 0 | 0.0% (0–11) | 11% |
| `exa/auto` | 31 | 0 | 0.0% (0–11) | 11% |
| `parallel/advanced` | 31 | 0 | 0.0% (0–11) | 11% |
| `parallel/fast` | 31 | 0 | 0.0% (0–11) | 11% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
