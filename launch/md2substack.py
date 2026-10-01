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
    # come out as a literal "!" followed by an anchor. ![alt](src "caption")
    # adds a caption, the way the Substack editor shows one under an image.
    def figure(m: re.Match) -> str:
        cap = f"<figcaption>{m.group(3)}</figcaption>" if m.group(3) else ""
        return f'<figure><img src="{m.group(2)}" alt="{m.group(1)}">{cap}</figure>'
    text = re.sub(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)', figure, text)
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


# Images must be on the public web for a paste to carry them: Substack fetches
# each one from its URL. Relative paths only work inside this repository.
IMAGE_BASE = "https://raw.githubusercontent.com/abhid1234/time-to-index/main/launch/"

PASTE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Substack paste: {title}</title>
<style>
body{{margin:0;background:#f6f6f4;color:#1c1d1f;font:16px/1.6 -apple-system,"Segoe UI",sans-serif}}
.wrap{{max-width:760px;margin:0 auto;padding:28px 18px 80px}}
.steps{{background:#fff;border:1px solid #dcdcd6;border-radius:10px;padding:16px 20px;font-size:14.5px}}
.steps ol{{margin:6px 0 0;padding-left:20px}}
.field{{display:flex;gap:12px;align-items:flex-start;margin:18px 0 0;background:#fff;
  border:1px solid #dcdcd6;border-radius:10px;padding:14px 16px}}
.field .k{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#6b6d72;width:72px;flex:none;padding-top:3px}}
.field .v{{flex:1;min-width:0;font-weight:600}}
button{{font:600 14px -apple-system,"Segoe UI",sans-serif;background:#1f5fb4;color:#fff;border:0;
  border-radius:7px;padding:8px 14px;cursor:pointer;flex:none}}
button:focus-visible{{outline:2px solid #1c1d1f;outline-offset:2px}}
.done{{background:#1d7a4f}}
.bodyhead{{display:flex;justify-content:space-between;align-items:center;margin:28px 0 8px}}
#post{{background:#fff;border:1px solid #dcdcd6;border-radius:10px;padding:8px 28px 24px}}
#post img{{max-width:100%;height:auto}}
#post pre{{white-space:pre-wrap;background:#f2f2ef;padding:12px;border-radius:6px;font-size:13.5px}}
#post figcaption{{font-size:13.5px;color:#6b6d72;text-align:center}}
</style></head><body><div class="wrap">
<div class="steps"><b>Post to Substack in one go</b><ol>
<li>New post. Click <b>Copy title</b> and paste it into the title field, then <b>Copy subtitle</b> into the subtitle field.</li>
<li>Click <b>Copy body</b>, click into the post body, and paste. Images and captions come with it.</li>
<li>Optional: upload the 91-second video under "Try it in your browser", and add a Subscribe button after the second paragraph.</li>
</ol></div>
<div class="field"><span class="k">Title</span><span class="v" id="title">{title}</span><button data-copy="title">Copy title</button></div>
<div class="field"><span class="k">Subtitle</span><span class="v" id="subtitle">{subtitle}</span><button data-copy="subtitle">Copy subtitle</button></div>
<div class="bodyhead"><b>Body</b><button data-copy="post">Copy body</button></div>
<div id="post">
{body}
</div></div>
<script>
// A selection plus execCommand("copy") puts rich text on the clipboard in
// every browser, including a page opened straight from disk.
document.querySelectorAll("button[data-copy]").forEach(b => b.addEventListener("click", () => {{
  const el = document.getElementById(b.dataset.copy);
  const range = document.createRange(); range.selectNodeContents(el);
  const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
  let ok = false; try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
  sel.removeAllRanges();
  const label = b.textContent;
  b.textContent = ok ? "Copied" : "Select and copy by hand";
  b.classList.toggle("done", ok);
  setTimeout(() => {{ b.textContent = label; b.classList.remove("done"); }}, 1800);
}}));
</script></body></html>
"""


def paste_page(md: str) -> str:
    """Title, subtitle and body as separate copy targets, the way the Substack
    editor takes them, with every image pointed at its public URL."""
    lines = md.splitlines()
    title = lines[0].removeprefix("# ").strip()
    rest = "\n".join(lines[1:]).lstrip()
    subtitle, _, body_md = rest.partition("\n")
    subtitle = subtitle.strip().strip("*")
    body_md = body_md.lstrip()
    if body_md.startswith("---"):
        body_md = body_md[3:]
    body = convert(body_md)
    body = re.sub(r'src="(diagrams/[^"]+)"', lambda m: f'src="{IMAGE_BASE}{m.group(1)}"', body)
    return PASTE_PAGE.format(title=html.escape(title), subtitle=html.escape(subtitle), body=body)


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    # `python md2substack.py essay.md` for the short post; blog.md by default.
    src = here / (sys.argv[1] if len(sys.argv) > 1 else "blog.md")
    dst = src.with_suffix(".html")
    body = convert(src.read_text())
    if src.name == "essay.md":
        page = paste_page(src.read_text())
    else:
        page = (
            "<!-- Paste everything below into the Substack editor. Substack keeps\n"
            "     these tags and drops anything else, so no classes or styles. -->\n"
            + body + "\n")
    dst.write_text(page)
    print(f"wrote {dst} ({len(page)} chars)")

    # A check, not a claim: if a tag Substack drops slipped in, say so.
    kept = {"h1", "h2", "p", "strong", "em", "code", "pre", "ul", "li", "hr",
            "a", "blockquote", "br", "table", "thead", "tbody", "tr", "th",
            "td", "figure", "img", "figcaption"}
    used = set(re.findall(r"<(\w+)", body))
    extra = used - kept
    print("tags used:", " ".join(sorted(used)))
    if extra:
        print("!! tags Substack may drop:", " ".join(sorted(extra)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
