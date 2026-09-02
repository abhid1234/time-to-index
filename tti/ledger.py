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

import datetime as dt
import json
import os
import pathlib
import shutil
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

    @property
    def seen_path(self) -> pathlib.Path:
        return self.root / "seen.jsonl"

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

        Read from two files. Events that entered the ladder are in
        events.jsonl. Events that were collected and dropped as detected-late
        are in seen.jsonl -- they never became events, but the collector
        still needs to know it has seen that answer, or it fetches the same
        document on every poll forever. Against the live npm registry that
        was roughly a gigabyte per five-minute cycle on a stale watchlist.

        Per key, the record with the later timestamp wins, because the two
        files are appended independently and file order says nothing about
        wall-clock order between them.
        """
        best: dict[tuple[str, str], tuple[float, str]] = {}
        for path, tkey in ((self.events_path, "discovered_at"),
                           (self.seen_path, "marked_at")):
            for d in self._read(path):
                if "source" in d and "subject" in d and "answer" in d:
                    key = (d["source"], d["subject"])
                    t = d.get(tkey)
                    t = float(t) if isinstance(t, (int, float)) else 0.0
                    if key not in best or t >= best[key][0]:
                        best[key] = (t, d["answer"])
        return {k: v for k, (_, v) in best.items()}

    def mark_seen(self, events: list[Event], reason: str) -> int:
        """Record answers for events that were collected but will not be
        probed, so the collector's high-water mark advances past them.

        Only answers that would change the mark are written; on a five-minute
        cadence the same stale answer arrives 288 times a day per subject,
        and appending each one would be a log of nothing happening. Returns
        the number written.
        """
        import time as _t
        current = self.seen_subjects()
        rows = []
        now = _t.time()
        for e in events:
            if current.get((e.source, e.subject)) != e.answer:
                rows.append({"source": e.source, "subject": e.subject,
                             "answer": e.answer, "reason": reason,
                             "marked_at": now})
                current[(e.source, e.subject)] = e.answer
        if rows:
            self._append(self.seen_path, rows)
        return len(rows)

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

    def rewrite_results(self, rows: list[ProbeResult],
                        keep_backup: bool = True) -> pathlib.Path | None:
        """Replace results.jsonl atomically, keeping the previous file.

        The only destructive operation in the project, and it was the least
        protected: a direct write over the live file, so an interrupt --
        Ctrl-C, a full disk, a power loss -- truncated weeks of collected
        results with no way back. The command it backs is `tti regrade
        --write`, which is precisely what a sceptical reader runs when they
        take the README up on its invitation to re-grade the evidence. They
        would have been the one to lose it.

        Written to a sibling temp file, fsynced, then renamed over the
        original: `os.replace` is atomic on POSIX, so a reader either sees
        the whole old file or the whole new one and never a half-written
        mixture. The previous file is kept alongside with a timestamp.

        Callers must hold the probe lock. A concurrent `tti probe` appending
        between the read and the write would have its rows silently dropped,
        and no count anywhere would show it.
        """
        target = self.results_path
        backup = None
        if keep_backup and target.exists() and target.stat().st_size:
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = target.with_name(f"{target.name}.{stamp}.bak")
            shutil.copy2(target, backup)

        tmp = target.with_name(f".{target.name}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(dumps(r.to_dict()) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        # Fsync the directory too, so the rename itself survives a crash.
        dfd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
        return backup

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
