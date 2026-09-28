"""Turn the raw capture into the finished video: captions, audio, 1080p.

Captions are rendered as transparent PNGs through the same headless Chromium
that renders the site, then overlaid by ffmpeg at the times vo.py computes.
Drawing them with ffmpeg's drawtext would have meant shipping a TTF; the page
self-hosts woff2, and a caption in a different typeface than the product it is
captioning looks like someone else made it.

Audio is optional. ElevenLabs is unreachable from this sandbox -- the egress
proxy answers 403 to CONNECT on api.elevenlabs.io before any key is checked --
so this produces a captioned silent cut by default, and picks up per-line wavs
the moment they appear in build/vo-external/<beat>-<index>.wav. Run
`python vo.py --script` to get the numbered lines to feed a TTS.

Video length, not audio length, drives the output. `-shortest` cut the picture
the instant the last word ended, so the final syllable landed on the final
frame with nothing after it -- which reads as the file being truncated.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import vo

HERE = pathlib.Path(__file__).resolve().parent
BUILD = HERE / "build"
CAPS = BUILD / "caps"
FONTS = "http://127.0.0.1:8890/fonts"
CHROME = "/opt/pw-browsers/chromium"
W, H = 1920, 1080
CAP_W, CAP_H = 1560, 210

CAP_HTML = """
<style>
@font-face{{font-family:"IBM Plex Sans";src:url({f}/plex-sans-var.woff2)format("woff2");font-weight:100 700}}
html,body{{margin:0;background:transparent}}
body{{width:{w}px;height:{h}px;display:flex;align-items:flex-end;
  justify-content:center;font-family:"IBM Plex Sans",sans-serif}}
.cap{{background:rgba(9,12,16,.88);color:#F4F5F7;border-radius:12px;
  padding:16px 26px;font-size:31px;line-height:1.36;font-weight:400;
  letter-spacing:-.005em;text-align:center;max-width:{w}px;
  box-shadow:0 8px 34px rgba(0,0,0,.34);-webkit-font-smoothing:antialiased}}
.cap b{{color:#7FB2FF;font-weight:600}}
</style>
<div class="cap">{text}</div>
"""

# Words worth lifting out of a caption. Not decoration: on a muted autoplay
# these are the only things a scrolling reader will actually take in.
EMPH = [r"0\.12\.15", r"0\.12\.14", r"\bSTALE\b", r"\bABSENT\b", r"\bFRESH\b",
        r"\bzero\b", r"\bnothing\b", r"\bnot a rate\b", r"\bnot a ranking\b"]


ALL = {r"0\.12\.15", r"0\.12\.14"}


def emphasise(text: str) -> str:
    out = text
    for pat in EMPH:
        out = re.sub(pat, lambda m: f"<b>{m.group(0)}</b>", out,
                     count=0 if pat in ALL else 1)
    return out


def render_captions(lines: list[dict]) -> None:
    from playwright.sync_api import sync_playwright
    CAPS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME,
                               args=["--hide-scrollbars",
                                     "--force-color-profile=srgb"])
        pg = b.new_page(viewport={"width": CAP_W, "height": CAP_H},
                        device_scale_factor=1)
        for ln in lines:
            pg.set_content(CAP_HTML.format(f=FONTS, w=CAP_W, h=CAP_H,
                                           text=emphasise(ln["caption"])),
                           wait_until="load")
            pg.wait_for_timeout(120)
            pg.screenshot(path=str(CAPS / f"{ln['i']:02d}.png"),
                          omit_background=True)
        b.close()
    print(f"  rendered {len(lines)} captions")


def probe_duration(ff: str, path: pathlib.Path) -> float:
    err = subprocess.run([ff, "-i", str(path)], capture_output=True,
                         text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if not m:
        raise SystemExit(f"could not read duration of {path}")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def main() -> int:
    ff = __import__("imageio_ffmpeg").get_ffmpeg_exe()
    raw = BUILD / "screen-raw.webm"
    if not raw.exists():
        raise SystemExit("no build/screen-raw.webm -- run record.py first")

    lines = vo.placement()
    render_captions(lines)
    vdur = probe_duration(ff, raw)
    spoken = max(ln["start"] + ln["dur"] for ln in lines)
    if spoken > vdur - 1.0:
        print(f"  ! narration ends {spoken:.1f}s but picture is {vdur:.1f}s "
              f"-- re-run budgets.py and record.py")

    external = BUILD / "vo-external"
    wavs = [(ln, external / f"{ln['beat']}-{ln['i']}.wav") for ln in lines]
    have_audio = [(ln, p) for ln, p in wavs if p.exists()]

    inputs: list[str] = ["-i", str(raw)]
    filters: list[str] = []

    # Upscale first: overlaying a caption PNG before the scale would soften it.
    filters.append(f"[0:v]scale={W}:{H}:flags=lanczos,fps=30[bg]")
    last = "bg"
    for n, ln in enumerate(lines):
        inputs += ["-i", str(CAPS / f"{ln['i']:02d}.png")]
        idx = n + 1
        a, b = ln["start"], ln["start"] + ln["dur"] + 0.45
        tag = f"v{n}"
        filters.append(
            f"[{last}][{idx}:v]overlay=(W-w)/2:H-h-58:"
            f"enable='between(t,{a:.2f},{b:.2f})'[{tag}]")
        last = tag

    filters.append(f"[{last}]fade=t=in:st=0:d=0.5,"
                   f"fade=t=out:st={vdur - 1.4:.2f}:d=1.4[v]")

    maps = ["-map", "[v]"]
    if have_audio:
        labels = []
        base = 1 + len(lines)
        for n, (ln, path) in enumerate(have_audio):
            inputs += ["-i", str(path)]
            k = base + n
            ms = int(ln["start"] * 1000)
            filters.append(f"[{k}:a]adelay={ms}|{ms},volume=1.55[a{n}]")
            labels.append(f"[a{n}]")
        filters.append(f"{''.join(labels)}amix=inputs={len(have_audio)}:"
                       f"normalize=0:dropout_transition=0[mix]")
        filters.append(f"[mix]dynaudnorm=f=180:g=9,alimiter=limit=0.94,"
                       f"afade=t=out:st={vdur - 1.6:.2f}:d=1.4[a]")
        maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k", "-ar", "44100"]
        print(f"  muxing {len(have_audio)}/{len(lines)} narration lines")
    else:
        print("  no narration wavs found -- rendering the captioned silent cut")
        print("  (python vo.py --script  prints the lines to feed a TTS)")

    out = HERE / "time-to-index-launch.mp4"
    cmd = [ff, "-y", "-loglevel", "error", *inputs,
           "-filter_complex", ";".join(filters), *maps,
           "-c:v", "libx264", "-preset", "slow", "-crf", "20",
           "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart",
           str(out)]
    subprocess.run(cmd, check=True)
    print(f"\nwrote {out}  ({out.stat().st_size / 1e6:.1f} MB, "
          f"{int(vdur) // 60}:{int(vdur) % 60:02d})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
