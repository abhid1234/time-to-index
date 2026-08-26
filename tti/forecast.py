"""How long do I have to run this before it can say anything?

`tti power` answers that question after the fact, from events already
collected. This answers it *before* the run, from how often the watchlist has
actually shipped -- which is knowable in advance, because every source here
publishes its own history.

The two numbers it joins:

    Observed cadence. Registries expose every past release with its
    timestamp, so the event rate of a watchlist is a measurement, not an
    estimate. Nothing is guessed and nothing is extrapolated from a sample.

    Schoenfeld's requirement. A hazard ratio of 2 needs 66 events, 1.5 needs
    191, and 1.2 needs 945.

Dividing one into the other gives days-to-signal, and it is usually a
larger number than anyone expects. That is the point. A benchmark that
publishes a ranking after four days of collection has published noise with
a leaderboard around it, and the cheapest moment to find that out is before
starting, when the watchlist can still be changed.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
from dataclasses import dataclass, field

from . import config, http
from .power import events_for_power

WINDOW_DAYS = 60


@dataclass
class SourceCadence:
    source: str
    subject: str
    releases: int = 0
    error: str = ""

    @property
    def per_day(self) -> float:
        return self.releases / WINDOW_DAYS


@dataclass
class Forecast:
    rows: list[SourceCadence] = field(default_factory=list)
    window_days: int = WINDOW_DAYS

    @property
    def readable(self) -> list[SourceCadence]:
        return [r for r in self.rows if not r.error]

    @property
    def per_day(self) -> float:
        return sum(r.per_day for r in self.readable)

    @property
    def superseding_per_day(self) -> float:
        """Events that can measure staleness.

        Only sources where an answer can be replaced count. Preprints and
        Federal Register documents add time-to-index volume but contribute
        nothing to the staleness denominator, so a watchlist padded with them
        looks busier than it is for the metric this project exists for.
        """
        return sum(r.per_day for r in self.readable
                   if r.source in ("npm", "pypi", "github_release", "edgar"))

    def days_for(self, hazard_ratio: float, superseding: bool = False) -> float | None:
        need = events_for_power(hazard_ratio)
        rate = self.superseding_per_day if superseding else self.per_day
        if need is None or rate <= 0:
            return None
        return need / rate

    def concentration(self) -> tuple[float, float]:
        """(top subject's share, effective number of subjects).

        Effective subjects is 1/Herfindahl. A corpus where one package ships
        16% of all events is substantially a measurement of that package,
        because provider behaviour can be subject-specific -- a provider that
        special-cases one popular registry entry would look good here for a
        reason that does not generalise. The headline event rate says nothing
        about this, which is why it is printed next to it.
        """
        rates = [r.per_day for r in self.readable if r.per_day > 0]
        total = sum(rates)
        if not rates or total <= 0:
            return float("nan"), float("nan")
        shares = [r / total for r in rates]
        hhi = sum(s * s for s in shares)
        return max(shares), (1.0 / hhi if hhi else float("nan"))

    def quiet(self) -> list[SourceCadence]:
        return [r for r in self.readable if r.releases == 0]


def _npm(pkg: str) -> SourceCadence:
    from .sources.npm import _is_prerelease, _iso
    row = SourceCadence("npm", pkg)
    cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - WINDOW_DAYS * 86400
    doc = http.get_json(f"https://registry.npmjs.org/{pkg}", timeout=25)
    row.releases = sum(
        1 for v, t in (doc.get("time") or {}).items()
        if v not in ("created", "modified") and not _is_prerelease(v) and _iso(t) >= cutoff)
    return row


def _pypi(pkg: str) -> SourceCadence:
    from .sources.pypi import _is_prerelease, _release_time
    row = SourceCadence("pypi", pkg)
    cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - WINDOW_DAYS * 86400
    doc = http.get_json(f"https://pypi.org/pypi/{pkg}/json", timeout=25)
    for v, files in (doc.get("releases") or {}).items():
        if _is_prerelease(v):
            continue
        t = _release_time(files)
        if t and t >= cutoff:
            row.releases += 1
    return row


def _github(repo: str) -> SourceCadence:
    from .sources.github_releases import _iso
    row = SourceCadence("github_release", repo)
    cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - WINDOW_DAYS * 86400
    headers = {"Accept": "application/vnd.github+json"}
    tok = config.api_key("GITHUB_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    rels = http.get_json(f"https://api.github.com/repos/{repo}/releases?per_page=100",
                         headers=headers, timeout=25)
    row.releases = sum(1 for r in rels
                       if not r.get("draft") and not r.get("prerelease")
                       and r.get("published_at") and _iso(r["published_at"]) >= cutoff)
    return row


def _edgar(row_cfg: dict) -> SourceCadence:
    from .sources.edgar import FORMS, _accept_ts
    cik, name = str(row_cfg["cik"]), row_cfg["name"]
    row = SourceCadence("edgar", name)
    cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - WINDOW_DAYS * 86400
    doc = http.get_json(f"https://data.sec.gov/submissions/CIK{cik:0>10}.json", timeout=30)
    recent = (doc.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accepted = recent.get("acceptanceDateTime") or []
    for i, f in enumerate(forms):
        if f in FORMS and i < len(accepted) and _accept_ts(accepted[i]) >= cutoff:
            row.releases += 1
    return row


# Sources whose cadence is not knowable from a watchlist: arXiv and the
# Federal Register publish on their own schedule regardless of what we watch,
# so they are reported separately rather than folded into a per-subject rate
# that would be meaningless.
UNBOUNDED = {
    "arxiv": "publishes on its own schedule; volume is set by how deep each poll reads",
    "federal_register": "publishes on its own schedule; one issue per business day",
}


def run(sources: list[str] | None = None, workers: int = 10) -> Forecast:
    wl = config.watchlist()
    enabled = sources or config.settings().get("sources", [])
    jobs: list[tuple] = []
    if "npm" in enabled:
        jobs += [(_npm, p) for p in wl.get("npm", [])]
    if "pypi" in enabled:
        jobs += [(_pypi, p) for p in wl.get("pypi", [])]
    if "github_release" in enabled:
        jobs += [(_github, r) for r in wl.get("github", [])]
    if "edgar" in enabled:
        jobs += [(_edgar, r) for r in wl.get("edgar", [])]

    fc = Forecast()
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fn, arg): (fn, arg) for fn, arg in jobs}
        for fut in cf.as_completed(futs):
            fn, arg = futs[fut]
            try:
                fc.rows.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                label = arg["name"] if isinstance(arg, dict) else str(arg)
                fc.rows.append(SourceCadence(
                    fn.__name__.lstrip("_"), label, error=f"{type(exc).__name__}: {exc}"[:120]))
    return fc
