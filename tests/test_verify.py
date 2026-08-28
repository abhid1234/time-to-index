"""`tti verify` is a claim about correctness, so the interesting tests are
the ones that break each check on purpose.

A self-check that only ever passes is worse than no self-check: it is a
green light nobody earned. Every check here is exercised twice — once clean,
once with the specific defect it exists to catch.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import verify
from tti.cli import main


def test_a_clean_installation_passes_every_check(tmp_path):
    checks = verify.run_all(tmp_path)
    assert [c.name for c in checks] == [
        "config", "estimator", "grader", "ledger", "platform"]
    bad = [(c.name, c.status, c.notes) for c in checks if c.status != verify.OK]
    assert bad == [], bad
    assert verify.worst(checks) == verify.OK


def test_an_invalid_config_fails_and_says_which_file(monkeypatch):
    from tti import config
    monkeypatch.setattr(config, "check_all",
                        lambda: ["settings.yaml: ladder must be increasing"])
    c = verify.check_config()
    assert c.status == verify.FAIL
    assert "ladder must be increasing" in c.notes[0]


def test_a_broken_estimator_is_caught_against_published_values(monkeypatch):
    """The check must be tied to the literature, not to whatever this build
    happens to compute. Perturb the estimator and it has to notice."""
    from tti import survival

    real_fit = survival.fit

    class Skewed:
        def __init__(self, inner):
            self._inner = inner
            self.dropped = inner.dropped

        def cdf_upper(self, t):
            return min(1.0, self._inner.cdf_upper(t) + 0.01)

    monkeypatch.setattr(survival, "fit", lambda obs, **kw: Skewed(real_fit(obs, **kw)))
    c = verify.check_estimator()
    assert c.status == verify.FAIL
    # It must name the disagreement between the two estimators, not merely
    # notice that something is off.
    assert [n for n in c.notes if n.startswith("S(6):") and "Turnbull" in n]


def test_a_grader_that_matches_version_prefixes_is_caught(monkeypatch):
    """The exact bug that shipped: `15.4.1` matching inside `15.4.10`."""
    from tti import grader
    from tti.models import FRESH

    real = grader.grade

    def loose(event, payload, rules=None):
        # A substring match, which is what the first implementation did.
        text = json.dumps(payload)
        if event.answer in text:
            return FRESH, [event.answer], [], len(text)
        return real(event, payload, rules)

    monkeypatch.setattr(grader, "grade", loose)
    c = verify.check_grader()
    assert c.status == verify.FAIL
    assert c.notes == ["a prefix of a longer version is not a match: "
                       "got FRESH, expected ABSENT"], c.notes


def test_a_torn_ledger_line_warns_rather_than_failing(tmp_path):
    """Skipping a damaged line loses one observation. It is worth saying and
    it is not worth refusing to report over."""
    (tmp_path / "results.jsonl").write_text(
        '{"probe_id": "a", "event_id": "e", "provider": "p", "mode": "m",\n')
    c = verify.check_ledger(tmp_path)
    assert c.status == verify.WARN
    assert "unparseable" in c.notes[0]


def test_duplicate_probe_ids_fail_because_a_reported_number_was_wrong(tmp_path):
    """Two overlapping runs double-count. Unlike a torn line, this one has
    already corrupted a rate and a spend total."""
    from tti.demo import generate

    generate(tmp_path, [300, 900, 3600])
    lines = (tmp_path / "results.jsonl").read_text().splitlines()
    assert lines, "demo produced no results to duplicate"
    with open(tmp_path / "results.jsonl", "a", encoding="utf-8") as fh:
        fh.write(lines[0] + "\n")

    c = verify.check_ledger(tmp_path)
    assert c.status == verify.FAIL
    assert "overlapped" in c.detail
    assert any("duplicate probe id" in n for n in c.notes)


def test_a_platform_without_locking_warns_about_double_spend(monkeypatch):
    from tti import lock
    monkeypatch.setattr(lock, "SUPPORTED", False)
    c = verify.check_platform()
    assert c.status == verify.WARN
    assert any("double spend" in n for n in c.notes)


def test_worst_status_is_the_one_that_governs_the_exit_code():
    mk = lambda st: verify.Check("x", st)  # noqa: E731
    assert verify.worst([mk(verify.OK), mk(verify.OK)]) == verify.OK
    assert verify.worst([mk(verify.OK), mk(verify.WARN)]) == verify.WARN
    assert verify.worst([mk(verify.WARN), mk(verify.FAIL)]) == verify.FAIL


def test_the_cli_exit_code_distinguishes_pass_warn_and_fail(tmp_path, monkeypatch, capsys):
    assert main(["--run-dir", str(tmp_path), "verify"]) == 0

    monkeypatch.setattr(verify, "check_platform",
                        lambda: verify.Check("platform", verify.WARN, "no lock"))
    assert main(["--run-dir", str(tmp_path), "verify"]) == 1

    monkeypatch.setattr(verify, "check_config",
                        lambda: verify.Check("config", verify.FAIL, "bad"))
    assert main(["--run-dir", str(tmp_path), "verify"]) == 2
    out = capsys.readouterr().out
    assert "do not publish numbers" in out


def test_the_json_form_carries_the_same_verdict(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(verify, "check_platform",
                        lambda: verify.Check("platform", verify.WARN, "no lock",
                                             ["serialise the jobs yourself"]))
    rc = main(["--run-dir", str(tmp_path), "verify", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1 and payload["status"] == "warn"
    by = {c["name"]: c for c in payload["checks"]}
    assert by["platform"]["notes"] == ["serialise the jobs yourself"]
    assert by["estimator"]["status"] == "ok"


def test_verify_never_touches_the_network(tmp_path, monkeypatch):
    """The point of this command is that it can be run anywhere, including
    the machine that has no API keys and no route to the providers."""
    from tti import http as _http

    def refuse(*a, **kw):
        raise AssertionError("verify made a network call")

    for name in ("get_json", "get_text", "get_bytes", "raw_get"):
        if hasattr(_http, name):
            monkeypatch.setattr(_http, name, refuse)
    assert verify.worst(verify.run_all(tmp_path)) == verify.OK
