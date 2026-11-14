# Results

_Generated 2026-11-14 08:07 UTC · 89 events · 177 provider probes graded · 49 control probes · $0.80 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `parallel/advanced` | 3.0d–3.0d | 3.0d–3.0d | 69% (42–87) | 41% (26–58) | 979 chars | $5.24 | $24.44 | 42 |
| `parallel/fast` | 10m–3.0d | 3.0d–3.0d | 33% (10–70) | 23% (11–40) | 1.2k chars | $1.05 | $22.00 | 42 |
| `exa/auto` | 10m–3.0d | 10m–3.0d | 62% (31–86) | 52% (34–69) | 1.5k chars | $7.16 | $61.60 | 43 |
| `brave/web` | 3.0d–3.0d | 3.0d–3.0d | 0% (0–49) | 24% (13–41) | 335 chars | $5.23 | no answers | 43 |

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
