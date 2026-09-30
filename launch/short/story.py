"""The short cut's content: every scene's words, and every number read from the ledger.

Kept apart from the renderer so the words can be read and argued with on their
own. The audience is not the people who read the blog -- it is someone
scrolling with the sound off -- so each scene carries one idea in plain words,
and anything technical is either translated or left out.

Numbers are never typed here. They come out of ledger/ when the video is
rendered, so the short cannot assert last week's result.
"""
from __future__ import annotations

import collections
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]


def ledger_facts() -> dict:
    led = REPO / "ledger"
    events = {e["event_id"]: e for e in (json.loads(x) for x in
              (led / "events.jsonl").read_text().splitlines() if x.strip())}
    seen, rows = set(), []
    for line in (led / "results.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["probe_id"] in seen:
            continue
        seen.add(r["probe_id"])
        rows.append(r)

    graded = [r for r in rows if r.get("provider") != "origin"
              and r["verdict"] in ("FRESH", "STALE", "ABSENT")]

    # --- the uv catch --------------------------------------------------------
    uv = next(e for e in events.values()
              if e["subject"] == "astral-sh/uv" and e["answer"] == "0.12.15")
    uv_rows = [r for r in rows if r["event_id"] == uv["event_id"] and r["rung"] == 300]
    names = {("origin", "direct"): "The release page itself",
             ("exa", "auto"): "Exa", ("parallel", "advanced"): "Parallel · advanced",
             ("brave", "web"): "Brave", ("parallel", "fast"): "Parallel · fast"}
    order = {"origin": 0}
    uv_rows.sort(key=lambda r: (order.get(r["provider"], 1),
                                {"FRESH": 0, "STALE": 1}.get(r["verdict"], 2),
                                r["provider"]))
    catch = []
    for r in uv_rows:
        v = r["verdict"]
        catch.append({
            "who": names.get((r["provider"], r["mode"]), f'{r["provider"]} · {r["mode"]}'),
            "control": r["provider"] == "origin",
            "verdict": v,
            "said": uv["answer"] if v == "FRESH" else
                    (r["matched_stale"][0] if v == "STALE" else "—"),
            "note": {"FRESH": "current", "STALE": "out of date"}.get(v, "found nothing"),
        })
    prov = [c for c in catch if not c["control"]]

    # --- by source -----------------------------------------------------------
    by = collections.defaultdict(collections.Counter)
    for r in graded:
        by[events[r["event_id"]]["source"]][r["verdict"]] += 1
    label = {"federal_register": ("US government notices", "Federal Register"),
             "npm": ("JavaScript packages", "npm"),
             "github_release": ("Software releases", "GitHub"),
             "pypi": ("Python packages", "PyPI")}
    sources = []
    for s in sorted(by, key=lambda s: (-by[s]["FRESH"], -sum(by[s].values()))):
        c = by[s]
        plain, where = label.get(s, (s, s))
        sources.append({"plain": plain, "where": where, "fresh": c["FRESH"],
                        "stale": c["STALE"], "total": sum(c.values())})

    # --- the same arm, both ways --------------------------------------------
    arm = collections.Counter((r["provider"], r["mode"]) for r in graded
                              if r["verdict"] == "FRESH").most_common(1)[0][0]
    stale_by_arm = collections.Counter((r["provider"], r["mode"]) for r in graded
                                       if r["verdict"] == "STALE")
    arm_stale = stale_by_arm[arm]
    tied = [a for a, n in stale_by_arm.items() if n == arm_stale and a != arm]
    arm_on_uv = next(r for r in uv_rows if (r["provider"], r["mode"]) == arm)

    tests = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                           cwd=REPO, capture_output=True, text=True).stdout
    import re
    m = re.search(r"(\d+) tests? collected", tests)

    return {
        "events": len(events),
        "graded": len(graded),
        "stale_total": sum(1 for r in graded if r["verdict"] == "STALE"),
        "uv": {"version": uv["answer"], "lag": round(uv["discovered_at"] - uv["published_at"]),
               "rows": catch,
               "none_had_it": sum(1 for c in prov if c["verdict"] == "FRESH") == 0,
               "n": len(prov),
               "stale_n": sum(1 for c in prov if c["verdict"] == "STALE")},
        "sources": sources,
        "arm": names.get(arm, " · ".join(arm)),
        "arm_fresh": sum(1 for r in graded if r["verdict"] == "FRESH"
                         and (r["provider"], r["mode"]) == arm),
        "arm_stale": arm_stale,
        "arm_tied_with": [names.get(a, " · ".join(a)) for a in tied],
        "arm_uv_verdict": arm_on_uv["verdict"],
        "arm_uv_said": (arm_on_uv["matched_stale"] or ["—"])[0],
        "tests": int(m[1]) if m else None,
    }


def check(f: dict) -> None:
    """The scenes' words make claims. Refuse to render if the ledger stops backing them."""
    fr = next(s for s in f["sources"] if s["where"] == "Federal Register")
    rest = [s for s in f["sources"] if s["where"] != "Federal Register"]
    problems = []
    if not f["uv"]["none_had_it"]:
        problems.append("scene 5 says none of the indexes had uv — the ledger disagrees")
    if f["uv"]["stale_n"] != 2:
        problems.append(f'scene 5 says two gave the old version — ledger says {f["uv"]["stale_n"]}')
    if sum(s["fresh"] for s in rest) != 0:
        problems.append("scene 6 says software releases were never fresh — the ledger disagrees")
    if fr["fresh"] == 0:
        problems.append("scene 6 leads with government notices being found — none were")
    if f["arm_uv_verdict"] != "STALE":
        problems.append("scene 7 says the fastest arm was stale on uv — it was not")
    if not f["arm_tied_with"]:
        problems.append("scene 7 says 'tied for the most' — no other arm has as many")
    if problems:
        raise SystemExit("the copy no longer matches the ledger:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    f = ledger_facts()
    check(f)
    print(json.dumps(f, indent=2))
