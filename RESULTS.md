# Results

_Generated 2026-10-25 17:27 UTC · 63 events · 125 provider probes graded · 37 control probes · $0.56 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | 10m–3.0d | 0% (0–79) | 19% (8–40) | 336 chars | $5.16 | no answers | 31 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 67% (21–94) | 10% (3–30) | 1.1k chars | $1.03 | $15.50 | 30 |
| `exa/auto` | >10m | >10m | 100% (51–100) | 33% (16–56) | 1.5k chars | $7.00 | $54.25 | 31 |
| `parallel/advanced` | >3.0d | >3.0d | 90% (60–98) | 29% (14–50) | 966 chars | $5.17 | $17.22 | 30 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 19 | 0 | 0.0% (0–17) | 17% |
| `exa/auto` | 18 | 0 | 0.0% (0–18) | 18% |
| `parallel/advanced` | 18 | 0 | 0.0% (0–18) | 18% |
| `parallel/fast` | 18 | 0 | 0.0% (0–18) | 18% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
