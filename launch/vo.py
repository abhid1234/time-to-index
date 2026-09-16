"""Narration for the screen recording — the words, and the muxer that lays them over.

The script is a list of lines, each pinned to a beat name from the recording
rather than to a timestamp. `record.py` writes build/beats.json with the real
time each beat started, so re-cutting the recording does not require retiming
by hand: the two are joined here.

Audio is optional and always external. ElevenLabs is unreachable from this
sandbox -- the egress proxy answers 403 to CONNECT on api.elevenlabs.io before
any key is checked -- so this renders a silent cut by default and picks up
per-line wavs if they are dropped in at build/vo-external/<beat>-<index>.wav.
`python vo.py --script` prints the numbered lines to feed a TTS by hand.

The same lines are burned in as captions by record.py, which is not a
consolation prize: most people meet this video muted in a feed, and a screen
recording with no words on it is a screen recording nobody can follow.

Written to be *spoken*: no parentheses, no symbols a synthesiser mangles,
numbers spelled the way a person says them, and short sentences, because a
long one read flat is where TTS falls apart.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
BUILD = HERE / "build"

# (beat, offset seconds after that beat starts, text)
LINES: list[tuple[str, float, str]] = [
    ("hero", 0.4,
     "Here is a problem I could not stop thinking about. Every retrieval "
     "benchmark I could find scores a lie the same way it scores a shrug."),
    ("hero", 7.6,
     "A search A P I that returns nothing, and a search A P I that "
     "confidently returns yesterday's answer, both score zero. In production "
     "they are nothing alike."),

    ("ground_truth", 1.0,
     "So I built the thing that separates them. And the trick is not crawling "
     "anything."),
    ("ground_truth", 5.4,
     "I watch the places that timestamp their own publications. N P M. "
     "Pie Pea Eye. Github releases. When a package is published, the registry "
     "itself says exactly when. That timestamp is time zero, and it is the "
     "publisher's clock, never mine. This panel is fetching it live, right "
     "now, with no key and no crawler."),

    ("ladder_run", 1.2,
     "Then every search index gets the same question at six fixed lags after "
     "publication. Five minutes. Fifteen minutes. One hour. Six hours. Twenty "
     "four hours. Seventy two hours."),
    ("ladder_run", 9.0,
     "Watch what comes back."),

    ("matrix_read", 0.8,
     "Green means the index returned the new answer. Grey means it returned "
     "nothing. And orange means it returned the version that was replaced, "
     "confidently, as though it were current."),
    ("matrix_read", 8.6,
     "Look at provider D along the bottom. It answered instantly at every "
     "single rung, and it was wrong every single time. Three full days of a "
     "confident, outdated answer."),

    ("scoring_old", 1.4,
     "Now score it the way retrieval benchmarks actually score it. Did a "
     "plausible result come back."),
    ("scoring_old", 6.6,
     "Provider D is second. The index that was wrong for three days is near "
     "the top of the leaderboard, because a confidently wrong answer counts "
     "the same as a correct one."),

    ("scoring_new", 1.2,
     "Now change one thing. Ask instead whether the current answer came back."),
    ("scoring_new", 6.0,
     "The ranking inverts. Provider D drops to last and gets flagged for six "
     "wrong answers. Same probes. Same responses. Only the question changed."),

    ("brackets", 0.8,
     "And when an index is absent at fifteen minutes and fresh at an hour, "
     "the truthful answer is a bracket, not a point. That is interval "
     "censored survival data, the same maths clinical trials use when "
     "patients outlive the study."),

    ("takeaway", 1.0,
     "That is the entire argument, and it costs almost nothing to measure."),
    ("takeaway", 5.2,
     "Artificial Analysis launched a search index for these same A P Is in "
     "August. It is serious work, and the best cost analysis published on "
     "them. All three of its component benchmarks are answer correctness "
     "scores, so a provider that returned nothing and a provider that "
     "returned yesterday's answer score identically."),
    ("aa_note", 0.8,
     "Their harness gives the agent twenty five turns. Hand it an empty result "
     "set and it retries and widens until it finds the answer. Hand it a "
     "confidently outdated one and it has no signal to retry on, so it "
     "submits. To be fair to them, burning all twenty five turns without "
     "finishing scores zero, so an absence can cost correctness in the tail. "
     "But short of that it costs turns, tokens and latency, and their cost "
     "and time columns capture all three. A stale answer costs none of "
     "those."),

    ("measured", 1.2,
     "Everything you have seen so far is a simulation, and the page says so. "
     "This part is not."),
    ("measured", 5.4,
     "Every square below is a real A P I call this project made to a real "
     "search product, at a fixed lag after a real package was published."),

    ("measured_punch", 0.6,
     "Here is the clearest thing it has caught. U V zero point twelve point "
     "fifteen was released on Github. My collector saw it two hundred and "
     "seventy four seconds later."),
    ("measured_punch", 9.5,
     "Five minutes after the release went live, four search indexes and the "
     "origin control were asked what the current version was."),

    ("measured_events", 1.0,
     "The control fetched zero point twelve point fifteen in four hundred and "
     "sixteen milliseconds. So the release was live, on the web, and "
     "retrievable at that exact moment."),
    ("measured_events", 10.0,
     "Exa returned zero point twelve point fourteen. Parallel's advanced mode "
     "returned zero point twelve point fourteen. The same superseded version, "
     "independently, at the same instant. The other two returned nothing at "
     "all."),
    ("measured_events", 21.5,
     "Not one of the four had the current answer, and half of them "
     "confidently asserted the old one. Every conventional benchmark scores "
     "those two stale rows exactly the same as the two empty ones. Zero. In "
     "production they are not the same event at all."),
    ("measured_events", 34.0,
     "Across the whole run, four stale verdicts, on three separate packages, "
     "across three different arms. And I have to say the next part in the "
     "same breath. Thirteen events is not a rate and it is not a ranking. At "
     "this sample size no pair of arms separates, which is why the "
     "leaderboard refuses to rank itself."),

    ("legend", 0.8,
     "And notice what the empty squares say. Not due yet. Not run yet. Never "
     "scheduled. A rung with no result is never drawn as an absence, because "
     "a benchmark that renders we haven't asked as the index didn't have it "
     "is committing the exact error it exists to name."),

    ("end", 0.6,
     "It is M I T licensed, the whole ledger is in the repository, and the "
     "link is below. If you work on one of these indexes and think the "
     "methodology is unfair to you, I want to hear it."),
]


def caption(text: str) -> str:
    """The spoken line, turned back into something worth reading.

    The narration spells things out for a synthesiser -- "A P I", "zero point
    twelve point fifteen" -- which is right in the ear and wrong on screen.
    """
    fixes = [
        (r"\bA P I\b", "API"), (r"\bA P Is\b", "APIs"), (r"\bN P M\b", "npm"),
        (r"\bPie Pea Eye\b", "PyPI"), (r"\bM I T\b", "MIT"),
        (r"\bU V zero point twelve point fifteen\b", "uv 0.12.15"),
        (r"\bzero point twelve point fifteen\b", "0.12.15"),
        (r"\bzero point twelve point fourteen\b", "0.12.14"),
        (r"\btwo hundred and seventy four seconds\b", "274 seconds"),
        (r"\bfour hundred and sixteen milliseconds\b", "416 ms"),
        (r"\btwenty five turns\b", "25 turns"),
        (r"\bThirteen events\b", "Thirteen events"),
    ]
    for pat, rep in fixes:
        text = re.sub(pat, rep, text)
    return text


def durations() -> list[float]:
    """How long each line takes to say.

    With no audio this is an estimate, and the estimate is what the captions
    and the beat budgets are built from, so it has to be the same number in
    both places. 2.6 words per second is unhurried narration pace; a rendered
    wav overrides it whenever one exists.
    """
    import wave
    external = BUILD / "vo-external"
    out = []
    for i, (beat, _off, text) in enumerate(LINES):
        swap = external / f"{beat}-{i}.wav"
        if swap.exists():
            with wave.open(str(swap)) as w:
                out.append(w.getnframes() / w.getframerate())
        else:
            out.append(max(2.0, len(text.split()) / 2.6))
    return out


def placement() -> list[dict]:
    """Where each line starts, given the beats the recording actually used.

    An offset is a *floor*, not a fixed time. A line never starts before its
    beat plus its offset, and never before the previous line has finished plus
    a breath -- so a take that runs long pushes the rest of the script later
    instead of talking over it. Hand-tuned offsets drift every time a word
    changes; this cannot.
    """
    beats = {b["beat"]: b["t"] for b in
             json.loads((BUILD / "beats.json").read_text())}
    GAP = 0.55
    durs = durations()
    out: list[dict] = []
    cursor = 0.0
    for i, (beat, off, text) in enumerate(LINES):
        if beat not in beats:
            raise SystemExit(f"beat {beat!r} is not in the recording")
        start = max(beats[beat] + off, cursor + GAP)
        out.append({"i": i, "beat": beat, "start": round(start, 2),
                    "dur": round(durs[i], 2), "text": text,
                    "caption": caption(text)})
        cursor = start + durs[i]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", action="store_true",
                    help="print the numbered lines for an external TTS")
    args = ap.parse_args()

    if args.script:
        print("Render each line and save it as "
              "build/vo-external/<beat>-<index>.wav, then re-run make_video.py.\n")
        for i, (beat, _off, text) in enumerate(LINES):
            print(f"--- {beat}-{i}.wav")
            print(text)
            print()
        return 0

    for p in placement():
        print(f"  {p['start']:6.1f}s  {p['dur']:5.1f}s  {p['beat']:<16} "
              f"{p['text'][:52]}…")
    total = max(p["start"] + p["dur"] for p in placement())
    print(f"\n  narration ends at {total:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
