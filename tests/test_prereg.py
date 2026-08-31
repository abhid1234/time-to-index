"""Pre-registration is a claim about what could not have been changed.

So the tests that matter are the ones that try to change something: reword the
plan and demand the hash hold, move a threshold and demand it break, edit the
plan after collection and demand every command say so. A lock nobody has
attacked is a lock nobody has tested.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import prereg
from tti.cli import main
from tti.models import ProbeResult, dumps

REAL = pathlib.Path(__file__).resolve().parent.parent / "docs" / "PREREGISTRATION.md"


def write(tmp_path, text: str) -> pathlib.Path:
    p = tmp_path / "PREREGISTRATION.md"
    p.write_text(text, encoding="utf-8")
    return p


def a_result(provider="exa", mode="base") -> str:
    return dumps(ProbeResult(
        probe_id="p1", event_id="e1", provider=provider, mode=mode, rung=300,
        requested_at=1.0, lag=300.0, verdict="ABSENT").to_dict())


# ---------------------------------------------------------------------------
# The shipped plan
# ---------------------------------------------------------------------------

def test_the_repository_ships_a_plan_that_parses():
    plan = prereg.parse()
    assert plan.version >= 1
    assert plan.hypotheses and plan.arms and plan.ladder
    assert len(plan.hash) == 16


def test_every_hypothesis_in_the_shipped_plan_can_come_out_false():
    """The property `parse` enforces, asserted against the real document so a
    later edit that drops a falsification condition fails here as well as at
    load time."""
    for h in prereg.parse().hypotheses:
        assert h.falsified_if.strip(), h.id
        assert h.statement.strip(), h.id


def test_the_declared_ladder_matches_the_configured_one():
    """A plan promising six rungs against a config running three would make
    every 'declared in advance' label a lie about which observations exist."""
    from tti import config
    assert prereg.parse().ladder == config.ladder()


def test_the_declared_arms_match_the_configured_arms():
    from tti import config
    configured = {f"{a['provider']}/{a['mode']}"
                  for a in config.settings().get("arms", [])}
    if config.settings().get("origin_control", True):
        configured.add("origin/direct")
    assert set(prereg.parse().arms) == configured


# ---------------------------------------------------------------------------
# What the hash must and must not notice
# ---------------------------------------------------------------------------

def test_rewording_the_prose_around_the_plan_does_not_move_the_hash(tmp_path):
    src = REAL.read_text()
    base = prereg.parse().hash
    edited = src.replace("The failure mode this guards against is not fraud.",
                         "This is not about fraud.")
    assert edited != src
    assert prereg.parse(write(tmp_path, edited)).hash == base


def test_rewrapping_a_sentence_inside_the_plan_does_not_move_the_hash(tmp_path):
    """A block scalar carries the line breaks of whatever column the author
    wrapped at. A lock that fires on re-wrapping fires on every typo fix, and
    a lock that cries wolf is not a lock."""
    src = REAL.read_text()
    base = prereg.parse().hash
    edited = src.replace(
        "  Median time from publication to first FRESH answer, per provider arm,\n"
        "  estimated by the Turnbull NPMLE over interval-censored observations and",
        "  Median time from publication to first FRESH answer, per provider arm, estimated\n"
        "  by the Turnbull NPMLE over interval-censored observations and")
    assert edited != src
    assert prereg.parse(write(tmp_path, edited)).hash == base


@pytest.mark.parametrize("find,replace,label", [
    ("threshold: p < 0.05", "threshold: p < 0.10", "a threshold moved"),
    ("  - serper/search", "  - serper/search\n  - newthing/base", "an arm added"),
    ("ladder_seconds: [300, 900, 3600, 21600, 86400, 259200]",
     "ladder_seconds: [900, 3600, 21600, 86400, 259200]", "a rung dropped"),
    ("plan_version: 1", "plan_version: 2", "the version bumped"),
])
def test_changing_the_plan_moves_the_hash(tmp_path, find, replace, label):
    src = REAL.read_text()
    assert find in src, find
    edited = src.replace(find, replace, 1)
    assert prereg.parse(write(tmp_path, edited)).hash != prereg.parse().hash, label


# ---------------------------------------------------------------------------
# What a plan must contain to be one
# ---------------------------------------------------------------------------

def test_a_hypothesis_with_no_falsification_condition_is_refused(tmp_path):
    src = REAL.read_text()
    edited = re.sub(
        r"    falsified_if: >\n      p >= 0\.05, or the estimated hazard.*?\n\n",
        "\n", src, count=1, flags=re.DOTALL)
    assert edited != src
    with pytest.raises(prereg.PreregError, match="falsified_if"):
        prereg.parse(write(tmp_path, edited))


def test_a_document_with_no_prereg_block_is_refused(tmp_path):
    with pytest.raises(prereg.PreregError, match="no ```yaml prereg block"):
        prereg.parse(write(tmp_path, "# Plan\n\nWe will be careful.\n"))


def test_a_plain_yaml_block_is_not_mistaken_for_the_plan(tmp_path):
    """The `prereg` infix is the opt-in, so a document may show YAML examples
    without one of them silently becoming the analysis plan."""
    doc = "# Plan\n\n```yaml\nplan_version: 99\narms_declared_in_advance: [a/b]\n```\n"
    with pytest.raises(prereg.PreregError, match="no ```yaml prereg block"):
        prereg.parse(write(tmp_path, doc))


@pytest.mark.parametrize("key", ["primary_endpoint", "arms_declared_in_advance",
                                 "stopping_rule", "hypotheses"])
def test_a_plan_missing_a_required_section_is_refused(tmp_path, key):
    src = REAL.read_text()
    edited = re.sub(rf"^{key}:.*?(?=^\w|\Z)", "", src, count=1,
                    flags=re.MULTILINE | re.DOTALL)
    with pytest.raises(prereg.PreregError):
        prereg.parse(write(tmp_path, edited))


def test_an_arm_that_is_not_provider_slash_mode_is_refused(tmp_path):
    src = REAL.read_text().replace("  - serper/search", "  - serper")
    with pytest.raises(prereg.PreregError, match="provider/mode"):
        prereg.parse(write(tmp_path, src))


# ---------------------------------------------------------------------------
# Classifying a run against the plan
# ---------------------------------------------------------------------------

def test_arms_split_into_declared_exploratory_and_silent():
    plan = prereg.parse()
    present = [("exa", "auto"), ("tavily", "basic"), ("mystery", "base"),
               ("origin", "direct")]
    cls = prereg.classify(plan, present)
    assert cls.declared == ["exa/auto", "tavily/basic"]
    assert cls.exploratory == ["mystery/base"]
    assert "brave/web" in cls.declared_but_silent
    # The control is declared and excluded by construction: neither a surprise
    # nor a missing result.
    assert "origin/direct" not in cls.exploratory
    assert "origin/direct" not in cls.declared_but_silent


def test_a_run_matching_the_plan_exactly_is_clean():
    plan = prereg.parse()
    present = [tuple(a.split("/")) for a in plan.arms]
    assert prereg.classify(plan, present).clean


# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------

def test_the_lock_is_written_once_and_not_overwritten(tmp_path):
    plan = prereg.parse()
    assert prereg.lock(tmp_path, plan) == plan.hash
    # A second call with a different plan must not silently re-lock: that would
    # make the lock record "whatever the plan said most recently", which is the
    # one thing it exists not to say.
    other = prereg.Plan(**{**plan.__dict__, "raw": {**plan.raw, "plan_version": 99}})
    assert other.hash != plan.hash
    assert prereg.lock(tmp_path, other) == plan.hash
    assert prereg.locked_hash(tmp_path) == plan.hash


def test_drift_is_reported_once_collection_has_started(tmp_path):
    plan = prereg.parse()
    prereg.lock(tmp_path, plan)
    moved = prereg.Plan(**{**plan.__dict__, "raw": {**plan.raw, "plan_version": 2}})
    assert prereg.status(tmp_path, moved, started=True).drifted


def test_no_drift_before_a_probe_has_been_dispatched(tmp_path):
    """Editing the plan before any data exists is writing the plan, not
    revising it in the light of results."""
    plan = prereg.parse()
    st = prereg.status(tmp_path, plan, started=False)
    assert not st.drifted and st.locked is None


def test_a_lock_file_alone_proves_collection_started(tmp_path):
    """The bug this closes: `started` is normally inferred from
    `bool(ledger.results())`, which is empty when every line of the results
    file is torn. The reader skips malformed lines by design, so the run looks
    like it never began, the drift check is skipped, and a plan edited after
    the data passes silently — exactly when ledger damage should make everyone
    more careful, not less."""
    plan = prereg.parse()
    prereg.lock(tmp_path, plan)
    moved = prereg.Plan(**{**plan.__dict__, "raw": {**plan.raw, "plan_version": 3}})
    st = prereg.status(tmp_path, moved, started=False)   # caller saw no results
    assert st.started, "the lock file is itself evidence that a probe ran"
    assert st.drifted


# ---------------------------------------------------------------------------
# Through the CLI
# ---------------------------------------------------------------------------

def test_prereg_prints_the_plan_and_exits_zero(tmp_path, capsys):
    assert main(["--run-dir", str(tmp_path), "prereg"]) == 0
    out = capsys.readouterr().out
    assert "primary endpoint" in out
    assert "falsified if" in out
    assert "no results yet" in out


def test_prereg_json_carries_the_hypotheses_and_the_lock(tmp_path, capsys):
    assert main(["--run-dir", str(tmp_path), "prereg", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["lock"]["collection_started"] is False
    assert payload["lock"]["drifted"] is False
    ids = [h["id"] for h in payload["hypotheses"]]
    assert ids == ["H1", "H2", "H3", "H4"]
    assert all(h["falsified_if"] for h in payload["hypotheses"])


def test_a_drifted_plan_makes_prereg_exit_one(tmp_path, capsys, monkeypatch):
    plan = prereg.parse()
    prereg.lock(tmp_path, plan)
    (tmp_path / "results.jsonl").write_text(a_result() + "\n")
    moved = prereg.Plan(**{**plan.__dict__, "raw": {**plan.raw, "plan_version": 7}})
    monkeypatch.setattr(prereg, "parse", lambda path=None: moved)

    assert main(["--run-dir", str(tmp_path), "prereg"]) == 1
    out = capsys.readouterr().out
    assert "CHANGED SINCE COLLECTION BEGAN" in out


def test_a_drifted_plan_makes_verify_fail(tmp_path, monkeypatch, capsys):
    plan = prereg.parse()
    prereg.lock(tmp_path, plan)
    (tmp_path / "results.jsonl").write_text(a_result() + "\n")
    moved = prereg.Plan(**{**plan.__dict__, "raw": {**plan.raw, "plan_version": 7}})
    monkeypatch.setattr(prereg, "parse", lambda path=None: moved)

    assert main(["--run-dir", str(tmp_path), "verify"]) == 2
    assert "changed after collection began" in capsys.readouterr().out


def test_an_unreadable_plan_warns_rather_than_failing_verify(tmp_path, monkeypatch, capsys):
    """A fork may run this instrument without pre-registering. Refusing to
    verify would punish the fork rather than the omission."""
    def boom(path=None):
        raise prereg.PreregError("no plan here")
    monkeypatch.setattr(prereg, "parse", boom)
    assert main(["--run-dir", str(tmp_path), "verify"]) == 1
    out = capsys.readouterr().out
    assert "no usable analysis plan" in out
    assert "exploratory by default" in out


def test_score_labels_undeclared_arms_as_exploratory(tmp_path, capsys):
    from tti import demo
    demo.generate(tmp_path, [300, 900, 3600])
    # Strip the synthetic marker so the run is treated as a real collection.
    (tmp_path / demo.DEMO_MARKER).unlink()

    assert main(["--run-dir", str(tmp_path), "score"]) == 0
    out = capsys.readouterr().out
    assert "EXPLORATORY, not pre-registered" in out
    assert "provider-a/fast" in out
    assert "Declared in the plan, produced nothing" in out
    assert "exa/auto" in out


def test_score_json_labels_each_arm_individually(tmp_path, capsys):
    from tti import demo
    demo.generate(tmp_path, [300, 900, 3600])
    (tmp_path / demo.DEMO_MARKER).unlink()

    assert main(["--run-dir", str(tmp_path), "score", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["preregistration"]["registered"] is True
    assert all(row["preregistered"] is False for row in payload["arms"])
    assert "exa/auto" in payload["preregistration"]["declared_but_silent"]


def test_a_synthetic_run_is_not_judged_against_the_plan(tmp_path, capsys):
    """The demo measures a generator whose answers are known. Reading its arms
    as five undeclared providers, and the five real ones as having failed
    everywhere, is true about the ledger and nonsense about the world."""
    from tti import demo
    demo.generate(tmp_path, [300, 900, 3600])

    assert main(["--run-dir", str(tmp_path), "score"]) == 0
    out = capsys.readouterr().out
    assert "Synthetic run" in out
    assert "EXPLORATORY" not in out
    assert "produced nothing" not in out


def test_the_dashboard_carries_the_plan_panel(tmp_path):
    from tti import demo
    demo.generate(tmp_path, [300, 900, 3600])
    (tmp_path / demo.DEMO_MARKER).unlink()
    out_dir = tmp_path / "site"
    out_dir.mkdir()

    assert main(["--run-dir", str(tmp_path), "report", "--out-dir", str(out_dir)]) == 0
    page = (out_dir / "index.html").read_text()
    assert "Exploratory, not pre-registered" in page
    assert "what was promised, and what would falsify it" in page
    assert "H1" in page and "H2" in page and "H3" in page
    assert (out_dir / "RESULTS.md").read_text().count("Pre-registration") == 1
