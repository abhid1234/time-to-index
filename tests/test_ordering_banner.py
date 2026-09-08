"""A table with an order in it will be read as a ranking.

The dashboard's leaderboard is sorted, so a reader arrives at an ordering
whether or not the run supports one. The p-value panel further down answers
the question properly, but nobody reads the bottom of a page before forming
an impression of the top. So when nothing in the run separates one arm from
another, the page says so above the table.

The rule is the analysis's own, not a hand-picked sample size: a pair is
separable when its Holm-adjusted p-value clears 0.05.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti.cli import main
from tti.ledger import Ledger
from tti.models import Event, ProbeResult, dumps

BANNER = "does not support an ordering of these arms"


def _run(tmp_path, arms, *, n_events, fast_arm=None):
    """One event per subject; every arm asked at every rung.

    `fast_arm` answers FRESH at the first rung and the others never do, which
    is the shape that eventually separates arms once there are enough events.
    """
    led = Ledger(tmp_path)
    evs, rows = [], []
    for i in range(n_events):
        e = Event(source="npm", source_class="package_registry", subject=f"p{i}",
                  published_at=1000.0, discovered_at=1060.0,
                  question="q", answer=f"1.{i}.0")
        evs.append(e)
        for provider, mode in arms:
            for rung in (300, 900, 3600, 21600, 86400, 259200):
                fresh = (provider, mode) == fast_arm and rung == 300
                rows.append(ProbeResult(
                    probe_id=f"{provider}{mode}{i}{rung}", event_id=e.event_id,
                    provider=provider, mode=mode, rung=rung,
                    requested_at=1000.0 + rung, lag=float(rung),
                    verdict="FRESH" if fresh else "ABSENT",
                    matched_fresh=[f"1.{i}.0"] if fresh else [],
                    n_results=5, chars=1200, cost_usd=0.005,
                    raw_ref=f"raw/x/{provider}{i}{rung}.json"))
    led.add_events(evs)
    (tmp_path / "results.jsonl").write_text(
        "".join(dumps(r.to_dict()) + "\n" for r in rows))
    out = tmp_path / "site"
    out.mkdir(exist_ok=True)
    assert main(["--run-dir", str(tmp_path), "report", "--out-dir", str(out)]) == 0
    return (out / "index.html").read_text()


def test_a_one_event_run_says_it_cannot_rank_its_own_table(tmp_path):
    html = _run(tmp_path, [("exa", "auto"), ("brave", "web")], n_events=1)
    assert BANNER in html
    # It states the size rather than gesturing at it, so a reader can judge.
    assert "at most 1 event(s)" in html


def test_the_banner_names_how_many_comparisons_failed_to_separate(tmp_path):
    html = _run(tmp_path, [("exa", "auto"), ("brave", "web"),
                           ("parallel", "fast")], n_events=2)
    assert BANNER in html
    # Three arms is three pairs; saying so is what makes the claim checkable.
    assert "3 pairwise comparisons" in html


def test_it_points_at_the_panel_that_answers_the_question_properly(tmp_path):
    html = _run(tmp_path, [("exa", "auto"), ("brave", "web")], n_events=1)
    assert "Are the differences real" in html
    assert "tti  power" in html or "tti power" in html.replace("&nbsp;", " ")


def test_the_banner_goes_away_once_a_pair_actually_separates(tmp_path):
    """Otherwise it is decoration: a warning that never clears teaches a
    reader to ignore it, including on the run where it matters."""
    html = _run(tmp_path, [("exa", "auto"), ("brave", "web")],
                n_events=40, fast_arm=("exa", "auto"))
    assert BANNER not in html


def test_a_run_with_no_provider_arm_keeps_its_own_message(tmp_path):
    """The control-only state is a different sentence and must not be
    overwritten by this one -- there is no ordering to withhold when there
    are no arms to order."""
    led = Ledger(tmp_path)
    e = Event(source="npm", source_class="package_registry", subject="p",
              published_at=1000.0, discovered_at=1060.0, question="q",
              answer="1.0.0")
    led.add_events([e])
    (tmp_path / "results.jsonl").write_text(dumps(ProbeResult(
        probe_id="o1", event_id=e.event_id, provider="origin", mode="direct",
        rung=300, requested_at=1300.0, lag=300.0, verdict="FRESH",
        matched_fresh=["1.0.0"], raw_ref="raw/o/o1.json",
        note="origin:found rank=0 render=server_html").to_dict()) + "\n")
    out = tmp_path / "site"
    out.mkdir(exist_ok=True)
    assert main(["--run-dir", str(tmp_path), "report", "--out-dir", str(out)]) == 0
    html = (out / "index.html").read_text()
    assert "Only the origin control has results" in html
    assert BANNER not in html
