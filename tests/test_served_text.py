"""The arms do not return the same amount of text, and the grader reads all
of it. Two things make that visible: a leaderboard column for characters read
per result, and a sensitivity variant that windows every text field to a
snippet's length. See METHODOLOGY, "The arms do not return the same amount of
text".
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import metrics
from tti.cli import main
from tti.grader import DEFAULT, VARIANTS, Rules, flatten_text, grade
from tti.models import ABSENT, FRESH, Event, ProbeResult
from tti.report import fmt_chars, leaderboard_md

WINDOW = next(r for r in VARIANTS if r.name == "snippet-window")


def _ev(event_id="e1"):
    return Event(source="npm", source_class="package_registry", subject="next",
                 published_at=0.0, discovered_at=1.0,
                 question="What is the latest version of the next npm package?",
                 answer="15.4.2", predecessor="15.4.1", event_id=event_id)


def test_snippet_window_is_a_declared_variant_with_a_conventional_length():
    assert WINDOW.max_chars_per_field == 160
    assert DEFAULT.max_chars_per_field == 0


def test_a_version_deep_in_a_long_excerpt_is_a_hit_only_when_the_excerpt_is_read():
    long_excerpt = ("Release notes. " * 40) + "Version 15.4.2 is now the latest."
    assert len(long_excerpt) > 500
    payload = {"results": [{"url": "https://x", "title": "next", "excerpts": [long_excerpt]}]}
    assert grade(_ev(), payload)[0] == FRESH
    assert grade(_ev(), payload, WINDOW)[0] == ABSENT


def test_the_window_applies_per_leaf_not_to_the_joined_text():
    # Three excerpts of 150 characters each, the token in the third. A window
    # on the joined string would cut it; a per-leaf window keeps all three.
    filler = "x" * 140
    payload = {"results": [{"excerpts": [filler, filler, "now at 15.4.2 " + filler]}]}
    assert grade(_ev(), payload, WINDOW)[0] == FRESH
    assert len(flatten_text(payload, rules=WINDOW)) <= 3 * 160 + 2


def test_short_snippets_grade_identically_under_the_window():
    payload = {"results": [{"snippet": "next 15.4.2 released"}]}
    assert grade(_ev(), payload)[:3] == grade(_ev(), payload, WINDOW)[:3]


def test_chars_per_result_is_the_median_over_graded_probes():
    events = {"e1": _ev("e1"), "e2": _ev("e2"), "e3": _ev("e3")}
    def pr(pid, eid, chars, n, verdict=FRESH):
        return ProbeResult(probe_id=pid, event_id=eid, provider="p", mode="m", rung=300,
                           requested_at=300.0, lag=300.0, verdict=verdict,
                           n_results=n, chars=chars)
    results = [
        pr("a", "e1", 1500, 5),          # 300 per result
        pr("b", "e2", 7000, 5),          # 1400
        pr("c", "e3", 800, 4),           # 200
        pr("d", "e3", 99_999, 0, ABSENT),  # no results returned: not a per-result figure
        pr("e", "e1", 1, 1, "ERROR"),    # errors are not graded text
    ]
    sc = metrics.score(events, results, "p", "m")
    assert sc.chars_per_result_p50 == 300.0


def test_no_graded_text_leaves_the_column_blank_not_zero():
    sc = metrics.score({"e1": _ev()}, [], "p", "m")
    assert math.isnan(sc.chars_per_result_p50)
    assert fmt_chars(sc.chars_per_result_p50) == "—"


def test_fmt_chars_refuses_to_render_a_non_measurement():
    assert fmt_chars(float("nan")) == "—"
    assert fmt_chars(float("inf")) == "—"
    assert fmt_chars(-1) == "—"
    assert fmt_chars(150) == "150 chars"
    assert fmt_chars(1450) == "1.4k chars"
    assert fmt_chars(12_000) == "12k chars"


def test_the_column_reaches_markdown_html_and_json(tmp_path, capsys):
    from tti import demo
    demo.generate(tmp_path, [300, 900, 3600])
    assert main(["--run-dir", str(tmp_path), "score", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    arms = payload["arms"]
    assert arms and all("chars_per_result_p50" in a for a in arms)
    assert all(isinstance(a["chars_per_result_p50"], (int, float)) or a["chars_per_result_p50"] is None
               for a in arms)

    out = tmp_path / "site"
    assert main(["--run-dir", str(tmp_path), "report", "--out", str(out)]) == 0
    html = (out / "index.html").read_text()
    md = (out / "RESULTS.md").read_text()
    assert "text served" in html and "per result" in html
    assert "| text/result |" in md


def test_leaderboard_md_carries_the_column_in_order():
    sc = metrics.ProviderScore(provider="p", mode="m", n_events=3)
    sc.chars_per_result_p50 = 1400.0
    md = leaderboard_md([sc])
    header, _, row = md.splitlines()
    cols = [c.strip() for c in header.strip("|").split("|")]
    vals = [c.strip() for c in row.strip("|").split("|")]
    assert cols.index("text/result") == vals.index("1.4k chars")
    assert Rules(max_chars_per_field=160).name == "strict"  # a window is not a new rule set by itself


def test_the_demo_page_does_not_say_zero_chars(tmp_path):
    from tti import demo
    led, _ = demo.generate(tmp_path, [300, 900, 3600])
    per_arm = {}
    for r in led.results():
        if r.provider != "origin" and r.verdict not in ("ERROR", "SKIPPED") and r.n_results:
            per_arm.setdefault(r.provider, set()).add(round(r.chars / r.n_results, -1))
    # Three arms, three distinct orders of text served, none of them zero.
    assert len(per_arm) == 3 and all(0 not in v for v in per_arm.values())
    medians = {p: sorted(v)[len(v) // 2] for p, v in per_arm.items()}
    assert medians["provider-a"] > 1000 > medians["provider-c"] > 300 > medians["provider-b"]
