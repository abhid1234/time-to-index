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
from collections.abc import Iterator

from . import config
from .models import Event, Probe, ProbeResult, dumps


class Ledger:
    """Append-only JSONL, read defensively.

    This is designed to be written by an unattended job for weeks. A reboot,
    a full disk, or a kill during `tti probe` leaves a partially written last
    line, and the first version of this class raised JSONDecodeError from
    every read path when that happened -- so one interrupted write made the
    entire run unreadable, raw payloads included, with no way back.

    Malformed lines are therefore skipped rather than fatal, and counted
    rather than ignored. The counts surface in `tti status`, because silently
    reading 9,900 of 10,000 records is its own kind of wrong answer.
    """

    def __init__(self, root: pathlib.Path | None = None):
        self.root = pathlib.Path(root or config.RUNS)
        (self.root / "raw").mkdir(parents=True, exist_ok=True)
        self.skipped: dict[str, int] = {}
        self.shape_errors: dict[str, int] = {}
        self.duplicates = 0

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
        # If the previous write was interrupted the file ends mid-line with no
        # newline, and appending straight onto it fuses the torn fragment to
        # the new record -- destroying both. The recovery path was quietly
        # eating the data it was meant to save.
        if path.exists() and path.stat().st_size:
            with open(path, "rb") as probe:
                probe.seek(-1, os.SEEK_END)
                needs_newline = probe.read(1) != b"\n"
            if needs_newline:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write("\n")
        with open(path, "a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(dumps(r) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _read(self, path: pathlib.Path) -> Iterator[dict]:
        if not path.exists():
            return
        bad = 0
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1          # a torn write, almost always the last line
                    continue
                if not isinstance(row, dict):
                    bad += 1
                    continue
                yield row
        if bad:
            # Assigned, not accumulated: each call rescans the whole file, so
            # adding would report one torn line three times after three reads.
            self.skipped[path.name] = bad

    def _typed(self, path: pathlib.Path, ctor) -> Iterator:
        """Rows that survive JSON parsing can still be the wrong shape --
        an older schema, or a record written by a half-finished change. Those
        are skipped and counted too, rather than raising KeyError from deep
        inside a report."""
        for row in self._read(path):
            try:
                yield ctor(row)
            except (KeyError, TypeError, ValueError):
                self.shape_errors[path.name] = self.shape_errors.get(path.name, 0) + 1

    def integrity(self) -> dict[str, dict[str, int]]:
        """One authoritative scan of every ledger file.

        Returns per-file counts of `unparseable` lines (a torn write) and
        `wrong_shape` records (valid JSON that no longer matches the model,
        usually an older schema). Computed by rescanning rather than by
        reading counters, because the counters are updated by whichever
        queries happened to run and would report a number that depends on
        what the caller asked for.
        """
        from .models import Event, Probe, ProbeResult

        out: dict[str, dict[str, int]] = {}
        for path, ctor in ((self.events_path, Event.from_dict),
                           (self.probes_path, Probe.from_dict),
                           (self.results_path, ProbeResult.from_dict)):
            if not path.exists():
                continue
            unparseable = shape = total = 0
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    total += 1
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        unparseable += 1
                        continue
                    if not isinstance(row, dict):
                        unparseable += 1
                        continue
                    try:
                        ctor(row)
                    except (KeyError, TypeError, ValueError):
                        shape += 1
            if unparseable or shape:
                out[path.name] = {"unparseable": unparseable,
                                  "wrong_shape": shape, "total": total,
                                  "duplicates": 0}

        # Duplicate probe ids are a separate failure with a separate cause:
        # two runs overlapping rather than one write being interrupted.
        seen: set[str] = set()
        dupes = 0
        for row in self._read(self.results_path):
            pid = row.get("probe_id")
            if pid is None:
                continue
            if pid in seen:
                dupes += 1
            seen.add(pid)
        if dupes:
            entry = out.setdefault(self.results_path.name,
                                   {"unparseable": 0, "wrong_shape": 0,
                                    "total": len(seen) + dupes, "duplicates": 0})
            entry["duplicates"] = dupes
        return out

    # -- events ------------------------------------------------------------
    def events(self) -> dict[str, Event]:
        return {e.event_id: e
                for e in self._typed(self.events_path, Event.from_dict)}

    def add_events(self, events: list[Event]) -> list[Event]:
        known = set(self.events())
        fresh = [e for e in events if e.event_id not in known]
        self._append(self.events_path, [e.to_dict() for e in fresh])
        return fresh

    def seen_subjects(self) -> dict[tuple[str, str], str]:  # noqa: D401
        """(source, subject) -> most recent answer we recorded.

        Collectors use this as their high-water mark so a restart does not
        re-emit the whole watchlist as if everything had just been published.
        """
        out: dict[tuple[str, str], str] = {}
        for d in self._read(self.events_path):
            if "source" in d and "subject" in d and "answer" in d:
                out[(d["source"], d["subject"])] = d["answer"]
        return out

    # -- probes ------------------------------------------------------------
    def probes(self) -> dict[str, Probe]:
        return {p.probe_id: p
                for p in self._typed(self.probes_path, Probe.from_dict)}

    def add_probes(self, probes: list[Probe]) -> list[Probe]:
        known = set(self.probes())
        fresh = [p for p in probes if p.probe_id not in known]
        self._append(self.probes_path, [p.to_dict() for p in fresh])
        return fresh

    # -- results -----------------------------------------------------------
    def results(self) -> list[ProbeResult]:
        """Results, de-duplicated by probe_id, first occurrence winning.

        Two overlapping `tti probe` runs both dispatch every due probe and
        both append, so the same probe_id lands twice. Counting it twice
        inflates every rate and double-counts the spend. The lock in
        `tti.lock` stops it happening again; this keeps a ledger that already
        has it from being wrong, and `integrity()` reports how many there
        were.
        """
        seen: set[str] = set()
        out: list[ProbeResult] = []
        for r in self._typed(self.results_path, ProbeResult.from_dict):
            if r.probe_id in seen:
                self.duplicates = getattr(self, "duplicates", 0) + 1
                continue
            seen.add(r.probe_id)
            out.append(r)
        return out

    def completed_probe_ids(self) -> set[str]:
        return {d["probe_id"] for d in self._read(self.results_path)
                if "probe_id" in d}

    def add_results(self, results: list[ProbeResult]) -> None:
        self._append(self.results_path, [r.to_dict() for r in results])

    def spent_on(self, day: str) -> float:
        from .budget import utc_day
        return sum(
            float(d.get("cost_usd", 0.0))
            for d in self._read(self.results_path)
            if "requested_at" in d and utc_day(float(d["requested_at"])) == day
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
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    # -- state for the scheduler ------------------------------------------
    def resolved_fresh(self) -> set[tuple[str, str, str]]:
        """(event_id, provider, mode) triples that have already answered FRESH."""
        out = set()
        for d in self._read(self.results_path):
            if d.get("verdict") == "FRESH" and {"event_id", "provider", "mode"} <= d.keys():
                out.add((d["event_id"], d["provider"], d["mode"]))
        return out


def now() -> float:
    return time.time()
