"""npm registry.

`GET https://registry.npmjs.org/<pkg>` returns a `time` map from version
string to ISO publish timestamp, written by the registry at publish. That is
the ground truth clock. `dist-tags.latest` gives the current version and the
`time` map gives its predecessor, which is what makes staleness measurable
here: the question "what is the latest version of X" had a correct answer
yesterday that is wrong today.
"""

from __future__ import annotations

import datetime as dt
import time

from .. import config, http
from ..models import Event
from . import BaseSource, register

API = "https://registry.npmjs.org/{pkg}"


def _iso(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _is_prerelease(v: str) -> bool:
    return any(t in v for t in ("-", "canary", "rc", "alpha", "beta", "next", "nightly"))


class Npm(BaseSource):
    name = "npm"
    source_class = "package_registry"

    def collect(self, seen):
        return self.fan_out(lambda pkg: self._one(pkg, seen),
                            config.watchlist().get("npm", []))

    def _one(self, pkg: str, seen) -> list[Event]:
            out: list[Event] = []
            doc = http.get_json(API.format(pkg=pkg), timeout=15.0)
            latest = (doc.get("dist-tags") or {}).get("latest")
            times = doc.get("time") or {}
            if not latest or latest not in times or _is_prerelease(latest):
                return out

            published = _iso(times[latest])
            # Predecessor = the stable version published immediately before.
            stable = sorted(
                ((v, _iso(t)) for v, t in times.items()
                 if v not in ("created", "modified") and not _is_prerelease(v)),
                key=lambda vt: vt[1],
            )
            prev = None
            for v, ts in reversed(stable[:-1]) if len(stable) > 1 else []:
                if ts < published:
                    prev = v
                    break

            if seen.get((self.name, pkg)) == latest:
                return out

            out.append(Event(
                source=self.name,
                source_class=self.source_class,
                subject=pkg,
                published_at=published,
                discovered_at=time.time(),
                question=(
                    f"What is the current latest published version of the "
                    f"npm package {pkg}?"
                ),
                answer=latest,
                answer_aliases=[latest, f"v{latest}", f"{pkg}@{latest}"],
                predecessor=prev,
                predecessor_aliases=(
                    [prev, f"v{prev}", f"{pkg}@{prev}"] if prev else []),
                url=f"https://www.npmjs.com/package/{pkg}/v/{latest}",
                # npmjs.com returns 403 to non-browser clients, so the origin
                # control falls back to the registry document and records that
                # it did. See control.probe_origin.
                origins=[f"https://www.npmjs.com/package/{pkg}/v/{latest}",
                         f"https://registry.npmjs.org/{pkg}"],
                meta={"registry": "npm"},
            ))
            return out


@register("npm")
def _factory() -> Npm:
    return Npm()
