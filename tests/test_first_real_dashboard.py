"""Four sentences the first real dashboard got wrong, on a control-only run.

Eight PyPI events, all found at rank 0 at five minutes, no provider key.
The page said 0 were confirmed retrievable within 24 hours; listed
"carry-forward: 28" as an origin outcome; RESULTS.md said 0 graded probes;
and the plan panel said six arms "produced nothing" when none had a key.
Every one was computed from provider scores, of which there were none.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import prereg
from tti.cli import main
from tti.ledger import Ledger
from tti.models import Event, ProbeResult, dumps


def _control_only(tmp_path, n_events=3):
    """A ledger shaped like the real one: FRESH at 300 s, carry-forward after."""
    led = Ledger(tmp_path)
    evs, rows = [], []
    for i in range(n_events):
        e = Event(source="pypi", source_class="package_registry", subject=f"p{i}",
                  published_at=1000.0, discovered_at=1001.0, question="q",
                  answer=f"1.{i}.0", predecessor=f"1.{i-1}.9" if i else None)
        evs.append(e)
        rows.append(ProbeResult(probe_id=f"f{i}", event_id=e.event_id, provider="origin",
                                mode="direct", rung=300, requested_at=1300.0, lag=300.0,
                                verdict="FRESH", render="server_html", raw_ref=f"raw/o/f{i}.json",
                                note="origin:found rank=0 render=server_html"))
        for rung in (900, 3600, 21600):
            rows.append(ProbeResult(probe_id=f"s{i}{rung}", event_id=e.event_id,
                                    provider="origin", mode="direct", rung=rung,
                                    requested_at=1000.0 + rung, lag=float(rung),
                                    verdict="SKIPPED", note="carry-forward: already FRESH"))
    led.add_events(evs)
    (tmp_path / "results.jsonl").write_text("".join(dumps(r.to_dict()) + "\n" for r in rows))
    return led


def _page(tmp_path):
    out = tmp_path / "site"
    out.mkdir(exist_ok=True)
    assert main(["--run-dir", str(tmp_path), "report", "--out-dir", str(out)]) == 0
    return (out / "index.html").read_text(), (out / "RESULTS.md").read_text()


def test_confirmed_within_24h_counts_control_finds_not_provider_scores(tmp_path):
    _control_only(tmp_path, n_events=3)
    page, _ = _page(tmp_path)
    assert "<b>3</b> were confirmed retrievable from their own origin" in page
    assert "<b>0</b> were confirmed retrievable" not in page


def test_carry_forward_rows_are_not_origin_outcomes(tmp_path):
    _control_only(tmp_path, n_events=3)
    page, _ = _page(tmp_path)
    assert "<td class='k'>found</td><td class='k'>3</td>" in page
    assert "carry-forward" not in page.split("<h2>The control arm</h2>")[1].split("</table>")[0]


def test_results_md_counts_control_probes_not_zero(tmp_path):
    _control_only(tmp_path, n_events=3)
    _, md = _page(tmp_path)
    assert "0 provider probes graded · 3 control probes" in md
    assert "0 graded probes" not in md


def test_plan_panel_tells_not_enabled_from_silent(tmp_path, monkeypatch, capsys):
    """No key for any provider: every declared arm is 'not enabled', none is
    'produced nothing'."""
    from tti import providers
    monkeypatch.setattr(providers, "available_arms", lambda: [])
    _control_only(tmp_path, n_events=2)
    page, md = _page(tmp_path)
    assert "not enabled in this run" in page
    assert "enabled, produced nothing" not in page
    assert "produced nothing" not in md.split("## Pre-registration")[-1]

    capsys.readouterr()  # drop the report's "wrote ..." line before parsing JSON
    assert main(["--run-dir", str(tmp_path), "score", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # control-only score carries no preregistration block by design; the
    # classification is exercised through report above and classify below.
    assert payload["arms"] == []


def test_classify_splits_silent_by_whether_the_arm_was_enabled():
    plan = prereg.parse()
    declared = [a for a in plan.arms if not a.startswith("origin/")]
    a0 = tuple(declared[0].split("/"))
    cls = prereg.classify(plan, present=[], enabled=[a0])
    assert cls.declared_but_silent == [declared[0]]
    assert cls.declared_not_enabled == sorted(declared[1:])
    # Pre-existing behaviour when nobody says what was enabled.
    legacy = prereg.classify(plan, present=[])
    assert legacy.declared_but_silent == sorted(declared)
    assert legacy.declared_not_enabled == []


def test_provider_only_panels_say_why_they_are_empty(tmp_path):
    """Screenshotting the first real page showed an empty twelve-column table,
    an empty chart, an empty estimator table, a staleness line reading
    "— of the time (0 of 0 opportunities)" and a bare heading. None of those
    is a sentence. Each panel now says the same thing, once."""
    from tti.report import NO_ARMS
    _control_only(tmp_path, n_events=2)
    page, md = _page(tmp_path)
    assert "<tbody></tbody>" not in page                 # no header-only tables
    assert page.count(NO_ARMS) >= 3                      # leaderboard, chart, estimator
    assert "No curve yet" in page
    assert "No staleness opportunities yet" in page
    assert 'class="big bad">—<' not in page and "of 0 opportunities" not in page
    assert "Per-class tables appear once" in page
    assert "needs stored raw payloads from a real run" not in page   # it has payloads; it lacks arms
    # The control panel is untouched by any of this.
    assert "<b>2</b> were confirmed retrievable" in page
