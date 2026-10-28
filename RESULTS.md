# Results

_Generated 2026-10-28 19:07 UTC · 78 events · 141 provider probes graded · 41 control probes · $0.64 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | 10m–3.0d | 0% (0–79) | 24% (11–43) | 310 chars | $5.14 | no answers | 35 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 67% (21–94) | 17% (7–36) | 1.1k chars | $1.03 | $17.50 | 34 |
| `exa/auto` | >10m | >10m | 100% (57–100) | 43% (24–63) | 1.5k chars | $7.00 | $49.00 | 35 |
| `parallel/advanced` | >3.0d | >3.0d | 90% (60–98) | 36% (20–55) | 979 chars | $5.15 | $19.44 | 34 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 23 | 0 | 0.0% (0–14) | 14% |
| `exa/auto` | 22 | 0 | 0.0% (0–15) | 15% |
| `parallel/advanced` | 22 | 0 | 0.0% (0–15) | 15% |
| `parallel/fast` | 22 | 0 | 0.0% (0–15) | 15% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
