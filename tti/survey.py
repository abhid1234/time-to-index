"""How much of the web an agent needs is readable without a JavaScript engine?

The benchmark's other half measures providers. This measures the corpus they
have to work with, and it is the half a site owner can do something about.

The distinction being counted is narrow and checkable: does the page's
content arrive in the served bytes as text, or does it arrive as instructions
for producing text. Most crawlers, including several that feed large AI
systems, do not run those instructions. When they do not, a page can be
perfectly correct, perfectly fast, fully permitted by robots.txt, and still
contribute nothing.

That combination is the interesting one, and it shows up in the wild: a
registry that explicitly allows every AI crawler in its robots.txt while
serving them a mount point and a bundle. Nobody decided that. It falls out
of a rendering default.

Nothing here is about any one framework. The survey records what it finds and
the aggregation is by posture first, framework second, because the posture is
what predicts retrievability and the framework only correlates with it.
"""

from __future__ import annotations

import concurrent.futures as cf
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field

from . import config, http
from .framework import (
    METADATA,
    NO_BODY,
    SSR,
    STATIC,
    VERDICTS,
    PageProfile,
    profile,
    robots_matrix,
)

# `metadata_only` is deliberately not in here. An agent reads JSON-LD without
# executing anything, which is real and is reported on its own -- but it does
# not get the page's content, and counting it as readable would let a registry
# that ships a name and hides its version table score as fine.
READABLE_POSTURES = (SSR, STATIC)


@dataclass
class SiteResult:
    url: str
    category: str = ""
    status: int | None = None
    prof: PageProfile | None = None
    robots_blocked: list[str] = field(default_factory=list)
    robots_checked: int = 0
    error: str = ""
    # Repeat-fetch agreement. A verdict about somebody's site should not rest
    # on one HTTP request: a transient proxy error, a rate limit, or an edge
    # node having a bad minute all produce a response that classifies
    # perfectly and means nothing. Observed in development -- the same URL
    # returned 5,056 bytes of SvelteKit shell on one run and a zero-byte 404
    # on the next.
    attempts: int = 1
    postures_seen: list[str] = field(default_factory=list)
    stable: bool = True

    @property
    def usable(self) -> bool:
        """Did we get a real page we can stand behind?

        Not "is it good" -- "can it be judged". Requires a 200, a body big
        enough to classify, and agreement across repeats.
        """
        return (self.status == 200 and self.prof is not None
                and self.prof.posture != NO_BODY and self.stable)

    @property
    def readable(self) -> bool:
        return self.usable and self.prof.posture in READABLE_POSTURES

    @property
    def verdict(self) -> str:
        if not self.stable:
            return "unstable"
        if not self.usable:
            return "no verdict"
        return VERDICTS[self.prof.posture][0]

    @property
    def why_unusable(self) -> str:
        if self.error:
            return self.error
        if not self.stable:
            return f"fetches disagreed: {' / '.join(self.postures_seen)}"
        if self.status != 200:
            return f"HTTP {self.status}"
        if self.prof is not None and self.prof.posture == NO_BODY:
            return "response too small to classify"
        return "unknown"


@dataclass
class Survey:
    results: list[SiteResult] = field(default_factory=list)

    @property
    def usable(self) -> list[SiteResult]:
        return [r for r in self.results if r.usable]

    @property
    def unreachable(self) -> list[SiteResult]:
        return [r for r in self.results if not r.usable]

    @property
    def unstable(self) -> list[SiteResult]:
        return [r for r in self.results if not r.stable]

    def metadata_only(self) -> list[SiteResult]:
        """Pages whose body is a shell but which ship readable metadata.

        Reported on their own because the honest description is neither
        "readable" nor "not readable": an agent learns what the page is and
        not what it says."""
        return [r for r in self.results
                if r.stable and r.prof is not None and r.prof.posture == METADATA]

    def readable_rate(self) -> tuple[int, int]:
        u = self.usable
        return sum(1 for r in u if r.readable), len(u)

    def by_posture(self) -> Counter:
        return Counter(r.prof.posture for r in self.usable)

    def by_framework(self) -> dict[str, tuple[int, int]]:
        out: dict[str, list[int]] = {}
        for r in self.usable:
            cell = out.setdefault(r.prof.framework, [0, 0])
            cell[1] += 1
            if r.readable:
                cell[0] += 1
        return {k: (v[0], v[1]) for k, v in sorted(out.items())}

    def by_category(self) -> dict[str, tuple[int, int]]:
        out: dict[str, list[int]] = {}
        for r in self.usable:
            cell = out.setdefault(r.category or "uncategorised", [0, 0])
            cell[1] += 1
            if r.readable:
                cell[0] += 1
        return {k: (v[0], v[1]) for k, v in sorted(out.items())}

    def text_ratios(self) -> list[float]:
        return sorted(r.prof.text_ratio for r in self.usable)

    def open_but_unreadable(self) -> list[SiteResult]:
        """Pages that invite every AI crawler and hand them nothing.

        The sharpest category in the survey, because it is the one nobody
        chose. A team that sets robots.txt to allow AI agents has decided they
        want to be read; if the page is a client shell, that decision is
        silently not in effect.
        """
        return [r for r in self.usable
                if not r.readable and r.robots_checked and not r.robots_blocked]

    def open_and_empty(self) -> list[SiteResult]:
        """The strict version: invites every AI crawler and ships *nothing*.

        Separated from `open_but_unreadable` because a page with breadcrumb
        JSON-LD over a client shell is not the same claim as a page with 32
        characters and no metadata at all, and the difference is the kind a
        reader will check. Overstating it by one site is how the whole survey
        stops being believed.
        """
        return [r for r in self.open_but_unreadable()
                if r.prof is not None and r.prof.posture != METADATA]


def _fetch(url: str, category: str, timeout: float, repeat: int = 2,
           gap: float = 1.5) -> SiteResult:
    res = SiteResult(url=url, category=category, attempts=repeat)
    profs: list[PageProfile] = []
    last_status: int | None = None
    last_error = ""

    for i in range(max(1, repeat)):
        if i:
            time.sleep(gap)     # separate samples in time, not just in count
        try:
            resp = http.raw_get(url, timeout=timeout, retries=0, headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"})
            last_status = resp.status_code
            pr = profile(resp.text)
            profs.append(pr)
            res.postures_seen.append(pr.posture if resp.status_code == 200
                                     else f"HTTP{resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"[:160]
            res.postures_seen.append("error")

    res.status = last_status
    res.error = last_error if not profs else ""
    if not profs:
        return res

    # Keep the richest observation -- a truncated response classifies as a
    # worse posture than the site deserves, and the goal is never to be
    # unfairly harsh about somebody's page.
    res.prof = max(profs, key=lambda p: p.bytes_total)
    res.stable = len(set(res.postures_seen)) == 1
    if not res.stable:
        return res

    if res.usable:
        import urllib.parse
        parts = urllib.parse.urlsplit(url)
        try:
            robots = http.get_text(f"{parts.scheme}://{parts.netloc}/robots.txt",
                                   timeout=10, retries=0)
            matrix = robots_matrix(robots, url)
            res.robots_checked = len(matrix)
            res.robots_blocked = [a for a, ok in matrix.items() if ok is False]
        except Exception:  # noqa: BLE001
            pass
    return res


def run(targets: list[tuple[str, str]] | None = None, workers: int = 12,
        timeout: float = 14.0, repeat: int = 2) -> Survey:
    targets = targets or load_corpus()
    sv = Survey()
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_fetch, u, c, timeout, repeat) for u, c in targets]
        for f in cf.as_completed(futs):
            sv.results.append(f.result())
    return sv


def load_corpus() -> list[tuple[str, str]]:
    doc = config.load("corpus")
    out: list[tuple[str, str]] = []
    for category, urls in (doc or {}).items():
        for u in urls or []:
            out.append((u, category))
    return out


def markdown(sv: Survey) -> str:
    hit, n = sv.readable_rate()
    ratios = sv.text_ratios()
    lines = [
        f"**{hit} of {n} pages** were readable without executing JavaScript.",
        "",
    ]
    if ratios:
        lines.append(
            f"Median visible-text ratio {statistics.median(ratios)*100:.1f}% "
            f"(range {ratios[0]*100:.2f}%–{ratios[-1]*100:.1f}%).")
        lines.append("")
    lines += ["| posture | pages |", "|---|---|"]
    for posture, count in sv.by_posture().most_common():
        lines.append(f"| `{posture}` | {count} |")
    lines += ["", "| framework | readable | pages |", "|---|---|---|"]
    for fw, (h, t) in sv.by_framework().items():
        lines.append(f"| `{fw}` | {h/t*100:.0f}% | {t} |")
    meta = sv.metadata_only()
    if meta:
        lines += ["", f"_{len(meta)} page(s) shipped readable metadata over an "
                      f"unreadable body: an agent learns what the page is, not what "
                      f"it says._"]
    if sv.unstable:
        lines += ["", f"_{len(sv.unstable)} target(s) gave different answers across "
                      f"repeat fetches and are excluded. A verdict about someone's "
                      f"site should not rest on one request._"]
    if sv.unreachable:
        lines += ["", f"_{len(sv.unreachable)} targets could not be judged and are "
                      f"excluded from every rate above._"]
    return "\n".join(lines)
