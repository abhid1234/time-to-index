"""PyPI JSON API.

`GET https://pypi.org/pypi/<pkg>/json` gives `info.version` plus a `releases`
map whose file records carry `upload_time_iso_8601`, stamped by the index at
upload. Same supersession property as npm.
"""

from __future__ import annotations

import datetime as dt
import time

from .. import config, http
from ..models import Event
from . import BaseSource, register

API = "https://pypi.org/pypi/{pkg}/json"


def _iso(s: str) -> float:
    if not s.endswith(("Z", "+00:00")):
        s += "+00:00"
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _release_time(files: list[dict]) -> float | None:
    ts = [_iso(f["upload_time_iso_8601"]) for f in files if f.get("upload_time_iso_8601")]
    return min(ts) if ts else None      # first artifact of the release


def _is_prerelease(v: str) -> bool:
    return any(t in v for t in ("a", "b", "rc", "dev")) and not v.replace(".", "").isdigit()


class PyPI(BaseSource):
    name = "pypi"
    source_class = "package_registry"

    def collect(self, seen):
        return self.fan_out(lambda pkg: self._one(pkg, seen),
                            config.watchlist().get("pypi", []))

    def _one(self, pkg: str, seen) -> list[Event]:
            out: list[Event] = []
            doc = http.get_json(API.format(pkg=pkg), timeout=15.0)
            latest = (doc.get("info") or {}).get("version")
            releases = doc.get("releases") or {}
            if not latest or latest not in releases:
                return out
            published = _release_time(releases[latest])
            if published is None:
                return out

            dated = []
            for v, files in releases.items():
                if _is_prerelease(v):
                    continue
                t = _release_time(files)
                if t is not None:
                    dated.append((v, t))
            dated.sort(key=lambda vt: vt[1])
            prev = next((v for v, t in reversed(dated) if t < published), None)

            if seen.get((self.name, pkg)) == latest:
                return out

            out.append(Event(
                source=self.name,
                source_class=self.source_class,
                subject=pkg,
                published_at=published,
                discovered_at=time.time(),
                question=(
                    f"What is the current latest released version of the "
                    f"Python package {pkg} on PyPI?"
                ),
                answer=latest,
                answer_aliases=[latest, f"v{latest}", f"{pkg} {latest}", f"{pkg}=={latest}"],
                predecessor=prev,
                predecessor_aliases=[p for p in ([prev, f"v{prev}", f"{pkg}=={prev}"] if prev else [])],
                url=f"https://pypi.org/project/{pkg}/{latest}/",
                meta={"registry": "pypi"},
            ))
            return out


@register("pypi")
def _factory() -> PyPI:
    return PyPI()
