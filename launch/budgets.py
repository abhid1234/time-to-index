"""How long the picture must hold for each beat.

Computed from the narration *alone*. The first version of this read beat times
out of the previous recording, which made it circular: every pass inherited
the drift of the one before it, and six and a half minutes of picture ended up
carrying three and three quarter minutes of speech. A budget derived from the
words cannot drift, because the words are the only input.

Writes build/budgets.json for record.py, which pads each beat to its budget.
"""
from __future__ import annotations

import json
import pathlib
import sys

import vo

HERE = pathlib.Path(__file__).resolve().parent
BUILD = HERE / "build"

# A beat needs its last line to finish, plus a moment before the cut. Too
# small and the final syllable lands on the transition; too large and the
# whole thing feels padded, which it is.
TAIL = 1.4


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    durs = vo.durations()

    # Lay the lines out against beat-relative time, applying the same "never
    # before the previous line has finished" rule vo.py uses, but per beat --
    # at this stage there is no recording to ask, so beats start at zero.
    GAP = 0.55
    need: dict[str, float] = {}
    cursor: dict[str, float] = {}
    for i, (beat, off, _text) in enumerate(vo.LINES):
        start = max(off, cursor.get(beat, 0.0) + GAP)
        end = start + durs[i]
        cursor[beat] = end
        need[beat] = max(need.get(beat, 0.0), end + TAIL)

    budgets = {b: round(v, 2) for b, v in need.items()}
    (BUILD / "budgets.json").write_text(json.dumps(budgets, indent=2))

    speech = sum(durs) + GAP * (len(durs) - 1)
    picture = sum(budgets.values())
    for b, v in budgets.items():
        print(f"  {b:<18}{v:6.1f}s")
    print(f"\nspeech {speech / 60:.1f} min · picture floor {picture / 60:.1f} min "
          f"· {100 * (picture - speech) / picture:.0f}% air")
    return 0


if __name__ == "__main__":
    sys.exit(main())
