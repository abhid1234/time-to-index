"""Framework detection and render posture.

The load-bearing test here is `test_an_empty_response_is_never_a_verdict`.
An early version reported a zero-byte proxy error as "client shell, not
readable" — an infrastructure failure wearing the costume of a finding, which
is the exact confusion this project exists to stop making about other
people's systems. Getting it wrong in a tool a stranger points at their own
site would be worse than getting it wrong internally.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti.framework import (
    FLIGHT,
    NO_BODY,
    SHELL,
    SSR,
    STATIC,
    VERDICTS,
    detect_framework,
    finds_token,
    profile,
    robots_matrix,
    visible_text,
)

PROSE = "A perfectly ordinary paragraph of documentation prose. " * 40


def page(head="", body=PROSE):
    return f"<html><head>{head}</head><body>{body}</body></html>"


@pytest.mark.parametrize("marker,expected", [
    ('<script>self.__next_f.push([1,"a"])</script>', "next-app"),
    ('<script id="__NEXT_DATA__">{}</script>', "next-pages"),
    ('<link href="/_next/static/x.css">', "next"),
    ('<script>window.__NUXT__={}</script>', "nuxt"),
    ('<script>__sveltekit_1={}</script>', "sveltekit"),
    ('<astro-island></astro-island>', "astro"),
    ('<script>window.__remixContext={}</script>', "remix"),
    ('<div id="___gatsby"></div>', "gatsby"),
    ('<app-root ng-version="17"></app-root>', "angular"),
    ('', "unknown"),
])
def test_framework_markers(marker, expected):
    assert detect_framework(page(marker))[0] == expected


def test_an_empty_response_is_never_a_verdict():
    for body in ("", "   ", "<html>404</html>", "Not Found"):
        p = profile(body)
        assert p.posture == NO_BODY
        assert VERDICTS[p.posture][0] == "no verdict"


def test_a_real_page_with_prose_is_readable():
    p = profile(page())
    assert p.posture == STATIC
    assert VERDICTS[p.posture][0] == "readable"
    assert p.visible_chars > 900


def test_a_framework_page_with_prose_is_server_rendered():
    p = profile(page('<script>self.__next_f.push([1,"a"])</script>'))
    assert p.framework == "next-app" and p.posture == SSR


def test_a_mount_point_and_a_bundle_is_a_client_shell():
    # Sized like a real shell: kilobytes of head, meta and preload hints, and
    # a mount point. A shell smaller than MIN_BODY_BYTES is `no_body` instead,
    # which is correct — it is too small to be judged at all.
    head = "".join(f'<link rel="preload" href="/_/{i}.js" as="script">' for i in range(60))
    p = profile(f'<html><head>{head}</head><body><div id="root"></div>'
                f'<script src="/b.js"></script></body></html>')
    assert p.posture == SHELL, p
    assert VERDICTS[p.posture][0] == "not readable"


def test_a_response_too_small_to_judge_is_not_called_a_shell():
    tiny = '<html><body><div id="root"></div><script src="/b.js"></script></body></html>'
    assert profile(tiny).posture == NO_BODY


def test_a_thin_page_with_a_large_payload_reads_as_flight():
    """Content that exists only inside a hydration stream is a different
    problem from content that does not exist in the bytes at all: one is an
    extractor question, the other is not answerable by any crawler."""
    payload = '{"content":"' + ("x" * 40_000) + '"}'
    p = profile(f'<html><script id="__NEXT_DATA__">{payload}</script>'
                f'<body><div id="__next"></div></body></html>')
    assert p.posture == FLIGHT
    assert VERDICTS[p.posture][0] == "at risk"


def test_visible_text_excludes_scripts_styles_and_templates():
    html = ('<html><script>var a="SECRET"</script><style>.x{content:"HIDDEN"}</style>'
            '<template>TEMPLATED</template><body>VISIBLE</body></html>')
    t = visible_text(html)
    assert "VISIBLE" in t
    assert "SECRET" not in t and "HIDDEN" not in t and "TEMPLATED" not in t


def test_finds_token_separates_present_from_visible():
    """The gap between these two is the entire point: a fact that is in the
    bytes but not the text is one JavaScript engine away from being found,
    and most crawlers do not have one."""
    assert finds_token("<body><h1>v15.4.2</h1></body>", "15.4.2") == (True, True)
    assert finds_token('<script>{"v":"15.4.2"}</script><body></body>',
                       "15.4.2") == (True, False)
    assert finds_token("<body>nothing here</body>", "15.4.2") == (False, False)


def test_token_matching_follows_the_grader_rules():
    assert finds_token("<body>15.4.20</body>", "15.4.2") == (False, False)
    assert finds_token("<body>115.4.2</body>", "15.4.2") == (False, False)
    assert finds_token("<body>v15.4.2</body>", "15.4.2") == (True, True)


def test_robots_matrix_respects_specific_agent_blocks_over_wildcard():
    """Precedence between a named agent and `*` is the thing people get wrong
    when they audit one of these by eye."""
    txt = ("User-agent: *\nAllow: /\n\n"
           "User-agent: GPTBot\nDisallow: /\n\n"
           "User-agent: CCBot\nDisallow: /private/\n")
    m = robots_matrix(txt, "https://example.com/article")
    assert m["GPTBot"] is False
    assert m["CCBot"] is True
    assert m["ClaudeBot"] is True
    m2 = robots_matrix(txt, "https://example.com/private/x")
    assert m2["CCBot"] is False
