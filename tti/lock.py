"""One writer at a time.

Cron fires on a schedule, not on completion. The moment a provider is slow
enough that `tti probe` outlasts its interval, the next run starts while the
first is still working, and both read the same set of due probes from the
ledger. Measured: six queued probes produced twelve provider calls, six
duplicate result rows, and exactly double the spend -- with every rate
computed afterwards counting the same observation twice.

Nothing in the design prevents that. `completed_probe_ids()` is read once at
the start of a run, so two runs that start together both see an empty
completed set and both dispatch everything.

An advisory file lock fixes it. It is advisory rather than mandatory, which
is the right strength here: a second run that cannot take the lock is not
broken, it is early, and it should say so and exit zero rather than fail.

Where `fcntl` is unavailable the lock degrades to a no-op and says so at the
call site, because silently pretending to hold a lock is worse than not
having one.
"""

from __future__ import annotations

import contextlib
import os
import pathlib

try:
    import fcntl
except ImportError:      # pragma: no cover - not POSIX
    fcntl = None         # type: ignore[assignment]

SUPPORTED = fcntl is not None


class Busy(RuntimeError):
    """Another process holds the lock."""


@contextlib.contextmanager
def exclusive(run_dir: pathlib.Path, name: str = "probe"):
    """Hold an exclusive lock for the duration of the block.

    Raises `Busy` immediately rather than waiting: a probe run that queues
    behind another will find its rungs stale by the time it starts, and
    dropping them for rung slip is a worse outcome than not running at all.
    """
    run_dir = pathlib.Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f".{name}.lock"

    if not SUPPORTED:     # pragma: no cover - not POSIX
        yield None
        return

    with open(path, "a+") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.seek(0)
            holder = fh.read().strip() or "another process"
            raise Busy(f"{name} is already running ({holder})") from exc
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(f"pid {os.getpid()}")
            fh.flush()
            yield fh
        finally:
            # Closing the descriptor releases the lock on its own; unlocking
            # explicitly keeps the intent visible and makes the release
            # independent of when the file object is finalised.
            with contextlib.suppress(Exception):
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
