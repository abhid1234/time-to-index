# Results

_Generated 2026-10-20 07:28 UTC · 59 events · 117 provider probes graded · 35 control probes · $0.53 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | 10m–3.0d | 0% (0–79) | 16% (6–38) | 310 chars | $5.17 | no answers | 29 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 67% (21–94) | 11% (3–33) | 1.0k chars | $1.04 | $14.50 | 28 |
| `exa/auto` | >10m | >10m | 100% (44–100) | 29% (13–53) | 1.5k chars | $7.00 | $67.67 | 29 |
| `parallel/advanced` | >3.0d | >3.0d | 90% (60–98) | 32% (15–54) | 935 chars | $5.18 | $16.11 | 28 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 17 | 0 | 0.0% (0–18) | 18% |
| `exa/auto` | 16 | 0 | 0.0% (0–19) | 19% |
| `parallel/advanced` | 16 | 0 | 0.0% (0–19) | 19% |
| `parallel/fast` | 16 | 0 | 0.0% (0–19) | 19% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
