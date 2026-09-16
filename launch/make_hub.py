"""One page with the whole launch on it, for the evening you actually post.

Everything here already exists in this directory as separate files. That is
correct for editing and wrong for posting: at the moment you are pasting into
four different sites you want one screen showing the running order, the exact
text of every post with its measured character count, the diagrams to upload,
and what is still outstanding.

Generated from blog.md, linkedin.md, x-thread.md and README.md rather than
written alongside them, so it cannot drift from what you would actually
publish. Self-contained -- fonts and diagrams base64'd -- so it opens from a
phone, a different machine, or an email attachment.
"""
from __future__ import annotations

import base64
import html
import pathlib
import re
import subprocess
import sys

import check_counts
import md2substack

HERE = pathlib.Path(__file__).resolve().parent
FONTDIR = HERE.parent / "docs" / "fonts"

FACES = [("Newsreader", "newsreader-var.woff2", "400 700"),
         ("IBM Plex Sans", "plex-sans-var.woff2", "100 700"),
         ("IBM Plex Mono", "plex-mono-400.woff2", "400"),
         ("IBM Plex Mono", "plex-mono-600.woff2", "600")]


def uri(p: pathlib.Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def fonts() -> str:
    out = []
    for fam, fn, w in FACES:
        f = FONTDIR / fn
        if f.exists():
            out.append(f'@font-face{{font-family:"{fam}";src:url({uri(f, "font/woff2")})'
                       f' format("woff2");font-weight:{w};font-display:block}}')
    return "\n".join(out)


def video_facts() -> list[tuple[str, str, str]]:
    ff = __import__("imageio_ffmpeg").get_ffmpeg_exe()
    out = []
    for name in ("time-to-index-launch.mp4", "time-to-index-teaser.mp4"):
        f = HERE / name
        if not f.exists():
            out.append((name, "not built", "—"))
            continue
        err = subprocess.run([ff, "-i", str(f)], capture_output=True, text=True).stderr
        m = re.search(r"Duration: (\d+):(\d+):(\d+)", err)
        dur = f"{int(m[2])}:{m[3]}" if m else "?"
        audio = "narrated + captioned" if "Audio" in err else "SILENT — check"
        out.append((name, f"{dur} · {f.stat().st_size / 1e6:.0f} MB", audio))
    return out


def posts() -> list[tuple[str, int, str]]:
    """Every X post with the count X will actually apply to it."""
    text = (HERE / "x-thread.md").read_text()
    out = []
    for chunk in re.split(r"\n---\n", text):
        m = re.search(r"\*\*(\d+[a-z]?)/\*\*", chunk)
        if not m:
            continue
        body = chunk[m.end():].strip()
        out.append((m.group(1), check_counts.measured(body), body))
    return out


CSS = """
:root{--ink:#12161C;--ink2:#464F5B;--ink3:#767F8C;--rule:#E2E5EA;--rule2:#CFD5DD;
  --panel:#fff;--inset:#F4F5F7;--ground:#FBFAF8;--accent:#2B5CA8;
  --accent-soft:#EDF2FA;--stale:#BC3E12;--fresh:#0B7A4F}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink2);
  font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:15.5px;
  line-height:1.62;-webkit-font-smoothing:antialiased}
.wrap{max-width:63rem;margin:0 auto;padding:54px 24px 120px}
h1{font-family:Newsreader,serif;font-weight:500;font-size:clamp(30px,4.4vw,42px);
  line-height:1.14;letter-spacing:-.018em;color:var(--ink);margin:0 0 10px}
.sub{font-size:17px;color:var(--ink3);margin:0 0 40px}
h2{font-family:Newsreader,serif;font-weight:500;font-size:25px;color:var(--ink);
  margin:54px 0 16px;letter-spacing:-.012em;
  padding-top:18px;border-top:1px solid var(--rule)}
h3{font-size:14px;font-weight:600;color:var(--ink);margin:26px 0 10px}
p{margin:0 0 15px}
a{color:var(--accent)}
code{font-family:"IBM Plex Mono",monospace;font-size:.87em;background:var(--inset);
  border:1px solid var(--rule);border-radius:4px;padding:.08em .34em;color:var(--ink)}
pre{font-family:"IBM Plex Mono",monospace;font-size:13px;line-height:1.7;
  background:var(--panel);border:1px solid var(--rule);border-radius:9px;
  padding:15px 17px;overflow-x:auto;margin:0 0 18px}
pre code{background:none;border:0;padding:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;
  margin:0 0 22px}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  padding:15px 17px}
.card .k{font-family:"IBM Plex Mono",monospace;font-size:10px;letter-spacing:.13em;
  text-transform:uppercase;color:var(--ink3);display:block;margin-bottom:6px}
.card .v{font-size:18px;color:var(--ink);font-weight:600}
.card .n{font-size:12.5px;color:var(--ink3);margin-top:4px}
ol.steps{counter-reset:s;list-style:none;padding:0;margin:0 0 20px}
ol.steps li{counter-increment:s;position:relative;padding:14px 0 14px 46px;
  border-top:1px solid var(--rule)}
ol.steps li:before{content:counter(s);position:absolute;left:0;top:13px;
  width:27px;height:27px;border-radius:50%;background:var(--accent-soft);
  color:var(--accent);font-family:"IBM Plex Mono",monospace;font-size:12px;
  font-weight:600;display:flex;align-items:center;justify-content:center}
ol.steps b{color:var(--ink)}
.post{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  padding:0;margin:0 0 10px;overflow:hidden}
.post .hd{display:flex;justify-content:space-between;align-items:center;
  padding:9px 15px;background:var(--inset);border-bottom:1px solid var(--rule);
  font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.06em;
  color:var(--ink3)}
.post .hd b{color:var(--accent);font-size:12px}
.post .bd{padding:14px 16px;white-space:pre-wrap;font-size:14.5px;color:var(--ink2)}
.post .n{color:var(--fresh)}
.post .n.warn{color:var(--stale)}
figure{margin:0 0 16px}
figure img{width:100%;height:auto;display:block;border:1px solid var(--rule);
  border-radius:9px;background:var(--panel)}
figcaption{font-family:"IBM Plex Mono",monospace;font-size:10.5px;
  letter-spacing:.11em;text-transform:uppercase;color:var(--ink3);margin-top:8px}
.todo{background:#FFF8E6;border:1px solid #E8D48A;border-radius:10px;
  padding:16px 18px;margin:0 0 22px}
.todo h3{margin-top:0;color:#7A5B00}
.todo li{margin-bottom:8px}
.copy{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  padding:18px 20px;white-space:pre-wrap;font-size:14.5px;margin:0 0 20px}
.blog{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  padding:26px 30px}
.blog h1{font-size:30px;margin-bottom:8px}
.blog h2{font-size:21px;border:0;padding-top:0;margin:34px 0 12px}
.blog table{width:100%;border-collapse:collapse;font-size:13.5px;display:block;
  overflow-x:auto;margin-bottom:18px}
.blog th{text-align:left;font-family:"IBM Plex Mono",monospace;font-size:10px;
  letter-spacing:.12em;text-transform:uppercase;color:var(--ink3);
  padding:0 12px 8px 0;border-bottom:1px solid var(--rule2);white-space:nowrap}
.blog td{padding:9px 12px 9px 0;border-bottom:1px solid var(--rule);
  vertical-align:top}
.blog figure img{border:1px solid var(--rule)}
@media(max-width:640px){.wrap{padding:34px 16px 80px}}
"""


def main() -> int:
    counts = posts()
    over = [p for p in counts if p[1] > 280]

    diagrams = "".join(
        f'<figure><img src="{uri(HERE / "diagrams" / f, "image/png")}">'
        f'<figcaption>{f}</figcaption></figure>'
        for f in ("the-catch.png", "absent-vs-stale.png", "architecture.png",
                  "interval.png")
        if (HERE / "diagrams" / f).exists())

    vids = "".join(
        f'<div class="card"><span class="k">{html.escape(n)}</span>'
        f'<span class="v">{d}</span><div class="n">{a}</div></div>'
        for n, d, a in video_facts())

    postblocks = "".join(
        f'<div class="post"><div class="hd"><b>{n}/</b>'
        f'<span class="n{" warn" if c > 280 else ""}">{c} / 280</span></div>'
        f'<div class="bd">{html.escape(b)}</div></div>'
        for n, c, b in counts)

    blog = md2substack.convert((HERE / "blog.md").read_text())
    blog = re.sub(r'src="(diagrams/[^"]+)"',
                  lambda m: f'src="{uri(HERE / m.group(1), "image/png")}"'
                  if (HERE / m.group(1)).exists() else m.group(0), blog)
    blog = re.sub(r"<p>&gt;&gt;&gt; EMBED.*?&lt;&lt;&lt;</p>",
                  '<p><b>[ video embed goes here — delete this line ]</b></p>',
                  blog, flags=re.S)

    linkedin = (HERE / "linkedin.md").read_text().split("\n", 2)[2].strip()

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>time-to-index — launch</title>
<style>{fonts()}{CSS}</style></head><body><div class="wrap">

<h1>time-to-index — launch pack</h1>
<p class="sub">Everything in one page, generated from the source files. Run the
two pre-flight checks immediately before posting, not now.</p>

<div class="todo">
<h3>Only you can do these</h3>
<ul>
<li><b>Rotate the ElevenLabs key</b> — it is in the session transcript.</li>
<li><b>Rule on the <code>Datadog, Inc.</code> entry</b> in <code>data/watchlist.yaml</code>
    — a T1 partner in a public repo you are about to send traffic to.</li>
<li><b>Download the two video files</b> — they are gitignored, so they are the
    only part of this pack the repo does not protect.</li>
</ul>
</div>

<h2>Running order</h2>
<ol class="steps">
<li><b>Substack.</b> Paste <code>blog.html</code>. Upload the four diagrams where
  the image markers are, and replace the <code>&gt;&gt;&gt; EMBED &lt;&lt;&lt;</code>
  line with the video — that line is plain prose and gets published by accident.</li>
<li><b>Video.</b> Upload the full cut, set <code>thumbnail.png</code>, put the
  Substack link in the description. Do this before the two social posts: the
  LinkedIn copy refers to the video sitting above it.</li>
<li><b>LinkedIn.</b> Paste the text below, upload the full video as native media.
  It truncates around 200 characters and the first line carries it.</li>
<li><b>X.</b> {len(counts)} posts in the order below. Attach the teaser to post 1
  as native media — it costs no characters and autoplay carries the thread.</li>
</ol>

<div class="grid">{vids}</div>

<h2>Pre-flight</h2>
<pre><code>cd launch
python check_claims.py     # every number vs the live ledger
python check_counts.py     # every X post vs the 280 limit</code></pre>
<p>Both exit non-zero on a problem. The gap between finishing the writing and
hitting publish is exactly where drift happens — the event count has already
moved seven → eight → ten → thirteen mid-draft.</p>

<h2>The finding</h2>
{diagrams}

<h2>LinkedIn</h2>
<div class="copy">{html.escape(linkedin)}</div>

<h2>X — {len(counts)} posts{" · " + str(len(over)) + " OVER LIMIT" if over else ""}</h2>
{postblocks}

<h2>The post</h2>
<div class="blog">{blog}</div>

</div></body></html>
"""
    out = HERE / "hub.html"
    out.write_text(page)
    print(f"wrote {out}  ({out.stat().st_size / 1e6:.2f} MB, self-contained)")
    print(f"  {len(counts)} X posts, {len(over)} over limit")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
