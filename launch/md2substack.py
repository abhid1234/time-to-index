"""Turn the blog markdown into HTML that survives a paste into Substack.

Substack's editor keeps a narrow set of tags and throws the rest away, so this
emits only h1/h2/p/strong/em/code/pre/ul/li/hr/a/blockquote/table -- no
classes, no ids, no inline styles beyond what the editor preserves. Anything
fancier arrives as a wall of unstyled text, which is worse than plain.
"""
from __future__ import annotations

import html
import pathlib
import re
import sys


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", text)
    # Images before links: ![alt](src) would otherwise match the link rule and
    # come out as a literal "!" followed by an anchor. No figcaption -- each
    # diagram carries its own title inside the image.
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
                  r'<figure><img src="\2" alt="\1"></figure>', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # Bare URLs on their own become links; Substack does this itself on paste
    # but not reliably when the URL follows a bold label.
    text = re.sub(r"(?<!href=\")(?<!>)(https?://[^\s<]+)(?![^<]*</a>)",
                  r'<a href="\1">\1</a>', text)
    return text


def convert(md: str) -> str:
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            i += 1
            block = []
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(html.escape(lines[i], quote=False))
                i += 1
            out.append("<pre><code>" + "\n".join(block) + "</code></pre>")
        elif line.startswith("## "):
            flush()
            out.append("<h2>" + inline(line[3:]) + "</h2>")
        elif line.startswith("# "):
            flush()
            out.append("<h1>" + inline(line[2:]) + "</h1>")
        elif line.strip() == "---":
            flush()
            out.append("<hr>")
        elif line.startswith("|") and i + 1 < len(lines) and set(
                lines[i + 1].replace("|", "").strip()) <= set("-: "):
            flush()
            head = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            out.append(
                "<table><thead><tr>"
                + "".join(f"<th>{inline(c)}</th>" for c in head)
                + "</tr></thead><tbody>"
                + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r)
                          + "</tr>" for r in rows)
                + "</tbody></table>")
            continue
        elif line.startswith("- "):
            flush()
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append("<li>" + inline(lines[i][2:]) + "</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()
    return "\n\n".join(out)


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    body = convert((here / "blog.md").read_text())
    page = (
        "<!-- Paste everything below into the Substack editor. Substack keeps\n"
        "     these tags and drops anything else, so no classes or styles. -->\n"
        + body + "\n")
    (here / "blog.html").write_text(page)
    print(f"wrote {here / 'blog.html'} ({len(page)} chars)")

    # A check, not a claim: if a tag Substack drops slipped in, say so.
    kept = {"h1", "h2", "p", "strong", "em", "code", "pre", "ul", "li", "hr",
            "a", "blockquote", "br", "table", "thead", "tbody", "tr", "th",
            "td", "figure", "img"}
    used = set(re.findall(r"<(\w+)", body))
    extra = used - kept
    print("tags used:", " ".join(sorted(used)))
    if extra:
        print("!! tags Substack may drop:", " ".join(sorted(extra)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
