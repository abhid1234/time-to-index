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
# ~300 bytes: the current dist-tags and nothing else. Asked first, on every
# poll. The full packument is fetched only when `latest` differs from the
# high-water mark, which on a five-minute cadence is almost never.
DIST_TAGS = "https://registry.npmjs.org/-/package/{pkg}/dist-tags"

# The full packument is the only document that carries the `time` map, and
# for a package with thousands of releases it is large. Measured 2026-09-02
# through this module's own fetch path, i.e. decompressed bytes as the
# collector sees them: prisma 43.8 MB, vite 38.9, next 31.2, firebase 30.2,
# wrangler 29.6, storybook 24.1, typescript 15.6, antd 8.4.
#
# A correction. The first version of this bound was 32 MB, described as
# "roughly twice the largest seen". It was sized from five packages measured
# with curl -- which reports compressed wire bytes, several times smaller than
# what this code reads -- and the five did not include next, prisma or vite.
# The bound refused two packages and sat within 1 MB of a third on its first
# live run. The number below comes from the collector's own measurement of
# every package that failed, and is written down that way so the next person
# knows which kind of megabyte it is.
#
# The abbreviated packument (Accept: application/vnd.npm.install-v1+json) is
# not a way out: it has no `time` map, and for `next` it is 25.5 MB anyway.
#
# 96 MB is ~2.2x the largest seen. With dist-tags change-detection the full
# fetch is a per-release event, not a per-poll one, so this bound is the
# cold-start path. Peak memory is workers x bound; workers is 4 for that
# reason.
PACKUMENT_CAP = 96_000_000
PACKUMENT_WARN = 72_000_000


def _iso(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _is_prerelease(v: str) -> bool:
    return any(t in v for t in ("-", "canary", "rc", "alpha", "beta", "next", "nightly"))


def fetch_packument(pkg: str, timeout: float = 60.0) -> tuple[dict, int]:
    """The full packument, under the per-source bound, for every caller.

    Three modules read packuments: this collector, `forecast` (release
    cadence over the last sixty days) and `decoy` (does a counterfactual
    version exist). The bound was raised here and not in the other two, and
    the first live forecast then excluded the twelve largest packages from
    the event-rate estimate the stopping rule depends on, while the decoy
    check silently downgraded those same packages to "unverified". One
    function, one bound, and a test that every caller goes through it.
    """
    return http.get_json_sized(API.format(pkg=pkg), timeout=timeout,
                               max_bytes=PACKUMENT_CAP)


def event_from_packument(pkg: str, doc: dict, source: str = "npm",
                         source_class: str = "package_registry") -> Event | None:
    """The Event a packument implies, or None if it implies none.

    Lifted out of the collector so that anything not polling -- the live
    compare endpoint, a test, a one-off -- builds the identical Event. A
    second construction site would be a second definition of what the
    benchmark asks, and the two would drift on the first change to phrasing.

    Deduplication stays with the caller: whether this version has been seen
    before is a fact about a run, not about the packument.
    """
    latest = (doc.get("dist-tags") or {}).get("latest")
    times = doc.get("time") or {}
    if not latest or latest not in times or _is_prerelease(latest):
        return None

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

    return Event(
        source=source,
        source_class=source_class,
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
        # npmjs.com returns 403 to non-browser clients, so the origin control
        # falls back to the registry document and records that it did. See
        # control.probe_origin.
        origins=[f"https://www.npmjs.com/package/{pkg}/v/{latest}",
                 f"https://registry.npmjs.org/{pkg}"],
        meta={"registry": "npm"},
    )


class Npm(BaseSource):
    name = "npm"
    source_class = "package_registry"
    # Bounds peak memory at workers x PACKUMENT_CAP on a cold start.
    workers = 4

    def collect(self, seen):
        return self.fan_out(lambda pkg: self._one(pkg, seen),
                            config.watchlist().get("npm", []))

    def _one(self, pkg: str, seen) -> list[Event]:
            out: list[Event] = []
            # Cheap question first. If the answer has not changed since the
            # last poll, or is a prerelease we would skip anyway, the 30 MB
            # document is never requested.
            tags = http.get_json(DIST_TAGS.format(pkg=pkg), timeout=15.0)
            if not isinstance(tags, dict):
                # Raised, not swallowed. A dist-tags endpoint answering with
                # something other than an object for every subject is the
                # registry having changed its API, and that must read as a
                # broken source -- not as forty-six quiet packages.
                raise ValueError(
                    f"dist-tags response was not an object "
                    f"({type(tags).__name__})")
            latest = tags.get("latest")
            if not latest or _is_prerelease(latest):
                return out
            if seen.get((self.name, pkg)) == latest:
                return out

            doc, size = fetch_packument(pkg)
            if size >= PACKUMENT_WARN:
                self.warnings.append(
                    f"{pkg}: packument is {size / 1e6:.1f} MB, bound is "
                    f"{PACKUMENT_CAP / 1e6:.1f} MB -- raise PACKUMENT_CAP "
                    f"before it crosses")
            ev = event_from_packument(pkg, doc, self.name, self.source_class)
            if ev is None:
                return out
            if seen.get((self.name, pkg)) == ev.answer:
                return out
            out.append(ev)
            return out


@register("npm")
def _factory() -> Npm:
    return Npm()
