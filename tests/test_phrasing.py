"""The phrasing axis.

Two things have to hold. The variants must be real alternatives built from
the event's own metadata, and phrasing probes must not leak into the primary
metrics -- a second wording of the same event is a second observation, and
counting it as an independent event would inflate every recall and narrow
every interval.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


from tti import config, phrasing, scheduler
from tti.ledger import Ledger
from tti.metrics import intervals, observations, phrasing_agreement, score
from tti.models import ABSENT, FRESH, Event, Probe, ProbeResult


def ev(source="npm", **kw):
    base = {"source": source, "source_class": "package_registry", "subject": "next",
            "published_at": 0.0, "discovered_at": 1.0, "answer": "15.4.2",
            "predecessor": "15.4.1",
            "question": "What is the current latest published version of the npm package next?"}
    base.update(kw)
    return Event(**base)


def test_canonical_wording_is_always_index_zero():
    """A phrasing-0 probe must be identical to a run with the axis off, or
    the two are not comparable."""
    e = ev()
    assert phrasing.variants(e)[0] == e.question
    assert phrasing.variant(e, 0) == e.question


def test_variants_span_registers_and_are_distinct():
    v = phrasing.variants(ev())
    assert len(v) == 3
    assert len(set(v)) == 3
    assert all("next" in q for q in v)
    # The terse one is what a planner emits once it knows what it wants.
    assert min(len(q) for q in v) < 40


def test_templates_that_cannot_be_filled_are_skipped_not_patched():
    """A question rendered with an empty slot measures the slot."""
    bare = ev(source="edgar", meta={})          # no company/form in meta
    assert phrasing.variants(bare) == [bare.question]
    full = ev(source="edgar", meta={"company": "Apple Inc.", "form": "10-Q"})
    v = phrasing.variants(full)
    assert len(v) == 3 and all("{" not in q for q in v)


def test_unknown_source_degrades_to_the_canonical_question_only():
    assert phrasing.variants(ev(source="mystery")) == [ev(source="mystery").question]


def test_probe_id_is_unchanged_for_phrasing_zero():
    """Ledgers written before this axis existed must stay re-gradable."""
    a = Probe(event_id="e", provider="p", mode="m", rung=300, due_at=0.0)
    b = Probe(event_id="e", provider="p", mode="m", rung=300, due_at=0.0, phrasing=0)
    c = Probe(event_id="e", provider="p", mode="m", rung=300, due_at=0.0, phrasing=1)
    assert a.probe_id == b.probe_id != c.probe_id


def _r(eid, rung, verdict, ph):
    return ProbeResult(probe_id=f"{eid}{rung}{ph}", event_id=eid, provider="px",
                       mode="base", rung=rung, requested_at=float(rung),
                       lag=float(rung), verdict=verdict, phrasing=ph)


def test_phrasing_probes_do_not_leak_into_time_to_index(tmp_path):
    """The load-bearing isolation test.

    One event, indexed at the 1h rung under the canonical wording. Two extra
    wordings at that rung come back absent. Time-to-index must be unmoved:
    the event indexed once, and asking it three ways does not make it three
    events or make the arm slower.
    """
    led = Ledger(tmp_path)
    e = ev()
    led.add_events([e])
    canonical = [_r(e.event_id, 300, ABSENT, 0), _r(e.event_id, 3600, FRESH, 0)]
    extra = [_r(e.event_id, 3600, ABSENT, 1), _r(e.event_id, 3600, ABSENT, 2)]

    evs = led.events()
    base_obs = observations(evs, canonical, "px", "base")
    with_ph = observations(evs, canonical + extra, "px", "base")
    assert base_obs == with_ph

    assert intervals(evs, canonical, "px", "base") == \
        intervals(evs, canonical + extra, "px", "base")

    a = score(evs, canonical, "px", "base")
    b = score(evs, canonical + extra, "px", "base")
    assert (a.n_events, a.n_indexed, a.median_bracket) == \
        (b.n_events, b.n_indexed, b.median_bracket)
    assert b.n_events == 1        # not three


def test_agreement_counts_only_multi_wording_cells_where_something_worked():
    e = ev()
    evs = {e.event_id: e}
    # Cell probed three ways, one fresh: 1 of 3.
    cell = [_r(e.event_id, 3600, FRESH, 0), _r(e.event_id, 3600, ABSENT, 1),
            _r(e.event_id, 3600, ABSENT, 2)]
    assert phrasing_agreement(evs, cell, "px", "base") == (1, 3)

    # A cell where nothing worked is excluded: that is time-to-index's finding,
    # not a phrasing finding.
    none_worked = [_r(e.event_id, 300, ABSENT, i) for i in range(3)]
    assert phrasing_agreement(evs, none_worked, "px", "base") == (0, 0)

    # A single-wording cell is excluded too.
    assert phrasing_agreement(evs, [_r(e.event_id, 300, FRESH, 0)], "px", "base") == (0, 0)


def test_agreement_of_one_means_phrasing_insensitive():
    e = ev()
    all_fresh = [_r(e.event_id, 3600, FRESH, i) for i in range(3)]
    hits, asked = phrasing_agreement({e.event_id: e}, all_fresh, "px", "base")
    assert (hits, asked) == (3, 3)
    sc = score({e.event_id: e}, all_fresh, "px", "base")
    assert sc.phrasing_agreement[0] == 1.0


def test_scheduler_queues_extra_wordings_only_at_configured_rungs(tmp_path, monkeypatch):
    led = Ledger(tmp_path)
    now = time.time()
    e = ev(published_at=now - 10, discovered_at=now)

    class OneSource:
        name, source_class = "npm", "package_registry"
        errors, attempted, all_failed = [], 1, False
        def collect(self, seen):
            return [e]

    monkeypatch.setattr(scheduler.sources, "get", lambda n: OneSource())
    monkeypatch.setattr(scheduler.providers, "available_arms", lambda: [("px", "base")])
    monkeypatch.setitem(config._cache, "settings", {
        "sources": ["npm"], "max_detection_lag_seconds": 600,
        "ladder": [300, 3600, 86400], "origin_control": False,
        "phrasing_probe": {"enabled": True, "rungs": [3600], "variants": 3}})

    rep = scheduler.discover(led, verbose=False)
    probes = list(led.probes().values())
    assert rep.new_events == 1
    # Three ladder rungs at phrasing 0, plus two extra wordings at 3600 only.
    assert len(probes) == 5
    extra = [p for p in probes if p.phrasing]
    assert {p.rung for p in extra} == {3600}
    assert sorted(p.phrasing for p in extra) == [1, 2]


def test_phrasing_probes_are_off_by_default():
    assert not (config.settings().get("phrasing_probe") or {}).get("enabled")
