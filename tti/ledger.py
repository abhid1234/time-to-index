"""Append-only run store.

Layout under runs/:

    events.jsonl      one Event per line, never rewritten
    probes.jsonl      one Probe per line (the schedule)
    results.jsonl     one ProbeResult per line
    raw/<provider>/<probe_id>.json   verbatim provider response

The raw payloads are the point. Anyone can re-run the grader over them with
different matching rules and get a different number out of the same evidence,
which is the only way a single-author benchmark earns trust.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Iterator

from . import config
from .models import Event, Probe, ProbeResult, dumps


class Ledger:
    def __init__(self, root: pathlib.Path | None = None):
        self.root = pathlib.Path(root or config.RUNS)
        (self.root / "raw").mkdir(parents=True, exist_ok=True)

    # -- paths -------------------------------------------------------------
    @property
    def events_path(self) -> pathlib.Path:
        return self.root / "events.jsonl"

    @property
    def probes_path(self) -> pathlib.Path:
        return self.root / "probes.jsonl"

    @property
    def results_path(self) -> pathlib.Path:
        return self.root / "results.jsonl"

    # -- generic append/read ----------------------------------------------
    @staticmethod
    def _append(path: pathlib.Path, rows: list[dict]) -> None:
        if not rows:
            return
        with open(path, "a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(dumps(r) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    @staticmethod
    def _read(path: pathlib.Path) -> Iterator[dict]:
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    # -- events ------------------------------------------------------------
    def events(self) -> dict[str, Event]:
        return {d["event_id"]: Event.from_dict(d) for d in self._read(self.events_path)}

    def add_events(self, events: list[Event]) -> list[Event]:
        known = set(self.events())
        fresh = [e for e in events if e.event_id not in known]
        self._append(self.events_path, [e.to_dict() for e in fresh])
        return fresh

    def seen_subjects(self) -> dict[tuple[str, str], str]:
        """(source, subject) -> most recent answer we recorded.

        Collectors use this as their high-water mark so a restart does not
        re-emit the whole watchlist as if everything had just been published.
        """
        out: dict[tuple[str, str], str] = {}
        for d in self._read(self.events_path):
            out[(d["source"], d["subject"])] = d["answer"]
        return out

    # -- probes ------------------------------------------------------------
    def probes(self) -> dict[str, Probe]:
        return {d["probe_id"]: Probe.from_dict(d) for d in self._read(self.probes_path)}

    def add_probes(self, probes: list[Probe]) -> list[Probe]:
        known = set(self.probes())
        fresh = [p for p in probes if p.probe_id not in known]
        self._append(self.probes_path, [p.to_dict() for p in fresh])
        return fresh

    # -- results -----------------------------------------------------------
    def results(self) -> list[ProbeResult]:
        return [ProbeResult.from_dict(d) for d in self._read(self.results_path)]

    def completed_probe_ids(self) -> set[str]:
        return {d["probe_id"] for d in self._read(self.results_path)}

    def add_results(self, results: list[ProbeResult]) -> None:
        self._append(self.results_path, [r.to_dict() for r in results])

    def spent_on(self, day: str) -> float:
        from .budget import utc_day
        return sum(
            float(d.get("cost_usd", 0.0))
            for d in self._read(self.results_path)
            if utc_day(float(d["requested_at"])) == day
        )

    # -- raw payloads ------------------------------------------------------
    def store_raw(self, provider: str, probe_id: str, payload) -> str:
        d = self.root / "raw" / provider
        d.mkdir(parents=True, exist_ok=True)
        rel = f"raw/{provider}/{probe_id}.json"
        with open(self.root / rel, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        return rel

    def load_raw(self, rel: str):
        p = self.root / rel
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)

    # -- state for the scheduler ------------------------------------------
    def resolved_fresh(self) -> set[tuple[str, str, str]]:
        """(event_id, provider, mode) triples that have already answered FRESH."""
        out = set()
        for d in self._read(self.results_path):
            if d["verdict"] == "FRESH":
                out.add((d["event_id"], d["provider"], d["mode"]))
        return out


def now() -> float:
    return time.time()
