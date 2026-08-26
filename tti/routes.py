"""Sample a site's routes, not just one page.

One URL per site is enough to prove a failure exists and not enough to
describe a site. Marketing pages are almost always server-rendered; the
interesting failures live on the detail pages where the actual facts are. A
survey that fetches a homepage and concludes the site is fine has measured
the least representative page on it.

So: discover routes from the site's own sitemap, sample them
deterministically, and report the spread. A site whose routes are uniformly
readable is a different claim from one where the docs render and the
reference pages do not, and only the second is actionable.

Discovery order is the site's own declarations, never guessing:

    robots.txt `Sitemap:` directives  (the canonical place to declare them)
    /sitemap.xml
    /sitemap_index.xml

Sampling is stratified over the sorted URL list rather than random, so two
runs against an unchanged sitemap examine the same routes. A survey whose
sample moves between runs cannot show that a site changed.
"""

from __future__ import annotations

import gzip
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from . import http

SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
MAX_SITEMAP_BYTES = 8_000_000
MAX_INDEX_CHILDREN = 5


@dataclass
class RouteSample:
    site: str
    sitemap_urls: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    sampled: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def discovered(self) -> int:
        return len(self.pages)

    @property
    def ok(self) -> bool:
        return bool(self.sampled)


def _sitemaps_from_robots(base: str) -> list[str]:
    try:
        txt = http.get_text(f"{base}/robots.txt", timeout=12, retries=0)
    except Exception:  # noqa: BLE001
        return []
    return [m.group(1).strip() for m in
            re.finditer(r"(?im)^\s*sitemap:\s*(\S+)\s*$", txt)]


def _decode_sitemap(raw: bytes) -> str:
    """Bytes to XML text, transparently un-gzipping.

    Detection is by magic number rather than by the `.gz` suffix or the
    Content-Type header: plenty of sitemaps are gzipped without either, and a
    gzipped body read as text parses as nothing, which is indistinguishable
    from a site that declares no routes at all.
    """
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return ""
    if len(raw) > MAX_SITEMAP_BYTES:
        raw = raw[:MAX_SITEMAP_BYTES]
    # Sitemaps are spec'd as UTF-8; replace rather than raise, so one bad byte
    # does not discard a valid route list.
    return raw.decode("utf-8", "replace")


def _parse_sitemap(url: str, depth: int = 0) -> tuple[list[str], list[str]]:
    """Return (page urls, child sitemap urls)."""
    try:
        body = _decode_sitemap(http.get_bytes(url, timeout=20, retries=0))
    except Exception:  # noqa: BLE001
        return [], []
    if not body:
        return [], []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return [], []
    tag = root.tag.split("}")[-1]
    locs = [e.text.strip() for e in root.iter() if e.tag.split("}")[-1] == "loc"
            and e.text and e.text.strip()]
    if tag == "sitemapindex":
        return [], locs
    return locs, []


def discover(site: str, limit: int = 5000) -> RouteSample:
    parts = urllib.parse.urlsplit(site)
    base = f"{parts.scheme or 'https'}://{parts.netloc or parts.path}"
    rs = RouteSample(site=base)

    candidates = _sitemaps_from_robots(base)
    candidates += [f"{base}/sitemap.xml", f"{base}/sitemap.xml.gz",
                   f"{base}/sitemap_index.xml", f"{base}/sitemap-index.xml"]

    seen: set[str] = set()
    pages: list[str] = []
    for sm in candidates:
        if sm in seen:
            continue
        seen.add(sm)
        found, children = _parse_sitemap(sm)
        if found or children:
            rs.sitemap_urls.append(sm)
        pages.extend(found)
        # One level of index expansion. A site with hundreds of child
        # sitemaps is not going to be characterised better by reading all of
        # them, and reading all of them is rude.
        for child in children[:MAX_INDEX_CHILDREN]:
            if child in seen:
                continue
            seen.add(child)
            sub, _ = _parse_sitemap(child, depth=1)
            pages.extend(sub)
        if len(pages) >= limit:
            break

    # Same-host only: a sitemap may legitimately list a CDN or a docs
    # subdomain, and judging those as this site would be wrong.
    host = parts.netloc or parts.path
    pages = [u for u in dict.fromkeys(pages)
             if urllib.parse.urlsplit(u).netloc == host]
    rs.pages = pages[:limit]
    if not pages:
        rs.note = "no sitemap found, or it listed no same-host pages"
    return rs


def stratified(urls: list[str], n: int) -> list[str]:
    """Evenly spaced picks across the sorted list.

    Deterministic on purpose. A random sample makes two runs incomparable,
    so a site that got worse and a sample that moved look identical.
    Spreading across the sorted order also avoids taking n pages from one
    directory, which is what `urls[:n]` does on almost every sitemap.
    """
    urls = sorted(set(urls))
    if n <= 0 or not urls:
        return []
    if len(urls) <= n:
        return urls
    step = len(urls) / n
    return [urls[min(len(urls) - 1, int(i * step))] for i in range(n)]


def sample(site: str, n: int = 8) -> RouteSample:
    rs = discover(site)
    rs.sampled = stratified(rs.pages, n)
    return rs
