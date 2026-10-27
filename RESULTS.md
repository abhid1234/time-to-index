# Results

_Generated 2026-10-27 00:54 UTC · 65 events · 133 provider probes graded · 39 control probes · $0.60 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `brave/web` | 10m–3.0d | 10m–3.0d | 0% (0–79) | 17% (7–37) | 336 chars | $5.15 | no answers | 33 |
| `parallel/fast` | 10m–3.0d | 10m–3.0d | 67% (21–94) | 18% (7–39) | 1.1k chars | $1.03 | $16.50 | 32 |
| `exa/auto` | >10m | >10m | 100% (51–100) | 40% (22–61) | 1.5k chars | $7.00 | $57.75 | 33 |
| `parallel/advanced` | >3.0d | >3.0d | 90% (60–98) | 35% (19–55) | 977 chars | $5.16 | $18.33 | 32 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 21 | 0 | 0.0% (0–15) | 15% |
| `exa/auto` | 20 | 0 | 0.0% (0–16) | 16% |
| `parallel/advanced` | 20 | 0 | 0.0% (0–16) | 16% |
| `parallel/fast` | 20 | 0 | 0.0% (0–16) | 16% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
