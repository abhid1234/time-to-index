"""An original ambient bed for the short cut.

The AgentRoute video this format is modelled on has a soft instrumental track
and nothing in its repo says where that track came from or under what licence.
Reusing an unattributed track on a public launch invites a content-ID claim
that mutes or blocks the video on the platforms it is meant for. So this
composes one instead: same mood -- warm, slow, unobtrusive -- and the same
loudness shape as the reference (a quiet open, a build by twenty seconds, a
long sustain, a fade), with nothing in it that anyone else owns.

Numpy only. Additive synthesis keeps every voice band-limited, so nothing needs
a filter; the room is an FFT convolution with a decaying-noise impulse response.

    python make_music.py --seconds 90 --out music.wav
"""
from __future__ import annotations

import argparse
import wave

import numpy as np

SR = 44100
BPM = 68
BEAT = 60 / BPM
CHORD_LEN = BEAT * 8          # two bars per chord

# D major, voiced low and open. maj9 / m9 colour without tension.
PROGRESSION = [
    ("Dmaj9", [50, 57, 61, 64, 66]),     # D A C# E F#
    ("Bm9",   [47, 54, 57, 61, 62]),     # B F# A C# D
    ("Gmaj9", [43, 50, 54, 57, 59]),     # G D F# A B
    ("Aadd9", [45, 52, 57, 59, 61]),     # A E A B C#
]


def hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def env_adsr(n: int, a: float, r: float) -> np.ndarray:
    t = np.arange(n) / SR
    e = np.minimum(1.0, t / a) if a > 0 else np.ones(n)
    tail = np.clip((n / SR - t) / r, 0, 1)
    return e * tail


def pad_voice(freq: float, n: int, rng: np.random.Generator) -> np.ndarray:
    """Three slightly detuned partial stacks -- a soft, chorused pad."""
    t = np.arange(n) / SR
    out = np.zeros(n)
    for cents in (-6.0, 0.0, 5.0):
        f = freq * 2 ** (cents / 1200)
        ph = rng.uniform(0, 2 * np.pi)
        for k, amp in ((1, 1.0), (2, 0.28), (3, 0.10), (4, 0.04)):
            out += amp * np.sin(2 * np.pi * f * k * t + ph * k)
    # a very slow swell so held chords breathe instead of sitting flat
    out *= 0.85 + 0.15 * np.sin(2 * np.pi * 0.11 * t + rng.uniform(0, 6.28))
    return out / 3.0


def pluck(freq: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * freq * t) + 0.22 * np.sin(2 * np.pi * 2 * freq * t) \
        + 0.06 * np.sin(2 * np.pi * 3 * freq * t)
    e = np.minimum(1.0, t / 0.006) * np.exp(-t / 0.55)
    return tone * e


def reverb(x: np.ndarray, seed: int, secs: float = 3.4, decay: float = 1.6) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(secs * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-t / decay)
    # darken the tail: a cheap moving-average low-pass on the impulse response
    k = 24
    ir = np.convolve(ir, np.ones(k) / k, mode="same")
    ir[: int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))   # pre-delay
    ir /= np.sqrt(np.sum(ir ** 2))
    size = 1 << int(np.ceil(np.log2(len(x) + n)))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)
    return y[: len(x)]


def compose(seconds: float, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    N = int(seconds * SR)
    pad = np.zeros(N)
    bass = np.zeros(N)
    arp = np.zeros(N)

    # --- pad and bass, one chord every two bars, crossfaded -----------------
    overlap = 2.2
    c = 0
    start = 0.0
    while start < seconds:
        name, notes = PROGRESSION[c % len(PROGRESSION)]
        s = int(start * SR)
        dur = min(CHORD_LEN + overlap, seconds - start)
        n = int(dur * SR)
        e = env_adsr(n, 1.9, 2.4)
        chord = sum(pad_voice(hz(m + 12), n, rng) for m in notes[1:]) / 4
        pad[s:s + n] += chord * e
        root = hz(notes[0] - 12)
        tb = np.arange(n) / SR
        b = (np.sin(2 * np.pi * root * tb) + 0.15 * np.sin(2 * np.pi * 2 * root * tb))
        bass[s:s + n] += b * env_adsr(n, 1.2, 2.0)
        start += CHORD_LEN
        c += 1

    # --- a sparse arpeggio, entering once the pad has settled ---------------
    step = BEAT / 2
    pattern = [0, 2, 1, 3, 2, 4, 3, 1]          # indices into the chord's upper voices
    t0, t1 = 11.0, seconds - 7.0
    i = 0
    tt = t0
    while tt < t1:
        ci = int(tt // CHORD_LEN) % len(PROGRESSION)
        notes = PROGRESSION[ci][1]
        m = notes[pattern[i % len(pattern)]] + 24
        # leave rests so it reads as a figure, not a metronome
        if i % 8 not in (5, 7):
            vel = 0.55 + 0.25 * rng.random()
            p = pluck(hz(m), 1.8) * vel
            s = int(tt * SR)
            e = min(N, s + len(p))
            arp[s:e] += p[: e - s]
        i += 1
        tt += step

    # --- mix, room, shape ---------------------------------------------------
    dry = 0.62 * pad + 0.34 * bass + 0.20 * arp
    left = 0.72 * dry + 0.40 * reverb(dry, 1)
    right = 0.72 * np.roll(dry, int(0.011 * SR)) + 0.40 * reverb(dry, 2)

    # A slow leveller. Chords differ in energy -- the low Gmaj9 voicing sat
    # four decibels under its neighbours -- and the reference holds its body
    # steady. Follow loudness over two seconds and pull it toward a constant,
    # gently enough that nothing audibly pumps.
    mono = 0.5 * (left + right)
    win = int(2.0 * SR)
    power = np.convolve(mono ** 2, np.ones(win) / win, mode="same")
    level = np.sqrt(np.maximum(power, 1e-10))
    ref = np.median(level[int(12 * SR): int((seconds - 8) * SR)])
    gain = (ref / level) ** 0.75
    gain = np.clip(gain, 0.5, 2.2)
    sm = int(1.5 * SR)
    gain = np.convolve(gain, np.ones(sm) / sm, mode="same")
    left, right = left * gain, right * gain

    t = np.arange(N) / SR
    # The reference's shape: quiet first seconds, full by ~20 s, fade at the end.
    shape = np.interp(t, [0, 2.5, 9, 20, seconds - 6, seconds],
                         [0.0, 0.35, 0.55, 1.0, 1.0, 0.0])
    st = np.stack([left, right], axis=1) * shape[:, None]

    # loudness: the reference sits around -17 dBFS once it has built
    body = st[int(20 * SR): int((seconds - 7) * SR)]
    rms = np.sqrt(np.mean(body ** 2)) if len(body) else np.sqrt(np.mean(st ** 2))
    st *= 10 ** (-16 / 20) / max(rms, 1e-9)
    peak = np.max(np.abs(st))
    if peak > 0.89:                                  # -1 dBFS ceiling
        st *= 0.89 / peak
    return st


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--out", default="music.wav")
    a = ap.parse_args()
    st = compose(a.seconds)
    pcm = (np.clip(st, -1, 1) * 32767).astype("<i2")
    with wave.open(a.out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"wrote {a.out}  {a.seconds:.0f}s")


if __name__ == "__main__":
    main()
