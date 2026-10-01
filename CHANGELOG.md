# Changelog

Time to Index follows Semantic Versioning. Measured results are not versioned
here: they live in `ledger/` and `RESULTS.md`, and corrections to them are
commits with a note, never silent re-runs.

## Unreleased

### Added

- Releases attach a CycloneDX SBOM (`sbom.cdx.json`) of the installed wheel.

## 0.1.0 - 2026-09-30

First public release.

### Added

- Collectors for six sources that stamp their own publication time: npm,
  PyPI, GitHub releases, SEC EDGAR, arXiv and the Federal Register. The
  publisher's timestamp is t=0; an event noticed more than ten minutes late
  is dropped rather than back-dated.
- Provider adapters for Parallel (`advanced`, `fast`), Exa (`auto`) and Brave
  (`web`), with Serper and Tavily declared in the plan and enabled by key.
- A probe ladder at t+5m, 15m, 1h, 6h, 24h and 72h, with a late probe
  dropped rather than fudged, a daily spend cap, and every raw payload kept.
- A grader that returns FRESH, STALE or ABSENT against the new token and the
  one it replaced, and ERROR (never ABSENT) when a call fails.
- An origin control arm that fetches the source URL at every rung, so a slow
  publisher is not blamed on a slow index.
- Turnbull's nonparametric MLE for interval-censored indexing times, checked
  against Kaplan–Meier on the Freireich 1963 data.
- Pre-registration: a hashed analysis plan, `tti prereg`, a lock file, and
  Holm–Bonferroni across the pairwise comparisons, with `tti power` for the
  sample each comparison needs.
- `tti report`, which writes `RESULTS.md` and the dashboard, states a partial
  ordering when only some pairs separate, and refuses to publish from a
  ledger older than the committed one.
- `tti verify`, an offline self-check of config, estimator, grader, ledger
  and platform; `tti decoy` for the pipeline's own false-positive rate;
  `tti regrade` to re-grade stored payloads without new calls; `tti demo`
  for a synthetic run with no keys.
- The interactive playground and the live dashboard on GitHub Pages, both
  read from the committed ledger.
- Scheduled GitHub Actions for discovery and probing, and a test suite of
  over 600 tests on Python 3.10 through 3.13 with no network calls.
