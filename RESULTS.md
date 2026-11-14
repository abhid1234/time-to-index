# Results

_Generated 2026-11-14 01:45 UTC · 89 events · 173 provider probes graded · 49 control probes · $0.78 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `parallel/advanced` | 3.0d–3.0d | >3.0d | 75% (47–91) | 41% (26–58) | 977 chars | $5.12 | $23.89 | 42 |
| `parallel/fast` | 10m–3.0d | >3.0d | 40% (12–77) | 23% (11–40) | 1.2k chars | $1.02 | $21.50 | 42 |
| `exa/auto` | 10m–3.0d | 10m–3.0d | 71% (36–92) | 52% (34–69) | 1.5k chars | $7.00 | $60.20 | 43 |
| `brave/web` | >3.0d | >3.0d | 0% (0–56) | 24% (13–41) | 335 chars | $5.12 | no answers | 43 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 28 | 0 | 0.0% (0–12) | 12% |
| `exa/auto` | 27 | 0 | 0.0% (0–12) | 12% |
| `parallel/advanced` | 27 | 0 | 0.0% (0–12) | 12% |
| `parallel/fast` | 27 | 0 | 0.0% (0–12) | 12% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
