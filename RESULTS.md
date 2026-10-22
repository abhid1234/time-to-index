# Results

_Generated 2026-10-22 05:01 UTC · 62 events · 121 provider probes graded · 36 control probes · $0.55 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | 10m–3.0d | 0% (0–79) | 20% (8–42) | 336 chars | $5.17 | no answers | 30 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 67% (21–94) | 11% (3–31) | 1.1k chars | $1.03 | $15.00 | 29 |
| `exa/auto` | >10m | >10m | 100% (44–100) | 33% (16–56) | 1.5k chars | $7.00 | $70.00 | 30 |
| `parallel/advanced` | >3.0d | >3.0d | 90% (60–98) | 30% (15–52) | 966 chars | $5.17 | $16.67 | 29 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 18 | 0 | 0.0% (0–18) | 18% |
| `exa/auto` | 17 | 0 | 0.0% (0–18) | 18% |
| `parallel/advanced` | 17 | 0 | 0.0% (0–18) | 18% |
| `parallel/fast` | 17 | 0 | 0.0% (0–18) | 18% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
