"""A 200 at /llms.txt is not proof that an llms.txt exists.

Measured on v0.app: /llms.txt returned 1,283,713 bytes against 1,283,166 for
the home page, and the sign-in links inside carried `next=%2Fllms.txt` -- the
SPA router had taken the path as a route and rendered the app. The summary
counted the bundle's brackets as links and reported a file that is not there.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import framework as fw

SHELL = """<!doctype html><html lang="en"><head><title>v0</title></head>
<body><div id="__next"><a href="/api/auth/login?next=%2Fllms.txt">Log In</a>
<h1>What do you want to create?</h1></div><script>console.log(1)</script>
</body></html>"""

REAL = """# Next.js

> The React framework for the web.

## Docs

- [Routing](https://nextjs.org/docs/routing)
- [Rendering](https://nextjs.org/docs/rendering)
"""


def test_an_app_shell_is_not_an_llms_txt():
    assert fw.serves_html(SHELL) is True


def test_leading_whitespace_and_bom_do_not_hide_the_shell():
    assert fw.serves_html("﻿\n  " + SHELL) is True
    assert fw.serves_html("<HTML><body>x</body></HTML>") is True


def test_a_real_llms_txt_is_not_mistaken_for_a_shell():
    assert fw.serves_html(REAL) is False
    info = fw.summarise_llms_txt(REAL)
    assert info["sections"] == 1
    assert info["links"] == 2
    assert info["title"] == "Next.js"


def test_markdown_quoting_html_further_down_is_still_markdown():
    """Only the opening bytes are examined, so a fenced HTML sample is safe."""
    body = REAL + "\n```html\n<!doctype html><html></html>\n```\n"
    assert fw.serves_html(body) is False
