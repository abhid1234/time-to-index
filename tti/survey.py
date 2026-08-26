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
from collections import Counter
from dataclasses import dataclass, field

from . import config, http
from .framework import (
    NO_BODY,
    SSR,
    STATIC,
    VERDICTS,
    PageProfile,
    profile,
    robots_matrix,
)

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

    @property
    def usable(self) -> bool:
        """Did we get a real page? Not "is it good" -- "can it be judged"."""
        return (self.status == 200 and self.prof is not None
                and self.prof.posture != NO_BODY)

    @property
    def readable(self) -> bool:
        return self.usable and self.prof.posture in READABLE_POSTURES

    @property
    def verdict(self) -> str:
        if not self.usable:
            return "no verdict"
        return VERDICTS[self.prof.posture][0]


@dataclass
class Survey:
    results: list[SiteResult] = field(default_factory=list)

    @property
    def usable(self) -> list[SiteResult]:
        return [r for r in self.results if r.usable]

    @property
    def unreachable(self) -> list[SiteResult]:
        return [r for r in self.results if not r.usable]

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


def _fetch(url: str, category: str, timeout: float) -> SiteResult:
    res = SiteResult(url=url, category=category)
    try:
        resp = http.raw_get(url, timeout=timeout, retries=0, headers={
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"})
        res.status = resp.status_code
        res.prof = profile(resp.text)
    except Exception as exc:  # noqa: BLE001
        res.error = f"{type(exc).__name__}: {exc}"[:160]
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
        timeout: float = 14.0) -> Survey:
    targets = targets or load_corpus()
    sv = Survey()
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_fetch, u, c, timeout) for u, c in targets]
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
    if sv.unreachable:
        lines += ["", f"_{len(sv.unreachable)} targets could not be fetched and are "
                      f"excluded from every rate above._"]
    return "\n".join(lines)
