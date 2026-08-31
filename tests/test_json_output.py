"""Machine-readable output across every reporting command.

Two things are checked for all of them at once, because both are easy to get
right for one command and forget for the next.

Strictness: `json.dumps` emits bare `NaN` and `Infinity` tokens by default.
Python reads them back happily and most other parsers reject them, so a
consumer gets either an error or a token it silently coerced. Every
non-finite value must arrive as `null`.

Refusal parity: whatever a command declines to claim in its human output, it
must decline in JSON too. A machine consumer is the one most likely to treat
a rendered number as authoritative, because nobody is reading the caveats.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from tti import demo
from tti.cli import main

LADDER = [300, 900, 3600, 21600, 86400, 259200]

# Every command that speaks JSON, and whether it needs a populated ledger.
COMMANDS = [
    (["score"], True),
    (["status"], False),
    (["power"], True),
    (["sensitivity"], True),
    (["watch", "--report"], False),
    (["verify"], False),
    (["prereg"], False),
]


def emit(capsys, tmp_path, cmd):
    rc = main(["--run-dir", str(tmp_path), *cmd, "--json"])
    raw = capsys.readouterr().out
    return rc, raw


@pytest.mark.parametrize("cmd,needs_data", COMMANDS,
                         ids=[" ".join(c) for c, _ in COMMANDS])
def test_output_is_strictly_parseable(cmd, needs_data, tmp_path, capsys):
    if needs_data:
        demo.generate(tmp_path, LADDER)
    rc, raw = emit(capsys, tmp_path, cmd)
    assert rc == 0, f"{cmd} exited {rc}"
    assert "NaN" not in raw, "bare NaN is not valid JSON for most parsers"
    assert "Infinity" not in raw
    assert isinstance(json.loads(raw), dict)


@pytest.mark.parametrize("cmd,_", COMMANDS, ids=[" ".join(c) for c, _ in COMMANDS])
def test_an_empty_ledger_yields_a_document_not_a_crash(cmd, _, tmp_path, capsys):
    """A monitoring wrapper polls from the first minute, before any data
    exists. It must get a parseable answer, not a traceback and not silence."""
    rc, raw = emit(capsys, tmp_path, cmd)
    assert rc == 0
    doc = json.loads(raw)
    assert isinstance(doc, dict)


def test_score_json_declines_the_same_things_the_table_does(tmp_path, capsys):
    demo.generate(tmp_path, LADDER)
    _, raw = emit(capsys, tmp_path, ["score"])
    arms = json.loads(raw)["arms"]
    assert arms and all(a["provider"] != "origin" for a in arms), \
        "the control arm is the yardstick, not a competitor"
    for a in arms:
        # An unreachable median is null on both ends, never a fabricated number.
        med = a["median_time_to_index"]
        assert set(med) == {"low_seconds", "high_seconds"}
        assert a["estimator_converged"] in (True, False)


def test_power_json_says_when_it_cannot_support_a_claim(tmp_path, capsys):
    demo.generate(tmp_path, LADDER)
    _, raw = emit(capsys, tmp_path, ["power"])
    doc = json.loads(raw)
    assert doc["comparisons"]
    for c in doc["comparisons"]:
        assert "verdict" in c
        assert c["events_for_80_percent"] is None or c["events_for_80_percent"] > 0


def test_sensitivity_json_marks_variants_it_could_not_evaluate(tmp_path, capsys):
    """The dangerous reading is a perfect rank correlation that only means
    nothing was re-graded."""
    demo.generate(tmp_path, LADDER)          # no raw payloads
    _, raw = emit(capsys, tmp_path, ["sensitivity"])
    variants = json.loads(raw)["variants"]
    skipped = [v for v in variants if not v["evaluated"]]
    assert skipped and all("no stored payloads" in v["note"] for v in skipped)


def test_watch_json_reports_regressions_distinctly(tmp_path, capsys):
    from tti import watch as w
    from tti.framework import SHELL, STATIC, PageProfile
    from tti.survey import SiteResult, Survey

    def snap(posture, chars, at):
        p = PageProfile(posture=posture, bytes_total=10_000, visible_chars=chars)
        w.record(Survey([SiteResult(url="https://a", status=200, prof=p)]),
                 tmp_path, now=at)

    snap(STATIC, 9000, 0.0)
    snap(SHELL, 40, 86_400.0)
    _, raw = emit(capsys, tmp_path, ["watch", "--report"])
    doc = json.loads(raw)
    assert doc["runs"] == 2
    assert len(doc["changes"]) == 1
    assert doc["changes"][0]["regression"] is True
    assert doc["changes"][0]["before"] == STATIC


def test_status_json_surfaces_ledger_damage(tmp_path, capsys):
    from tti.ledger import Ledger
    from tti.models import FRESH, Event, ProbeResult
    led = Ledger(tmp_path)
    ev = Event(source="npm", source_class="package_registry", subject="p",
               published_at=1.0, discovered_at=2.0, question="q", answer="1.0.1")
    led.add_events([ev])
    led.add_results([ProbeResult(probe_id="x", event_id=ev.event_id,
                                 provider="serper", mode="search", rung=300,
                                 requested_at=300.0, lag=300.0, verdict=FRESH)])
    with open(led.events_path, "a", encoding="utf-8") as fh:
        fh.write('{"torn": tru')
    _, raw = emit(capsys, tmp_path, ["status"])
    assert json.loads(raw)["integrity"]["events.jsonl"]["unparseable"] == 1


def _build_parser():
    """The parser `main` builds, captured without executing a command."""
    import argparse
    import contextlib
    import io

    from tti import cli

    holder: dict = {}
    real = argparse.ArgumentParser.parse_args

    def capture(self, argv=None, namespace=None):
        holder.setdefault("parser", self)
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture
    try:
        with contextlib.suppress(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main([])
    finally:
        argparse.ArgumentParser.parse_args = real
    return holder["parser"]


def _subcommands_with_json() -> set[str]:
    """Every subcommand declaring a --json flag, read from the parser itself.

    Introspected rather than listed by hand, so the coverage check cannot
    drift: a new command that grows the flag fails this file until it is
    covered.
    """
    import argparse

    found: set[str] = set()
    for action in _build_parser()._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            if any("--json" in (a.option_strings or []) for a in sub._actions):
                found.add(name)
    return found


def test_every_json_capable_command_is_covered_by_this_file():
    """Getting strictness right once and forgetting it on the next command is
    exactly how a NaN reaches a consumer, so the coverage list is checked
    against the parser rather than maintained by hand."""
    covered = {c[0] for c, _ in COMMANDS}
    # These take URLs or make live network calls; they are tested in their own
    # modules against a local fixture server instead.
    elsewhere = {"crawlability", "survey", "forecast"}
    declared = _subcommands_with_json()
    assert len(declared) >= 6, f"introspection looks broken: found {declared}"
    missing = declared - covered - elsewhere
    assert not missing, f"--json commands with no strictness test: {sorted(missing)}"


def test_the_readme_names_the_same_json_commands_the_parser_declares():
    """A hand-written sentence in the README is a claim like any other.

    "Nine commands take --json" was typed by a person reading the parser
    once. The tenth arrives, the sentence stays, and a reader who trusts it
    plans around a flag that either does not exist or was never counted.
    Both the count and the list are checked here.
    """
    import pathlib
    import re

    readme = (pathlib.Path(__file__).resolve().parent.parent / "README.md").read_text()
    # `[^.]` rather than a lazy `.` under DOTALL: the list wraps across lines,
    # and a lazy dot-all run happily swallows the paragraph after it.
    m = re.search(r"^(\w+) commands take `--json`: ([^.]+)\.", readme,
                  re.MULTILINE)
    assert m, "the README no longer states which commands take --json"

    words = {"Five": 5, "Six": 6, "Seven": 7, "Eight": 8, "Nine": 9,
             "Ten": 10, "Eleven": 11, "Twelve": 12}
    claimed_n = words.get(m.group(1))
    assert claimed_n is not None, f"unhandled number word: {m.group(1)}"
    named = set(re.findall(r"`([a-z-]+)`", m.group(2)))
    declared = _subcommands_with_json()

    assert named == declared, (
        f"README lists {sorted(named)}, parser declares {sorted(declared)}")
    assert claimed_n == len(declared), (
        f"README says {claimed_n}, parser declares {len(declared)}")
