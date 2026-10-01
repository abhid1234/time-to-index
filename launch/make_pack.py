"""Copy every file the launch needs into one folder, in posting order.

    python launch/make_pack.py        # -> launch/pack/

Copies, not new content: each file comes from its source (essay, diagrams,
video, posts), so re-running after `check_claims.py` passes keeps the pack in
step with the ledger. Git stores identical files once, so the copies of the
video and images cost the repository nothing.
"""
from __future__ import annotations

import pathlib
import shutil

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
PACK = HERE / "pack"

SETTINGS = """On the repo page, click the gear icon next to "About":

Description:
How long a new fact takes to reach web-search APIs, and whether they answer nothing or confidently answer with yesterday's fact.

Website:
https://abhid1234.github.io/time-to-index/

Topics:
web-search benchmark freshness staleness llm-agents rag information-retrieval survival-analysis

Then Settings > General > Social preview > upload social-preview.png (in this folder).
"""

PLAYGROUND = """THE PLAYGROUND (The Staleness Playground)

Public link, used in all the posts:
  https://abhid1234.github.io/time-to-index/playground.html
  Its data refreshes after every probe run.

Your claude.ai copy (private until you share it from its Share menu):
  https://claude.ai/artifact/B4StuZXAbRTyWWE57BPhy9
"""


def start_here(title: str) -> str:
    return f"""TIME TO INDEX - LAUNCH PACK
Before posting, check the numbers are still current:
  cd ~/Downloads/time-to-index && python3 launch/check_claims.py
Release v0.1.0 is out and the site is live. hub.html shows everything on one page.

1. REPO SETTINGS (2 min): 6-repo-settings/settings.txt

2. SUBSTACK (post first; everything else links to it)
   Title: {title}
   Open 1-substack/essay.html in a browser, select all, paste into a new post.
   Upload the 4 PNGs from 1-substack/ where the image markers are.
   Embed 2-video/time-to-index-short.mp4 under the playground link near the top.

3. VIDEO: 2-video/time-to-index-short.mp4 (1:31). Thumbnail: 2-video/thumbnail.png.
   Put the Substack link in the description.

4. LINKEDIN: paste 3-linkedin/linkedin.txt and attach the video.

5. X: 4-x/x-thread.txt has 21 posts, in order. Attach the video to post 1.

6. Send Claude the Substack link so it can be added to the README and playground.

Links used in the posts:
  Playground  https://abhid1234.github.io/time-to-index/playground.html
  Dashboard   https://abhid1234.github.io/time-to-index/
  Code        https://github.com/abhid1234/time-to-index
  Release     https://github.com/abhid1234/time-to-index/releases/tag/v0.1.0
"""


def main() -> None:
    if PACK.exists():
        shutil.rmtree(PACK)
    copies = {
        "hub.html": HERE / "hub.html",
        "1-substack/essay.html": HERE / "essay.html",
        "1-substack/long-version-blog.html": HERE / "blog.html",
        "2-video/time-to-index-short.mp4": REPO / "media" / "time-to-index-short.mp4",
        "2-video/thumbnail.png": HERE / "thumbnail.png",
        "4-x/x-thread.txt": HERE / "x-thread.md",
        "6-repo-settings/social-preview.png": REPO / "docs" / "og.png",
    }
    for name in ("absent-vs-stale", "architecture", "the-catch", "by-source"):
        copies[f"1-substack/{name}.png"] = HERE / "diagrams" / f"{name}.png"
    for dst, src in copies.items():
        (PACK / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, PACK / dst)
    linkedin = (HERE / "linkedin.md").read_text().split("\n", 2)[2]   # drop the title line
    (PACK / "3-linkedin").mkdir(exist_ok=True)
    (PACK / "3-linkedin" / "linkedin.txt").write_text(linkedin)
    (PACK / "5-playground").mkdir(exist_ok=True)
    (PACK / "5-playground" / "README.txt").write_text(PLAYGROUND)
    (PACK / "6-repo-settings" / "settings.txt").write_text(SETTINGS)
    title = (HERE / "essay.md").read_text().split("\n", 1)[0].lstrip("# ").strip()
    (PACK / "START-HERE.txt").write_text(start_here(title))
    n = sum(1 for p in PACK.rglob("*") if p.is_file())
    print(f"wrote {PACK}  ({n} files)")


if __name__ == "__main__":
    main()
