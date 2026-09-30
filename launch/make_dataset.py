"""Build the Hugging Face dataset folder for the committed ledger.

    python launch/make_dataset.py            # -> launch/build/dataset/

The folder holds the ledger exactly as committed, the raw provider payloads,
a dataset card whose numbers are read from the ledger (not typed), and a
SHA-256 manifest. Upload it as-is:

    huggingface-cli upload abhid1234/time-to-index-ledger launch/build/dataset . --repo-type dataset
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
OUT = HERE / "build" / "dataset"
FILES = ["events.jsonl", "probes.jsonl", "results.jsonl", "seen.jsonl", "prereg.lock"]


def rows(name: str) -> list[dict]:
    text = (REPO / "ledger" / name).read_text()
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def card() -> str:
    events, results = rows("events.jsonl"), rows("results.jsonl")
    seen, dedup = set(), []
    for r in results:                           # the ledger's first-wins rule
        if r["provider"] == "origin" or r["probe_id"] in seen:
            continue
        seen.add(r["probe_id"])
        dedup.append(r)
    v = collections.Counter(r["verdict"] for r in dedup)
    graded = v["FRESH"] + v["STALE"] + v["ABSENT"]
    first = min(e["published_at"] for e in events)
    last = max(e["published_at"] for e in events)
    day = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    return f"""---
license: mit
pretty_name: Time to Index ledger
language: [en]
tags: [web-search, search-api, freshness, staleness, benchmark, llm-agents, rag, interval-censored]
size_categories: [n<1K]
configs:
  - config_name: events
    data_files: events.jsonl
  - config_name: results
    data_files: results.jsonl
  - config_name: probes
    data_files: probes.jsonl
---

# Time to Index — ledger

Every event, probe and graded answer from
[Time to Index](https://github.com/abhid1234/time-to-index), a pre-registered
benchmark that times how long a newly published fact takes to reach
web-search APIs, and separates answering **nothing** (ABSENT) from
confidently answering with **the fact that was just replaced** (STALE).

This is real measured data, not a fixture: {len(events)} events published
between {day(first)} and {day(last)}, {graded} graded provider answers
(FRESH {v['FRESH']}, STALE {v['STALE']}, ABSENT {v['ABSENT']}), plus
{v['ERROR']} failed calls kept as ERROR. It is a small, early sample; the
project README lists what can and cannot be claimed from it.

Snapshot of commit `{commit}`.

## What's inside

| file | one row per |
|---|---|
| `events.jsonl` | new fact: the question, the new answer, the answer it replaced, the publisher's timestamp (t=0) |
| `probes.jsonl` | scheduled question to one provider arm at one rung (t+5m … t+72h) |
| `results.jsonl` | graded answer, including the origin control arm (`provider: origin`) |
| `seen.jsonl` | release the collectors noticed, including ones dropped for arriving late |
| `prereg.lock` | hash of the pre-registered analysis plan |
| `raw/*.tar.gz` | verbatim provider payloads for each probe run |
| `manifest.json` | SHA-256 of every file above |

When a probe id appears more than once in `results.jsonl`, the first row is
authoritative.

## Reproduce

```bash
git clone https://github.com/abhid1234/time-to-index && cd time-to-index
pip install -e .
python -m tti verify      # offline: config, estimator, grader, ledger
python -m tti regrade     # re-grade the stored payloads under the current rules
```

## Links

- Code and method: https://github.com/abhid1234/time-to-index
- Live dashboard: https://abhid1234.github.io/time-to-index/
- Playground: https://abhid1234.github.io/time-to-index/playground.html
"""


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "raw").mkdir(parents=True)
    for name in FILES:
        shutil.copy2(REPO / "ledger" / name, OUT / name)
    for tar in sorted((REPO / "ledger" / "raw").glob("*.tar.gz")):
        shutil.copy2(tar, OUT / "raw" / tar.name)
    (OUT / "README.md").write_text(card())
    manifest = {
        str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "manifest.json"
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {OUT}  ({len(manifest)} files)")


if __name__ == "__main__":
    main()
