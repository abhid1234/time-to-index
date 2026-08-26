"""What built this page, and can an agent read it without running JavaScript?

The control arm already classifies *where* a fact sits — visible text, a
script-embedded data blob, or nowhere. This asks the next question: what put
it there.

That matters because it is the one finding in this benchmark a site owner can
act on. "Provider X is slow" is somebody else's problem. "Your content is
only in a hydration payload, so a crawler that does not execute JavaScript
cannot read it" is a rendering decision, and rendering decisions are made in
a framework config file.

Detection is by served-byte markers, not by guessing:

    Next.js Pages Router   __NEXT_DATA__ script, /_next/static/
    Next.js App Router     self.__next_f.push flight stream
    Nuxt                   __NUXT__, /_nuxt/
    SvelteKit              __sveltekit_, /_app/immutable/
    Astro                  astro-island, data-astro-cid
    Remix / React Router   __remixContext, __reactRouterContext
    Gatsby                 ___gatsby, /page-data/
    Docusaurus             docusaurus-plugin markers

Render posture is separate from framework and is the part that actually
predicts retrievability. A framework does not decide it; how the app is
written does. The same Next.js version produces a fully server-rendered
article and an empty shell with a fetch in a useEffect.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# (name, [regex markers]) — ordered so the most specific wins.
_FRAMEWORKS: list[tuple[str, list[str]]] = [
    ("next-app", [r"self\.__next_f\.push", r"__next_f"]),
    ("next-pages", [r"id=\"__NEXT_DATA__\"", r"__NEXT_DATA__"]),
    ("next", [r"/_next/static/", r"/_next/image"]),
    ("nuxt", [r"window\.__NUXT__", r"/_nuxt/"]),
    ("sveltekit", [r"__sveltekit_", r"/_app/immutable/"]),
    ("astro", [r"astro-island", r"data-astro-cid", r"/_astro/"]),
    ("remix", [r"__remixContext", r"__reactRouterContext"]),
    ("gatsby", [r"___gatsby", r"/page-data/"]),
    ("docusaurus", [r"docusaurus", r"__docusaurus"]),
    ("angular", [r"ng-version=", r"<app-root"]),
    ("vue-spa", [r"id=\"app\"[^>]*></div>", r"__VUE_"]),
    ("react-spa", [r"id=\"root\"[^>]*></div>"]),
]

# Rendering posture.
SSR = "server_rendered"      # substantive text in the HTML itself
FLIGHT = "flight_payload"    # text only inside an RSC/hydration data stream
SHELL = "client_shell"       # almost no text and no metadata; a mount point
METADATA = "metadata_only"   # body is a shell, but it ships JSON-LD/OG an agent reads
STATIC = "static_html"       # text present and no framework markers at all
UNKNOWN = "unknown"          # not classifiable — never a verdict about a site
NO_BODY = "no_body"          # empty or near-empty response; nothing to judge

# A response has to be big enough to be a page before it can be called a bad
# one. This constant exists because an early version confidently reported a
# zero-byte proxy error as "client shell, not readable" -- an infrastructure
# failure wearing the costume of a finding, which is the exact confusion this
# project was built to stop making about other people's systems.
MIN_BODY_BYTES = 200

_SCRIPTY = re.compile(r"<(script|style|template|noscript)\b[^>]*>.*?</\1>",
                      re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Below this ratio of visible text to served bytes, a page is carrying far
# more machinery than content. Calibrated loosely on purpose: it is a signal
# to look, not a verdict, and the posture call never rests on it alone.
SHELL_TEXT_RATIO = 0.012
SHELL_TEXT_CHARS = 900


@dataclass
class Structured:
    """Machine-readable metadata a page ships alongside its HTML.

    This exists because the first version of the verdict was wrong in a way
    that mattered. A page whose body is a client shell can still ship JSON-LD,
    OpenGraph tags and a meta description -- and an agent reads those without
    executing anything. Calling such a page "not readable" overstates the
    problem and would be a bad claim to make in public about someone's site.

    What it does *not* fix: metadata is a summary. A registry page that ships
    a name and a description but renders its version table client-side has
    told an agent what the package is and not what version it is on, which is
    the fact that was actually being asked for. So this is a third state, not
    a pardon.
    """
    jsonld_blocks: int = 0
    jsonld_types: list[str] = field(default_factory=list)
    jsonld_chars: int = 0
    opengraph: int = 0
    meta_description: str = ""
    microdata_attrs: int = 0

    @property
    def substantive(self) -> bool:
        """Enough machine-readable content to answer something.

        A single og:title is not structured data in any useful sense; every
        page has one. The bar is a real JSON-LD block, or a description plus
        several OpenGraph tags, or genuine microdata markup.
        """
        return (self.jsonld_chars >= 200
                or (len(self.meta_description) >= 50 and self.opengraph >= 3)
                or self.microdata_attrs >= 8)

    @property
    def chars(self) -> int:
        return self.jsonld_chars + len(self.meta_description)


@dataclass
class PageProfile:
    framework: str = "unknown"
    posture: str = UNKNOWN
    bytes_total: int = 0
    visible_chars: int = 0
    script_chars: int = 0
    body_sha: str = ""
    evidence: list[str] = field(default_factory=list)
    structured: Structured = field(default_factory=lambda: Structured())

    @property
    def text_ratio(self) -> float:
        return self.visible_chars / self.bytes_total if self.bytes_total else 0.0

    @property
    def is_next(self) -> bool:
        return self.framework.startswith("next")

    def summary(self) -> str:
        return (f"{self.framework} · {self.posture} · "
                f"{self.visible_chars:,} chars visible of {self.bytes_total:,} served "
                f"({self.text_ratio*100:.1f}%)")


_JSONLD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL)
_OG = re.compile(r'<meta[^>]+property=["\']og:[a-z:]+["\']', re.IGNORECASE)
_DESC = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{0,400})',
    re.IGNORECASE)
_MICRO = re.compile(r'itemscope|itemprop=', re.IGNORECASE)
_LDTYPE = re.compile(r'"@type"\s*:\s*"([^"]{1,60})"')


def extract_structured(html: str) -> Structured:
    st = Structured()
    blocks = _JSONLD.findall(html)
    st.jsonld_blocks = len(blocks)
    st.jsonld_chars = sum(len(b.strip()) for b in blocks)
    seen: list[str] = []
    for b in blocks:
        for t in _LDTYPE.findall(b):
            if t not in seen:
                seen.append(t)
    st.jsonld_types = seen[:8]
    st.opengraph = len(_OG.findall(html))
    m = _DESC.search(html)
    st.meta_description = (m.group(1).strip() if m else "")
    st.microdata_attrs = len(_MICRO.findall(html))
    return st


def visible_text(html: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", _SCRIPTY.sub(" ", html))).strip()


def script_text(html: str) -> str:
    return " ".join(m.group(0) for m in _SCRIPTY.finditer(html))


def detect_framework(html: str) -> tuple[str, list[str]]:
    for name, markers in _FRAMEWORKS:
        hits = [m for m in markers if re.search(m, html, re.IGNORECASE)]
        if hits:
            return name, hits
    return "unknown", []


def profile(html: str) -> PageProfile:
    p = PageProfile(bytes_total=len(html))
    p.body_sha = hashlib.sha256(html.encode("utf-8", "replace")).hexdigest()
    if len(html) < MIN_BODY_BYTES:
        p.posture = NO_BODY
        return p
    p.framework, p.evidence = detect_framework(html)
    vis = visible_text(html)
    p.visible_chars = len(vis)
    p.script_chars = len(script_text(html))
    p.structured = extract_structured(html)

    thin = p.visible_chars < SHELL_TEXT_CHARS or p.text_ratio < SHELL_TEXT_RATIO
    if thin and p.structured.substantive:
        # Readable metadata on an unreadable body. A real third state: the
        # agent learns what the page is about and not what it says.
        p.posture = METADATA
        return p
    if p.framework == "unknown":
        p.posture = STATIC if not thin else SHELL
    elif thin:
        # A framework page with almost no readable text is either a client
        # shell or a page whose content lives entirely in a hydration stream.
        # The distinction is whether the payload is large enough to be
        # carrying the content rather than just the app.
        p.posture = FLIGHT if p.script_chars > 20_000 else SHELL
    else:
        p.posture = SSR
    return p


def finds_token(html: str, token: str) -> tuple[bool, bool]:
    """(present anywhere in the bytes, present in the visible text).

    The gap between these two booleans is the whole point of this module: a
    fact that is present but not visible is one JavaScript engine away from
    being found, and most crawlers do not have one.
    """
    core = re.escape(token)
    if token[:1].isdigit():
        core = "[vV]?" + core      # same rule as grader._pattern
    pat = re.compile(rf"(?<![\w.]){core}(?![\w.])", re.IGNORECASE)
    return bool(pat.search(html)), bool(pat.search(visible_text(html)))


VERDICTS = {
    SSR: ("readable", "An agent that does not execute JavaScript can read this page."),
    STATIC: ("readable", "Plain server-delivered HTML. Nothing to execute."),
    FLIGHT: ("at risk", "The content appears to live in a hydration or flight payload "
                        "rather than in the HTML. Whether an agent sees it depends "
                        "entirely on that agent's extractor."),
    SHELL: ("not readable", "The served HTML is a mount point and a bundle. An agent "
                            "that does not run JavaScript sees nothing."),
    METADATA: ("partial", "The body is a client shell, but the page ships "
                          "machine-readable metadata (JSON-LD or OpenGraph). An agent "
                          "gets a summary without executing anything — it does not get "
                          "the page's actual content."),
    UNKNOWN: ("unknown", "Could not classify."),
    NO_BODY: ("no verdict", "The response was empty or too small to be a page. "
                            "This says something about the fetch, not about the site."),
}


# ---------------------------------------------------------------------------
# AI crawler access
# ---------------------------------------------------------------------------

# The user-agents that decide whether a page enters an AI system at all. Split
# by what they feed, because a site owner's answer is often different for
# each: many are happy to be cited in an answer and unhappy to be training
# data, and robots.txt is where that distinction actually gets made.
AI_AGENTS = {
    "GPTBot": "OpenAI — training",
    "OAI-SearchBot": "OpenAI — search results",
    "ChatGPT-User": "OpenAI — user-initiated fetch",
    "ClaudeBot": "Anthropic — training",
    "Claude-User": "Anthropic — user-initiated fetch",
    "Claude-SearchBot": "Anthropic — search",
    "PerplexityBot": "Perplexity — index",
    "Google-Extended": "Google — Gemini training",
    "Applebot-Extended": "Apple — training",
    "CCBot": "Common Crawl — feeds many downstream corpora",
    "Bytespider": "ByteDance",
    "meta-externalagent": "Meta",
}


def robots_matrix(robots_txt: str, url: str) -> dict[str, bool | None]:
    """Which AI agents robots.txt permits for this URL.

    Uses the stdlib parser per agent rather than reading the file by eye,
    because precedence between a specific agent block and `*` is exactly the
    thing people get wrong when they hand-audit one of these.
    """
    import urllib.robotparser
    out: dict[str, bool | None] = {}
    for agent in AI_AGENTS:
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.parse(robots_txt.splitlines())
            out[agent] = rp.can_fetch(agent, url)
        except Exception:  # noqa: BLE001
            out[agent] = None
    return out
