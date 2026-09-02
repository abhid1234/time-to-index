"""The plan calls the pipeline false-positive rate a secondary endpoint
"reported alongside recall rather than as a footnote". Until this panel it
was a footnote: the stdout of a separate command."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import config, decoy, demo
from tti.cli import main
from tti.report import fp_md, fp_panel_html


def test_the_dashboard_and_results_md_carry_the_false_positive_rate(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("report must not ask a registry")
    monkeypatch.setattr(decoy, "npm_absent", boom)
    demo.generate(tmp_path, config.ladder())
    out = tmp_path / "site"
    assert main(["--run-dir", str(tmp_path), "report", "--out", str(out)]) == 0
    page = (out / "index.html").read_text()
    md = (out / "RESULTS.md").read_text()
    assert "Pipeline false-positive rate" in page
    assert "provider-a/fast" in page.split("Pipeline false-positive rate")[1][:3000]
    assert "unpublished by construction" in page        # synthetic wording
    assert "## Pipeline false-positive rate" in md and "upper bound" in md
    # It sits with the leaderboard, before the survival chart.
    assert page.index("Pipeline false-positive rate") < page.index("<h2>Time to index</h2>")


def test_the_panel_states_the_verification_it_did_not_do():
    class Arm:
        provider, mode, graded, hits = "p", "m", 40, 0
    class Rep:
        arms = [Arm()]
        any_graded = True
        events_skipped = 0
        skip_reasons = {}
    html = fp_panel_html(Rep(), verified=False)
    assert "did not ask any registry" in html and "tti decoy" in html
    assert "up to 9%" in html                            # Wilson upper bound at 0/40
    assert "confirmed absent" in fp_panel_html(Rep(), verified=True)
    assert "| `p/m` | 40 | 0 |" in fp_md(Rep())


def test_the_panel_without_payloads_says_so_instead_of_a_zero():
    class Arm:
        provider, mode, graded, hits = "p", "m", 0, 0
    class Rep:
        arms = [Arm()]
        any_graded = False
        events_skipped = 0
        skip_reasons = {}
    html = fp_panel_html(Rep())
    assert "No stored payload could be re-graded" in html
    assert "0.0%" not in html
    assert fp_md(Rep()) == ""
    assert "No provider arm has results yet" in fp_panel_html(None)


def test_the_control_arm_is_a_sentence_not_a_row():
    class Arm:
        def __init__(self, provider, graded, hits=0):
            self.provider, self.mode, self.graded, self.hits = provider, "x", graded, hits
    class Rep:
        arms = [Arm("origin", 8), Arm("p", 40)]
        any_graded = True
        events_skipped = 0
        skip_reasons = {}
    html = fp_panel_html(Rep())
    assert "origin/x</td>" not in html and "<td class='k'>p/x</td>" in html
    assert "own re-grade: 0 of 8" in html and "upper bound 32%" in html
    assert "origin" not in fp_md(Rep())

    class ControlOnly(Rep):
        arms = [Arm("origin", 8)]
    html = fp_panel_html(ControlOnly())
    assert "No provider arm has results yet" in html and "0 of 8" in html
