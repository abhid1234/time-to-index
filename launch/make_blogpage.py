"""A readable, self-contained preview of the post.

`blog.html` is deliberately ugly: it is the Substack paste buffer, and Substack
throws away every class, style and id, so anything beyond bare tags there is
wasted. Opening it in a browser therefore shows unstyled text with broken
images -- the diagrams are relative paths, so they vanish the moment the file
is moved or opened through a viewer that does not resolve siblings.

This is the other half: one file, nothing external, that shows what the post
actually reads like. Fonts and all three diagrams are base64'd in, so it can be
mailed, dropped in a message, or opened from anywhere. The type and palette are
the playground's, so the post, the diagrams, the video and the site are visibly
one thing.

Publishing still goes through blog.html. This exists to be read and judged
before that happens.
"""
from __future__ import annotations

import base64
import pathlib
import re
import sys

import md2substack

HERE = pathlib.Path(__file__).resolve().parent
FONTDIR = HERE.parent / "docs" / "fonts"

FONT_FACES = [
    ("Newsreader", "newsreader-var.woff2", "400 700"),
    ("IBM Plex Sans", "plex-sans-var.woff2", "100 700"),
    ("IBM Plex Mono", "plex-mono-400.woff2", "400"),
    ("IBM Plex Mono", "plex-mono-600.woff2", "600"),
]


def data_uri(path: pathlib.Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def fonts() -> str:
    out = []
    for family, fn, weight in FONT_FACES:
        f = FONTDIR / fn
        if not f.exists():
            continue
        out.append(f'@font-face{{font-family:"{family}";'
                   f'src:url({data_uri(f, "font/woff2")}) format("woff2");'
                   f'font-weight:{weight};font-style:normal;font-display:block}}')
    return "\n".join(out)


CSS = """
:root{
  --ink:#12161C;--ink2:#464F5B;--ink3:#767F8C;--rule:#E2E5EA;--rule2:#CFD5DD;
  --panel:#FFFFFF;--inset:#F4F5F7;--ground:#FBFAF8;
  --accent:#2B5CA8;--accent-soft:#EDF2FA;--stale:#BC3E12;
  --measure:41rem;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--ground);color:var(--ink2);
  font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:17.5px;
  line-height:1.68;-webkit-font-smoothing:antialiased;
  font-variant-numeric:tabular-nums}
main{max-width:var(--measure);margin:0 auto;padding:72px 26px 120px}

.kicker{font-family:"IBM Plex Mono",monospace;font-size:11.5px;font-weight:600;
  letter-spacing:.16em;text-transform:uppercase;color:var(--accent);
  margin:0 0 20px}
h1{font-family:Newsreader,Georgia,serif;font-weight:500;
  font-size:clamp(34px,5.2vw,49px);line-height:1.13;letter-spacing:-.018em;
  color:var(--ink);margin:0 0 20px}
.standfirst{display:block;font-size:20px;line-height:1.55;color:var(--ink3);
  font-style:normal}
h1 + p{margin:0 0 34px}
h2{font-family:Newsreader,Georgia,serif;font-weight:500;font-size:28px;
  line-height:1.22;letter-spacing:-.012em;color:var(--ink);margin:62px 0 18px}
p{margin:0 0 21px}
strong{color:var(--ink);font-weight:600}
a{color:var(--accent);text-decoration:none;
  border-bottom:1px solid color-mix(in srgb,var(--accent) 34%,transparent);
  padding-bottom:1px}
a:hover{border-bottom-color:var(--accent)}
hr{border:0;border-top:1px solid var(--rule);margin:34px 0}
code{font-family:"IBM Plex Mono",monospace;font-size:.875em;
  background:var(--inset);border:1px solid var(--rule);border-radius:4px;
  padding:.1em .34em;color:var(--ink)}
pre{font-family:"IBM Plex Mono",monospace;font-size:13.5px;line-height:1.75;
  background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  padding:18px 20px;overflow-x:auto;margin:0 0 24px;color:var(--ink2)}
pre code{background:none;border:0;padding:0;font-size:inherit}
ul{margin:0 0 22px;padding-left:22px}
li{margin:0 0 9px}
li::marker{color:var(--rule2)}

/* Diagrams and the verdict table get to break the measure -- they are the
   widest things here and squeezing them into body width is what made them
   unreadable. */
figure{margin:34px 0 38px;width:min(58rem,calc(100vw - 52px));
  position:relative;left:50%;transform:translateX(-50%)}
figure img{display:block;width:100%;height:auto;border-radius:11px;
  border:1px solid var(--rule);background:var(--panel)}

table{width:100%;border-collapse:collapse;margin:6px 0 28px;font-size:15px;
  display:block;overflow-x:auto}
th{text-align:left;font-family:"IBM Plex Mono",monospace;font-size:10.5px;
  letter-spacing:.13em;text-transform:uppercase;color:var(--ink3);
  font-weight:600;padding:0 14px 9px 0;border-bottom:1px solid var(--rule2);
  white-space:nowrap}
td{padding:11px 14px 11px 0;border-bottom:1px solid var(--rule);
  vertical-align:top;line-height:1.55}
tr:last-child td{border-bottom:0}
td:first-child{color:var(--ink)}

.note{background:var(--accent-soft);border:1px solid
  color-mix(in srgb,var(--accent) 22%,transparent);border-radius:10px;
  padding:15px 18px;font-size:14px;line-height:1.6;color:var(--ink2);
  margin:0 0 40px}
.note b{color:var(--accent)}
footer{max-width:var(--measure);margin:0 auto;padding:0 26px 90px;
  font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink3)}

@media (max-width:640px){
  main{padding:46px 20px 80px}
  body{font-size:16.5px}
  figure{width:calc(100vw - 40px)}
}
"""


def main() -> int:
    body = md2substack.convert((HERE / "blog.md").read_text())

    # The first paragraph after the title is the standfirst; give it the
    # larger, quieter treatment rather than letting it read as body copy.
    body = body.replace("<p><em>A search index that is wrong",
                        '<p class="standfirst"><em>A search index that is wrong', 1)

    # Inline every diagram. A preview whose images only resolve from one
    # directory is the exact failure this file exists to fix.
    missing = []

    def embed(m: re.Match[str]) -> str:
        src = HERE / m.group(1)
        if not src.exists():
            missing.append(m.group(1))
            return m.group(0)
        return f'src="{data_uri(src, "image/png")}"'

    body, n = re.subn(r'src="(diagrams/[^"]+)"', embed, body)
    if missing:
        print(f"!! {len(missing)} diagram(s) not on disk, left as links: "
              + ", ".join(missing))
        print("   run: python make_diagrams.py  (needs http.server 8890 in docs/)")

    # The video placeholder is an instruction to the publisher, not prose.
    body = re.sub(
        r"<p>&gt;&gt;&gt; EMBED.*?&lt;&lt;&lt;</p>",
        '<p class="note"><b>Video goes here.</b> In the Substack draft this line '
        'is where the walkthrough is embedded, and the line itself is deleted.</p>',
        body, flags=re.S)

    title = re.search(r"<h1>(.*?)</h1>", body)[1]
    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
{fonts()}
{CSS}
</style>
</head><body>
<main>
<p class="kicker">time-to-index</p>
{body}
</main>
<footer>Preview only — publishing goes through blog.html</footer>
</body></html>
"""
    out = HERE / "blog-preview.html"
    out.write_text(page)
    print(f"wrote {out}  ({out.stat().st_size / 1e6:.2f} MB, "
          f"{n - len(missing)}/3 diagrams inlined)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
