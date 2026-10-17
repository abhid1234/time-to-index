# Results

_Generated 2026-10-17 08:49 UTC · 57 events · 113 provider probes graded · 34 control probes · $0.51 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | 10m–3.0d | 0% (0–79) | 17% (6–39) | 336 chars | $5.18 | no answers | 28 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 67% (21–94) | 12% (3–34) | 1.0k chars | $1.04 | $14.00 | 27 |
| `exa/auto` | >10m | >10m | 100% (44–100) | 25% (10–49) | 1.5k chars | $7.00 | $65.33 | 28 |
| `parallel/advanced` | >3.0d | >3.0d | 90% (60–98) | 33% (16–56) | 935 chars | $5.19 | $15.56 | 27 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 16 | 0 | 0.0% (0–19) | 19% |
| `exa/auto` | 15 | 0 | 0.0% (0–20) | 20% |
| `parallel/advanced` | 15 | 0 | 0.0% (0–20) | 20% |
| `parallel/fast` | 15 | 0 | 0.0% (0–20) | 20% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
