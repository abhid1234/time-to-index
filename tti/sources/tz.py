"""The one place a named time zone is constructed.

`zoneinfo.ZoneInfo("America/New_York")` needs an IANA database: the system's,
or the `tzdata` package. A slim container image has neither. Constructing the
zone at module import time meant that on such a box importing `tti.sources`
raised, `tti.cli` imports `tti.sources`, and so every command -- `tti
--version` included -- died with a ZoneInfoNotFoundError before printing a
line. The zone is now built on first use, and a missing database is a
per-subject collector error that names the fix, not a crash.
"""
from __future__ import annotations

from functools import cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@cache
def eastern() -> ZoneInfo:
    try:
        return ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(
            "no IANA time zone database on this system; `pip install tzdata` "
            "(it is a declared dependency, so a fresh install has it)") from exc
