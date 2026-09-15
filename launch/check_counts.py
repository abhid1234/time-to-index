"""Count every X post the way X counts, and fail if one is over.

X counts a URL as 23 characters regardless of its real length, so measuring
with len() understates a post with a link in it and overstates nothing. A
thread that looks fine in an editor and truncates on posting is a bad way to
find that out.

The post-number regex takes a letter suffix. It did not, once, and the script
cheerfully reported "all 15 posts" on a thread that had 16 -- an uncounted
post in the post-counting script.
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
LIMIT = 280
URL_LEN = 23
URL = re.compile(r"https?://\S+")


def measured(body: str) -> int:
    return len(URL.sub("x" * URL_LEN, body).strip())


def main() -> int:
    text = (HERE / "x-thread.md").read_text()
    posts = re.split(r"\n---\n", text)
    bad = 0
    found: list[str] = []
    for chunk in posts:
        m = re.search(r"\*\*(\d+[a-z]?)/\*\*", chunk)
        if not m:
            continue
        num = m.group(1)
        found.append(num)
        body = chunk[m.end():].strip()
        n = measured(body)
        flag = "ok" if n <= LIMIT else "OVER"
        if n > LIMIT:
            bad += 1
        print(f"  {num:>4}/{n:>5}  {flag}")
    print()
    if bad:
        print(f"{bad} post(s) over {LIMIT}")
        return 1
    print(f"all {len(found)} posts under {LIMIT} ({', '.join(found)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
