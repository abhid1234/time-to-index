"""A box with no IANA time zone database must not lose the whole CLI."""
from __future__ import annotations

import importlib
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def test_importing_the_cli_does_not_build_a_time_zone():
    """Static: no source module constructs ZoneInfo at import time."""
    root = pathlib.Path(__file__).resolve().parent.parent / "tti"
    for path in root.rglob("*.py"):
        if path.name == "tz.py":
            continue
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("def ", "class ", "#", '"', "'")):
                continue
            assert "ZoneInfo(" not in line, f"{path.relative_to(root)}: {stripped}"


def test_a_missing_database_is_a_named_error_at_use_not_at_import():
    from tti.sources import tz
    tz.eastern.cache_clear()
    import zoneinfo
    real = zoneinfo.ZoneInfo
    try:
        def boom(key):
            raise zoneinfo.ZoneInfoNotFoundError(key)
        tz.ZoneInfo = boom
        try:
            tz.eastern()
        except RuntimeError as exc:
            assert "tzdata" in str(exc)
        else:
            raise AssertionError("expected a RuntimeError naming tzdata")
    finally:
        tz.ZoneInfo = real
        tz.eastern.cache_clear()
    assert tz.eastern().key == "America/New_York"


def test_the_cli_starts_with_an_empty_tz_search_path():
    """Dynamic: run `tti --version` in a subprocess whose zoneinfo cannot
    find any database (TZPATH emptied, tzdata hidden), and require it to
    print the version rather than a traceback."""
    code = (
        "import sys, types; sys.modules['tzdata'] = None\n"
        "import zoneinfo; zoneinfo.reset_tzpath(to=[])\n"
        "from tti.cli import main; sys.exit(main(['--version']))"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=str(pathlib.Path(__file__).resolve().parent.parent))
    assert r.returncode == 0, r.stderr
    assert "tti 0." in (r.stdout + r.stderr)
    importlib.invalidate_caches()
