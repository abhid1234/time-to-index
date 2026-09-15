"""Check every number the launch materials claim against the live ledger.

The run keeps collecting while the copy sits still. Between writing the blog
and publishing it the event count went from seven to eight, then to ten, then
to thirteen, and nobody would have noticed -- the number is in prose, in a
narration script and in a thread, and there is no reason any of them would
stay in step.

So each claim is declared here as a pattern plus the ledger query that settles
it, and this exits non-zero when they disagree. It does not rewrite anything:
a number that moved usually needs a sentence rewritten around it, not a digit
swapped, and a script that silently edits prose is worse than one that
complains.

Run it immediately before publishing. `--repo` points at the checkout; the
default is this file's parent, because the pack now lives inside the repo --
it used to live in a scratch directory and a container reset took the whole
thing.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ASSETS = ["blog.md", "linkedin.md", "x-thread.md", "README.md"]


def ledger_facts(repo: pathlib.Path) -> dict[str, float]:
    """Everything the copy is allowed to assert, read from the ledger."""
    led = repo / "ledger"
    events = [json.loads(x) for x in
              (led / "events.jsonl").read_text().splitlines() if x.strip()]
    results = [json.loads(x) for x in
               (led / "results.jsonl").read_text().splitlines() if x.strip()]

    prov = [r for r in results if r.get("provider") != "origin"]
    seen: set[str] = set()
    dedup = []
    for r in prov:                       # the ledger's own first-wins rule
        if r["probe_id"] in seen:
            continue
        seen.add(r["probe_id"])
        dedup.append(r)

    graded = [r for r in dedup if r["verdict"] in ("FRESH", "STALE", "ABSENT")]
    verdicts = collections.Counter(r["verdict"] for r in graded)
    errors = sum(1 for r in dedup if r["verdict"] == "ERROR")
    lags = [e["discovered_at"] - e["published_at"] for e in events]

    # The event the copy tells the story of: the first with graded provider
    # calls, found by id rather than by name so a rename cannot break it.
    ids = {r["event_id"] for r in graded}
    story = next((e for e in events if e["event_id"] in ids), None)

    # Those claims are about ONE event -- "four search indexes were asked, none
    # had it, 1.8 cents" -- so they must be checked against that event, not
    # against the whole ledger. While only one event had graded calls the two
    # were the same number; the moment a second landed this reported three
    # mismatches that were not mistakes in the prose. A checker that cries wolf
    # gets ignored on the run where it is right.
    story_calls = [r for r in graded if story and r["event_id"] == story["event_id"]]
    story_spend = sum(r.get("cost_usd") or 0.0 for r in dedup
                      if story and r["event_id"] == story["event_id"])

    stale = [r for r in graded if r["verdict"] == "STALE"]
    return {
        "events": len(events),
        "graded_provider_calls": len(story_calls),
        "graded_provider_calls_total": len(graded),
        "errors": errors,
        "arms": len({(r["provider"], r["mode"]) for r in story_calls}),
        "fresh": verdicts["FRESH"],
        "stale": verdicts["STALE"],
        "absent": verdicts["ABSENT"],
        "stale_arms": len({(r["provider"], r["mode"]) for r in stale}),
        "stale_events": len({r["event_id"] for r in stale}),
        "story_spend": round(story_spend, 4),
        "spend": round(sum(r.get("cost_usd") or 0.0 for r in dedup), 4),
        "max_detection_lag": round(max(lags)) if lags else 0,
        "span_days": round((max(e["published_at"] for e in events)
                            - min(e["published_at"] for e in events)) / 86400, 2)
                     if events else 0,
        "story_lag": round(story["discovered_at"] - story["published_at"])
                     if story else 0,
        # The second event the copy narrates, found by the subject it names
        # rather than by position, so a later event cannot silently become it.
        "uv_lag": next((round(e["discovered_at"] - e["published_at"])
                        for e in events
                        if e["subject"] == "astral-sh/uv"
                        and e["answer"] == "0.12.15"), 0),
        "story_answer": story["answer"] if story else "",
        "tests": _collected_tests(repo),
    }


def _collected_tests(repo: pathlib.Path) -> int:
    """How many tests pytest actually collects.

    The build table names a number, and that number goes up every time a test
    is added -- silently, because nothing links the table to the suite. Asking
    pytest costs a few seconds once, immediately before publishing, which is
    the only moment it matters.
    """
    import subprocess
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                         cwd=repo, capture_output=True, text=True).stdout
    m = re.search(r"(\d+) tests? collected", out)
    return int(m[1]) if m else -1


# (label, regex over the asset text, key in ledger_facts, how to read the match)
CLAIMS: list[tuple[str, str, str, str]] = [
    ("event count (digits)",
     r"\b(\d+) events? in (?:a |two |\d+ ?)(?:day|days|week|weeks)", "events", "int"),
    ("event count (words, with span)",
     r"\b([Ss]even|[Ee]ight|[Nn]ine|[Tt]en|[Ee]leven|[Tt]welve|[Tt]hirteen) events? in "
     r"(?:a |two |\d+ ?)(?:day|days|week|weeks)", "events", "word"),
    ("event count (words)",
     r"\b(seven|eight|nine|ten|eleven|twelve|thirteen) real events", "events", "word"),
    ("ledger events",
     r"the ladder has (\w+) events", "events", "word"),
    ("graded provider calls (story)",
     r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+) API calls on one package",
     "graded_provider_calls", "word"),
    ("graded provider calls (total)",
     r"and (\w+) graded provider calls", "graded_provider_calls_total", "word"),
    ("arms asked",
     r"\b(three|four|five|six|\d+) search indexes were asked", "arms", "word"),
    ("detection lag (story event)",
     r"workers-types@[\w.]+` was published\. My collector saw it (\d+) seconds later",
     "story_lag", "int"),
    ("detection lag (uv event)",
     r"released on GitHub\. My collector saw it (\d+) seconds later",
     "uv_lag", "int"),
    ("story spend", r"[Cc]ost:? (?:was )?\$?([\d.]+) cents", "story_spend_cents", "float"),
    ("stale count (words)", r"\b(two|three|four|five|six) came back STALE", "stale", "word"),
    ("stale arms", r"across (\w+) different arms", "stale_arms", "word"),
    ("test count", r"\*\*Tests\*\* \| (\d+),", "tests", "int"),
    ("test count (launch pack)", r"(\d+) tests green", "tests", "int"),
]

WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
    .split())}


def to_number(raw: str, how: str) -> float | None:
    raw = raw.strip().lower()
    if how == "int":
        return int(raw)
    if how == "float":
        return float(raw)
    if raw.isdigit():        # a digit is a digit, whatever `how` says
        return int(raw)
    if raw in WORDS:
        return WORDS[raw]
    # spoken compounds: "two hundred and twenty eight"
    parts = [WORDS[w] for w in raw.replace("hundred and", "hundred")
             .replace("-", " ").split() if w in WORDS]
    if "hundred" in raw and parts:
        return parts[0] * 100 + sum(parts[1:])
    return sum(parts) if parts else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(HERE.parent))
    args = ap.parse_args()

    facts = ledger_facts(pathlib.Path(args.repo))
    facts["spend_cents"] = round(facts["spend"] * 100, 2)
    facts["story_spend_cents"] = round(facts["story_spend"] * 100, 2)

    print("ledger says:")
    for k in ("events", "span_days", "graded_provider_calls",
              "graded_provider_calls_total", "errors", "arms", "fresh", "stale",
              "absent", "stale_arms", "stale_events", "story_spend_cents",
              "spend_cents", "story_lag", "uv_lag", "tests"):
        print(f"  {k:<28}{facts[k]}")
    print()

    bad = 0
    checked = 0
    for name in ASSETS:
        text = (HERE / name).read_text()
        for label, pattern, key, how in CLAIMS:
            for m in re.finditer(pattern, text):
                checked += 1
                got = to_number(m.group(1), how)
                want = facts[key]
                ok = got is not None and abs(got - want) < 0.51
                if not ok:
                    bad += 1
                    line = text[:m.start()].count("\n") + 1
                    print(f"  MISMATCH  {name}:{line}  {label}")
                    print(f"            says {m.group(1)!r}, ledger says {want}")
                    print(f"            > {m.group(0)}")

    # Cross-reference check. The ledger comparison above catches a number that
    # drifted from reality; it cannot catch two numbers inside one asset that
    # disagree with each other. The blog once said "eight real events" in the
    # opening and "only seven events" forty lines later -- both were true when
    # written, and together they told a reader the piece had not been read
    # through.
    NUMBERISH = re.compile(
        r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
        r"|thirteen)\b[- ](?:real |graded |provider )*(events?|API calls|search indexes)",
        re.I)
    for name in ASSETS:
        text = (HERE / name).read_text()
        found: dict[str, set[float]] = collections.defaultdict(set)
        for m in NUMBERISH.finditer(text):
            v = to_number(m.group(1), "int" if m.group(1).isdigit() else "word")
            if v is not None:
                found[m.group(2).lower().rstrip("s")].add(v)
        for noun, values in found.items():
            if len(values) > 1:
                bad += 1
                print(f"  CONTRADICTION  {name}  says {sorted(values)} "
                      f"{noun}(s) in the same document")

    # How long the build took is stated in the blog and the LinkedIn post and
    # nowhere derivable, so nothing but this stops the two drifting apart --
    # which they did: "a couple of weekends" against "a few weeks".
    spans = set()
    for name in ("blog.md", "linkedin.md"):
        for m in re.finditer(r"I spent (a [a-z ]+?) building", (HERE / name).read_text()):
            spans.add(m[1])
    checked += 1
    if len(spans) > 1:
        bad += 1
        print(f"  CONTRADICTION  build duration given as {sorted(spans)} across assets")

    # The thread is numbered by hand and described by number in README.md.
    # Adding post 12b once left the running order saying "1 -> 15" and the file
    # table saying "15 posts" -- both written before 12b existed, both still
    # true-looking. Count the posts rather than trusting the prose.
    thread = (HERE / "x-thread.md").read_text()
    n_posts = len(re.findall(r"^\*\*\d+[a-z]?/\*\*", thread, re.M))
    launch = (HERE / "README.md").read_text()
    for m in re.finditer(r"(\d+) posts\b", launch):
        checked += 1
        if int(m[1]) != n_posts:
            bad += 1
            line = launch[:m.start()].count("\n") + 1
            print(f"  MISMATCH  README.md:{line}  X post count")
            print(f"            says {m[1]}, x-thread.md has {n_posts}")

    # blog.html is *generated* from blog.md, and the generated one is what gets
    # pasted into Substack. Editing the markdown and forgetting to regenerate
    # publishes the previous draft while every check above passes, because they
    # all read the markdown.
    if (HERE / "blog.html").exists():
        import md2substack
        want = md2substack.convert((HERE / "blog.md").read_text())
        checked += 1
        if want not in (HERE / "blog.html").read_text():
            bad += 1
            print("  STALE  blog.html does not match blog.md")
            print("         run: python md2substack.py && python make_blogpage.py")

    print(f"\n{checked} claim(s) checked across {len(ASSETS)} assets, "
          f"{bad} mismatched")
    if bad:
        print("\nFix the prose, not just the digit -- a number that moved often "
              "needs the sentence around it rewritten.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
