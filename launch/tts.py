"""Render the narration to wavs, from inside this sandbox.

ElevenLabs is 403 at the egress proxy's CONNECT, before any key is checked,
and Piper's voice models moved to HuggingFace, which is blocked as well. What
*is* reachable is Google's translate_tts endpoint, which needs no credential
and returns an ordinary mp3. It is not ElevenLabs, but it is a clear, natural
voice and it is available now, which beats a better one that is not.

Two things it demands. It caps a request at a couple of hundred characters, so
long lines are split on sentence boundaries and concatenated; and it is a
public endpoint, so requests are paced rather than fired in a batch.

Writes build/vo-external/<beat>-<index>.wav -- the same drop-in path an
external take would use, so make_video.py needs no flag and no change. Delete
that directory to go back to the silent captioned cut.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import vo

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "build" / "vo-external"
TMP = HERE / "build" / "tts-parts"
ENDPOINT = "https://translate.googleapis.com/translate_tts"
CHUNK = 190          # the endpoint truncates past roughly two hundred
PACE = 0.7           # seconds between requests; it is a public endpoint


def split(text: str) -> list[str]:
    """Sentence-aligned chunks under the endpoint's limit.

    Splitting mid-sentence is audible: the synthesiser drops the pitch as if
    the thought had ended, and the join lands as a stumble.
    """
    import re
    sentences = re.split(r"(?<=[.!?]) +", text)
    out: list[str] = []
    buf = ""
    for s in sentences:
        if len(buf) + len(s) + 1 <= CHUNK:
            buf = f"{buf} {s}".strip()
            continue
        if buf:
            out.append(buf)
        while len(s) > CHUNK:                    # a single very long sentence
            cut = s.rfind(",", 0, CHUNK)
            if cut < CHUNK // 2:
                cut = s.rfind(" ", 0, CHUNK)
            out.append(s[:cut + 1].strip())
            s = s[cut + 1:].strip()
        buf = s
    if buf:
        out.append(buf)
    return out


def fetch(text: str, path: pathlib.Path) -> None:
    url = f"{ENDPOINT}?ie=UTF-8&client=tw-ob&tl=en&q={urllib.parse.quote(text)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(4):
        try:
            data = urllib.request.urlopen(req, timeout=40).read()
            if len(data) < 800 or data[:2] not in (b"\xff\xfb", b"\xff\xf3", b"ID"):
                raise RuntimeError(f"not audio ({len(data)} bytes)")
            path.write_bytes(data)
            return
        except Exception as exc:                 # noqa: BLE001 - retry anything
            if attempt == 3:
                raise SystemExit(f"tts failed for {path.name}: {exc}")
            time.sleep(1.5 * (attempt + 1))


def main() -> int:
    ff = __import__("imageio_ffmpeg").get_ffmpeg_exe()
    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)

    total = 0.0
    for i, (beat, _off, text) in enumerate(vo.LINES):
        wav = OUT / f"{beat}-{i}.wav"
        chunks = split(text)
        parts = []
        for n, chunk in enumerate(chunks):
            mp3 = TMP / f"{i:02d}-{n}.mp3"
            if not mp3.exists():
                fetch(chunk, mp3)
                time.sleep(PACE)
            parts.append(mp3)

        listing = TMP / f"{i:02d}.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
        subprocess.run(
            [ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing),
             # One pass to 22.05k mono: the endpoint returns 24k, and leaving
             # the rate alone made the mix stage resample every line
             # separately, which is where the hiss came from.
             "-ar", "22050", "-ac", "1", str(wav)],
            cwd=TMP, check=True)

        import wave
        with wave.open(str(wav)) as w:
            d = w.getnframes() / w.getframerate()
        total += d
        print(f"  {i:2d}  {beat:<17}{d:5.1f}s  {len(chunks)} chunk(s)")

    print(f"\n{len(vo.LINES)} lines, {total / 60:.1f} min of speech")
    print("now: python budgets.py && python record.py && python make_video.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
