"""Configuration loading.

All tunables live in YAML under `data/` so that a fork can change the
watchlist, the probe ladder, or the cost table without touching code.
Secrets come from the environment only.
"""

from __future__ import annotations

import os
import pathlib
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RUNS = pathlib.Path(os.environ.get("TTI_RUN_DIR", ROOT / "runs"))

# Ladder of target lags, in seconds after publication. A probe fires once per
# rung per provider until that provider answers FRESH, after which the
# remaining rungs are skipped (see METHODOLOGY.md, "Carry-forward").
DEFAULT_LADDER = [300, 900, 3600, 21_600, 86_400, 259_200]

# An event whose detection lag exceeds this is discarded, not probed. We cannot
# attribute our own collection delay to a provider.
MAX_DETECTION_LAG = 600.0

# How far a publisher's clock may run ahead of ours before its timestamp is
# treated as an error rather than as skew. A few seconds is ordinary and
# harmless. Hours mean the ladder would be anchored to a t0 that never
# happened, and every lag it produced would describe nothing -- while looking
# exactly like a normal event.
MAX_CLOCK_SKEW = 120.0

# A probe fired more than this far past its due time is dropped rather than
# recorded at the wrong rung.
MAX_RUNG_SLIP = 600.0

_cache: dict[str, Any] = {}


class ConfigError(RuntimeError):
    """A configuration file is missing, malformed, or self-contradictory.

    Raised rather than defaulted, because the alternative was observed here
    and is worse: a `settings.yaml` containing a YAML typo parsed to
    something unusable, every lookup quietly fell back to a hard-coded
    default, and the daily spend cap silently became $5 while the file
    plainly said $6. A benchmark that spends a different amount of money than
    its own configuration states, and says nothing, has no business
    publishing numbers about anybody else's reliability.
    """


def _fail(name: str, msg: str) -> None:
    raise ConfigError(f"data/{name}.yaml: {msg}")


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_settings(name: str, d: Any) -> None:
    if not isinstance(d, dict):
        _fail(name, f"expected a mapping at the top level, got {type(d).__name__}")

    ladder = d.get("ladder", DEFAULT_LADDER)
    if not isinstance(ladder, list) or not ladder:
        _fail(name, "`ladder` must be a non-empty list of seconds")
    if not all(isinstance(r, int) and not isinstance(r, bool) and r > 0
               for r in ladder):
        _fail(name, "`ladder` entries must be positive whole seconds")
    if list(ladder) != sorted(ladder) or len(set(ladder)) != len(ladder):
        _fail(name, "`ladder` must be strictly increasing; a repeated or "
                    "out-of-order rung would record two observations at one lag")

    cap = d.get("daily_usd_cap", 5.0)
    if not _num(cap) or cap <= 0:
        _fail(name, f"`daily_usd_cap` must be a positive number of dollars, "
                    f"got {cap!r}")

    for key, lo, hi in (("max_clock_skew_seconds", 0, 86_400),
                        ("max_results", 1, 100),
                        ("max_chars_per_result", 100, 100_000),
                        ("max_detection_lag_seconds", 1, 86_400),
                        ("max_rung_slip_seconds", 1, 86_400)):
        if key in d and (not _num(d[key]) or not lo <= d[key] <= hi):
            _fail(name, f"`{key}` must be a number between {lo} and {hi}, "
                        f"got {d[key]!r}")

    # The real invariant is not "detection lag must be under the first rung".
    # An event found late still fires its first rung, and `run_due` records
    # the true elapsed lag rather than the rung's nominal one, which the
    # interval-censored estimator handles correctly. What actually breaks is
    # detection so late that the first rung is already outside the slip
    # window, because then that rung is dropped for every event and the
    # shortest measurable latency silently becomes the second rung.
    lag = d.get("max_detection_lag_seconds", MAX_DETECTION_LAG)
    slip = d.get("max_rung_slip_seconds", MAX_RUNG_SLIP)
    if ladder and lag - ladder[0] > slip:
        _fail(name, f"`max_detection_lag_seconds` ({lag:g}) is more than "
                    f"`max_rung_slip_seconds` ({slip:g}) past the first rung "
                    f"({ladder[0]}s). An event detected at that limit would arrive "
                    f"too late to fire its first rung at all, so the shortest "
                    f"measurable latency would silently become the second rung.")

    arms = d.get("arms", [])
    if not isinstance(arms, list):
        _fail(name, "`arms` must be a list of {provider, mode} mappings")
    for a in arms:
        if not isinstance(a, dict) or "provider" not in a or "mode" not in a:
            _fail(name, f"each arm needs `provider` and `mode`; got {a!r}")

    srcs = d.get("sources", [])
    if not isinstance(srcs, list) or not all(isinstance(x, str) for x in srcs):
        _fail(name, "`sources` must be a list of collector names")

    ph = d.get("phrasing_probe")
    if ph is not None:
        if not isinstance(ph, dict):
            _fail(name, "`phrasing_probe` must be a mapping")
        bad = [r for r in (ph.get("rungs") or []) if r not in ladder]
        if bad:
            _fail(name, f"`phrasing_probe.rungs` {bad} are not rungs in `ladder`; "
                        f"those probes would never be scheduled and the axis would "
                        f"silently collect nothing")


def _validate_providers(name: str, d: Any) -> None:
    if not isinstance(d, dict) or not isinstance(d.get("providers"), dict):
        _fail(name, "expected a top-level `providers` mapping")
    for pname, cfg in d["providers"].items():
        if not isinstance(cfg, dict):
            _fail(name, f"`{pname}` must be a mapping")
        modes = cfg.get("modes")
        if not isinstance(modes, dict) or not modes:
            _fail(name, f"`{pname}` needs at least one entry under `modes`")
        for mname, m in modes.items():
            price = (m or {}).get("usd_per_1k_requests")
            if not _num(price) or price < 0:
                _fail(name, f"`{pname}.modes.{mname}.usd_per_1k_requests` must be a "
                            f"non-negative number — an unpriced arm spends against "
                            f"a cap that cannot see it")


def _validate_watchlist(name: str, d: Any) -> None:
    if not isinstance(d, dict):
        _fail(name, f"expected a mapping of source -> subjects, got "
                    f"{type(d).__name__}")
    for source, items in d.items():
        if items is None:
            continue
        if not isinstance(items, list):
            _fail(name, f"`{source}` must be a list")
        if source == "edgar":
            for row in items:
                if not isinstance(row, dict) or "cik" not in row or "name" not in row:
                    _fail(name, f"each edgar entry needs `cik` and `name`; got {row!r}")
        elif not all(isinstance(x, str) for x in items):
            _fail(name, f"`{source}` entries must be strings")


def _validate_corpus(name: str, d: Any) -> None:
    if not isinstance(d, dict):
        _fail(name, "expected a mapping of category -> list of URLs")
    for cat, urls in d.items():
        for u in urls or []:
            if not isinstance(u, str) or not u.startswith(("http://", "https://")):
                _fail(name, f"`{cat}` entry {u!r} is not an absolute http(s) URL")


_VALIDATORS = {
    "settings": _validate_settings,
    "providers": _validate_providers,
    "watchlist": _validate_watchlist,
    "corpus": _validate_corpus,
}


def load(name: str) -> Any:
    """Read and validate a config file.

    Validation runs here, on file load, and not on every lookup: the tests
    inject partial settings straight into `_cache`, and a benchmark that
    could not be driven from a stub would be much harder to test than it is
    to misconfigure.
    """
    if name not in _cache:
        path = DATA / f"{name}.yaml"
        if not path.exists():
            raise ConfigError(f"data/{name}.yaml is missing. It ships with the "
                              f"repository — restore it rather than running "
                              f"without it.")
        try:
            with open(path, encoding="utf-8") as fh:
                doc = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ConfigError(f"data/{name}.yaml is not valid YAML: "
                              f"{str(exc).splitlines()[0]}") from exc
        if doc is None:
            raise ConfigError(f"data/{name}.yaml is empty. An empty file is not the "
                              f"same as the defaults, and treating it as such runs "
                              f"with settings nobody chose.")
        validator = _VALIDATORS.get(name)
        if validator:
            validator(name, doc)
        _cache[name] = doc
    return _cache[name]


def check_all() -> list[str]:
    """Validate every config file. Returns the problems found; empty if clean."""
    problems = []
    for name in _VALIDATORS:
        _cache.pop(name, None)
        try:
            load(name)
        except ConfigError as exc:
            problems.append(str(exc))
    return problems


def settings() -> dict[str, Any]:
    return load("settings")


def ladder() -> list[int]:
    return list(settings().get("ladder", DEFAULT_LADDER))


def watchlist() -> dict[str, Any]:
    return load("watchlist")


def providers_config() -> dict[str, Any]:
    return load("providers")


def api_key(env_var: str) -> str | None:
    v = os.environ.get(env_var, "").strip()
    return v or None


def contact_ua() -> str:
    """SEC and arXiv both require a real contact string in User-Agent."""
    return os.environ.get(
        "TTI_USER_AGENT",
        "time-to-index/0.1 (open benchmark; set TTI_USER_AGENT to your contact)",
    )
