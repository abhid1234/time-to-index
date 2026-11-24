# Results

_Generated 2026-11-24 01:16 UTC · 91 events · 185 provider probes graded · 51 control probes · $0.83 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `parallel/advanced` | 3.0d–3.0d | 3.0d–3.0d | 69% (42–87) | 41% (26–58) | 980 chars | $5.23 | $25.56 | 44 |
| `parallel/fast` | 10m–3.0d | 3.0d–3.0d | 33% (10–70) | 24% (13–41) | 1.2k chars | $1.05 | $23.00 | 44 |
| `exa/auto` | 10m–3.0d | 10m–3.0d | 62% (31–86) | 52% (34–69) | 1.5k chars | $7.16 | $64.40 | 45 |
| `brave/web` | 3.0d–3.0d | 3.0d–3.0d | 20% (4–62) | 24% (12–40) | 332 chars | $5.22 | $235.00 | 45 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 30 | 0 | 0.0% (0–11) | 11% |
| `exa/auto` | 29 | 0 | 0.0% (0–12) | 12% |
| `parallel/advanced` | 29 | 0 | 0.0% (0–12) | 12% |
| `parallel/fast` | 29 | 0 | 0.0% (0–12) | 12% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
