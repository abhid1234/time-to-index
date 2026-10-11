# Results

_Generated 2026-10-11 21:06 UTC · 52 events · 90 provider probes graded · 29 control probes · $0.41 spent_

| provider | median TTI | p90 | 24h recall | staleness | text/result | $/1k events | $/1k fresh answers | n |
|---|---|---|---|---|---|---|---|---|
| `parallel/advanced` | 7m–7m | >10m | 100% (70–100) | 33% (14–61) | 914 chars | $5.00 | $12.22 | 22 |
| `brave/web` | >10m | >10m | — | 8% (1–33) | 342 chars | $5.00 | no answers | 23 |
| `exa/auto` | >10m | >10m | 100% (21–100) | 23% (8–50) | 1.5k chars | $7.00 | $161.00 | 23 |
| `parallel/fast` | >10m | >10m | 100% (34–100) | 8% (1–35) | 1.1k chars | $1.00 | $11.00 | 22 |

## Pipeline false-positive rate

| arm | payloads re-graded | false positives | rate (95% CI) | upper bound |
|---|---|---|---|---|
| `brave/web` | 11 | 0 | 0.0% (0–26) | 26% |
| `exa/auto` | 11 | 0 | 0.0% (0–26) | 26% |
| `parallel/advanced` | 10 | 0 | 0.0% (0–28) | 28% |
| `parallel/fast` | 10 | 0 | 0.0% (0–28) | 28% |

_Counterfactuals not registry-verified in this render; `tti decoy` verifies them. Zero observed is not a zero rate; quote the upper bound._
## Pre-registration

```
  plan bac218770f209b20 · v1 · registered 2026-08-31
  · Declared in the plan, not enabled in this run (no key): serper/search, tavily/basic
```
