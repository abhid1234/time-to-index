"""Command line.

    tti doctor              check every source and provider is reachable
    tti discover            poll sources, enqueue probes
    tti probe [--limit N]   run probes whose due time has arrived
    tti score               print the leaderboard
    tti report              write RESULTS.md and docs/index.html
    tti regrade             re-grade stored raw payloads without new calls
    tti status              what is queued, what is due, what is spent

`discover` and `probe` are the two that run on a timer. Everything else is
read-only over the ledger, so it is safe to run at any time, including while
a probe run is in flight.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys
import time

from . import config, providers, report, sources
from .budget import Budget, utc_day, unit_cost
from .grader import grade
from .ledger import Ledger
from .metrics import (ProviderScore, fmt_duration, logrank, observations, score,
                      staleness_by_rung)
from .models import ERROR, FRESH, SKIPPED, STALE
from .scheduler import _count_results, discover, run_due


def _ledger(args) -> Ledger:
    return Ledger(pathlib.Path(args.run_dir) if args.run_dir else None)


# ---------------------------------------------------------------------------

def cmd_doctor(args) -> int:
    ua = config.contact_ua()
    if "set TTI_USER_AGENT" in ua:
        # SEC's fair-access policy and arXiv's terms both require a real
        # contact. Without one their collectors will be refused, and the
        # refusal looks like an unreachable host.
        print("  ! TTI_USER_AGENT is unset. SEC and arXiv require a real contact\n"
              "    string and will refuse requests without one.\n")
    print("sources")
    bad = 0
    from . import http as _http
    _http.set_retry_ceiling(0)      # fail fast; this is a reachability check
    for name in config.settings().get("sources", []):
        src = sources.get(name)
        src.max_subjects = args.subjects or None
        t0 = time.perf_counter()
        try:
            got = src.collect({})
            ms = (time.perf_counter() - t0) * 1000
            if src.all_failed:
                print(f"  ✗ {name:18s} unreachable ({len(src.errors)}/{src.attempted}) "
                      f"— {src.errors[0][:70]}")
                bad += 1
            else:
                note = f" [{len(src.errors)} subject errors]" if src.errors else ""
                print(f"  ✓ {name:18s} {len(got):3d}/{src.attempted} subjects "
                      f"reachable  {ms:6.0f}ms{note}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {name:18s} {type(exc).__name__}: {exc}"[:110])
            bad += 1

    print("\nproviders")
    cfg = config.providers_config()["providers"]
    for arm in config.settings().get("arms", []):
        p, m = arm["provider"], arm["mode"]
        env = cfg.get(p, {}).get("env", "?")
        arm = f"{p}/{m}"
        try:
            prov = providers.get(p)
        except KeyError:
            print(f"  ✗ {arm:18s} no adapter")
            bad += 1
            continue
        if not prov.available():
            print(f"  · {arm:18s} skipped — {env} not set")
            continue
        try:
            t0 = time.perf_counter()
            payload = prov.search("what is the latest version of the npm package next",
                                  m, max_results=3, max_chars=500)
            ms = (time.perf_counter() - t0) * 1000
            print(f"  ✓ {arm:18s} {_count_results(payload):2d} results  {ms:6.0f}ms  "
                  f"${unit_cost(p, m, 3):.4f}/call")
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {arm:18s} {type(exc).__name__}: {str(exc)[:70]}")
            bad += 1

    led = _ledger(args)
    day = utc_day(time.time())
    b = Budget(spent_today=led.spent_on(day))
    print(f"\nbudget  ${b.spent:.4f} of ${b.cap:.2f} spent on {day} "
          f"(${b.remaining():.2f} left)")
    _http.set_retry_ceiling(None)
    if bad:
        print(f"\n{bad} check(s) failed. A run with unreachable sources is a partial")
        print("run; its per-class numbers should not be read as complete.")
    return 1 if bad else 0


def cmd_discover(args) -> int:
    led = _ledger(args)
    rep = discover(led, source_names=args.sources or None)
    print(f"collected {rep.collected} · new {rep.new_events} · "
          f"dropped-late {rep.dropped_late} · probes queued {rep.probes_queued}")
    for k, v in sorted(rep.per_source.items()):
        print(f"  {k:18s} {v}")
    if rep.broken_sources:
        print(f"\n  UNREACHABLE: {', '.join(rep.broken_sources)}")
        print("  These contributed no events. A run with unreachable sources is a")
        print("  partial run; do not read its per-class numbers as complete.")
        return 2
    return 0


def cmd_probe(args) -> int:
    led = _ledger(args)
    rep = run_due(led, limit=args.limit, dry_run=args.dry_run)
    print(f"dispatched {rep.dispatched} · FRESH {rep.fresh} · STALE {rep.stale} · "
          f"ABSENT {rep.absent} · errors {rep.errors}")
    print(f"skipped: carry-forward {rep.skipped_carry} · budget {rep.skipped_budget} · "
          f"rung-slip {rep.dropped_slip}")
    print(f"spend ${rep.spend_usd:.4f} this run (cap ${rep.cap_usd:.2f}/day)")
    if rep.skipped_budget:
        print("  ! the daily cap refused probes; today's coverage is incomplete")
    return 0


def _all_scores(led: Ledger, source_class: str | None = None) -> list[ProviderScore]:
    events, results = led.events(), led.results()
    arms = sorted({(r.provider, r.mode) for r in results})
    # Bootstrap only the top-level table; the per-source-class panels have
    # too few events per cell for a resample to mean much, and computing it
    # anyway would print an interval that looks authoritative and is not.
    boot = 0 if source_class else 400
    return [score(events, results, p, m, source_class, bootstrap=boot)
            for p, m in arms]


def cmd_score(args) -> int:
    led = _ledger(args)
    scores = _all_scores(led)
    if not scores:
        print("no results yet — run `tti discover` then `tti probe`")
        return 1
    print(report.leaderboard_md(scores))
    return 0


def cmd_status(args) -> int:
    led = _ledger(args)
    events, probes = led.events(), led.probes()
    done = led.completed_probe_ids()
    now = time.time()
    pending = [p for p in probes.values() if p.probe_id not in done]
    due = [p for p in pending if p.due_at <= now]
    nxt = min((p.due_at for p in pending if p.due_at > now), default=None)
    day = utc_day(now)
    b = Budget(spent_today=led.spent_on(day))
    print(f"events    {len(events)}")
    print(f"probes    {len(probes)} total · {len(done)} done · {len(pending)} pending · "
          f"{len(due)} due now")
    if nxt:
        print(f"next due  {dt.datetime.fromtimestamp(nxt, dt.timezone.utc):%H:%M:%S UTC} "
              f"(in {fmt_duration(nxt - now)})")
    print(f"budget    ${b.spent:.4f} / ${b.cap:.2f} today")
    est = sum(unit_cost(p.provider, p.mode) for p in due)
    if due:
        print(f"due cost  ${est:.4f} to clear the {len(due)} probes due now")
    return 0


def cmd_regrade(args) -> int:
    """Re-grade every stored payload with the current rules, no API calls.

    This is the affordance that makes the published numbers checkable: if you
    think the matching rules are wrong, change grader.py, run this, and see
    how much the leaderboard actually moves.
    """
    led = _ledger(args)
    events = led.events()
    changed = 0
    rows = []
    for r in led.results():
        if r.verdict in (ERROR, SKIPPED) or not r.raw_ref:
            rows.append(r)
            continue
        payload = led.load_raw(r.raw_ref)
        ev = events.get(r.event_id)
        if payload is None or ev is None:
            rows.append(r)
            continue
        v, fh, sh, chars = grade(ev, payload)
        if v != r.verdict:
            changed += 1
            print(f"  {r.provider}/{r.mode} {ev.subject} @{r.rung}s: {r.verdict} -> {v}")
        r.verdict, r.matched_fresh, r.matched_stale, r.chars = v, fh, sh, chars
        rows.append(r)
    if args.write:
        led.results_path.write_text(
            "".join(__import__("json").dumps(x.to_dict(), sort_keys=True) + "\n"
                    for x in rows), encoding="utf-8")
        print(f"rewrote {len(rows)} results ({changed} verdicts changed)")
    else:
        print(f"{changed} of {len(rows)} verdicts would change — pass --write to apply")
    return 0


def _events_per_day(led: Ledger) -> float:
    evs = list(led.events().values())
    if len(evs) < 2:
        return 0.0
    span = max(e.published_at for e in evs) - min(e.published_at for e in evs)
    return (len(evs) / (span / 86_400.0)) if span > 3600 else 0.0


def cmd_power(args) -> int:
    """Can this run support the claim its leaderboard invites?

    Printed as its own command rather than buried in the report, because the
    honest answer early in a run is "no", and that is the moment it matters.
    """
    from .power import analyse

    led = _ledger(args)
    events, results = led.events(), led.results()
    arms = sorted({(r.provider, r.mode) for r in results if r.provider != "origin"})
    if len(arms) < 2:
        print("need at least two provider arms with results")
        return 1

    rate = _events_per_day(led)
    print(f"{len(events)} events, {rate:.1f}/day observed\n")
    hdr = f"{'comparison':38s} {'HR':>6s} {'events':>7s} {'power':>7s} {'need':>7s} {'days':>6s}  verdict"
    print(hdr)
    print("-" * len(hdr))
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            a, b = arms[i], arms[j]
            oa = observations(events, results, *a)
            ob = observations(events, results, *b)
            _, pv = logrank(oa, ob)
            r = analyse(f"{a[0]}/{a[1]}", oa, f"{b[0]}/{b[1]}", ob, pv, rate)
            hr = "—" if r.hazard_ratio != r.hazard_ratio else f"{r.hazard_ratio:.2f}"
            pw = "—" if r.power_now != r.power_now else f"{r.power_now*100:.0f}%"
            need = "—" if r.events_for_80 is None else f"{r.events_for_80:.0f}"
            days = "—" if r.days_needed is None else f"{r.days_needed:.0f}"
            print(f"{r.a + ' vs ' + r.b:38s} {hr:>6s} {r.events_observed:>7d} "
                  f"{pw:>7s} {need:>7s} {days:>6s}  {r.verdict}")
    print("\nHR > 1 means the first arm indexes faster. `need` is the Schoenfeld")
    print("event count for 80% power at the observed hazard ratio; `days` is how")
    print("much more collection that is at the current rate.")
    return 0


def cmd_sensitivity(args) -> int:
    """Re-grade stored payloads under deliberately worse rules.

    Zero API calls. If the ranking holds under every variant, say so; if a
    variant reorders it, that belongs next to the leaderboard rather than in
    a footnote.
    """
    from . import sensitivity

    led = _ledger(args)
    rows = sensitivity.run(led)
    if not rows:
        print("no results to re-grade — run `tti probe` first")
        return 1

    hdr = (f"{'rule variant':26s} {'churn':>8s} {'tau':>6s} {'medians':>8s} "
           f"{'lost':>5s}  ranking")
    print(hdr)
    print("-" * max(len(hdr), 74))
    for r in rows:
        if not r.regraded and r.name != "strict":
            print(f"{r.name:26s} {'—':>8s} {'—':>6s} {'—':>8s} {'—':>5s}  {r.note}")
            continue
        churn = f"{r.churn*100:.1f}%" if r.verdicts_total else "—"
        tau = f"{r.tau:.2f}"
        moved = " ".join(
            f"{n}{'' if r.rank_moves.get(n, 0) == 0 else f'({r.rank_moves[n]:+d})'}"
            for n in r.order)
        label = r.name + ("  (reported)" if r.name == "strict" else "")
        meds = f"{r.median_changes}/{r.n_arms}" if r.n_arms else "—"
        lost = str(r.arms_lost) if r.n_arms else "—"
        print(f"{label:26s} {churn:>8s} {tau:>6s} {meds:>8s} {lost:>5s}  {moved}")

    print()
    print(sensitivity.verdict(rows))
    print()
    print("churn = share of probe verdicts that change. tau = Kendall rank")
    print("correlation against the reported ordering. medians = arms whose median")
    print("bracket moved. lost = arms that stopped being measurable at all.")
    print()
    print("High churn with tau near 1 is the good case: the rule matters locally and")
    print("washes out in aggregate. A high `lost` count with tau near 1 is the trap —")
    print("the order survives because there is nothing left to order.")
    return 0


def cmd_demo(args) -> int:
    """Render docs/demo.html from a synthetic run.

    Deliberately never writes docs/index.html. The demo uses made-up provider
    names and a seeded generator, and it prints whether the estimator
    recovered the latencies the generator drew -- which is the only thing the
    demo is evidence of.
    """
    import tempfile
    from . import demo as demo_mod
    root = pathlib.Path(__file__).resolve().parent.parent
    out = root / "docs" / "demo.html"
    lines = demo_mod.render(pathlib.Path(tempfile.mkdtemp()), out, config.ladder())
    print(f"wrote {out.relative_to(root)}  (synthetic — not a result about any product)")
    print("estimator recovery against the generator's own draws:")
    print(lines)
    return 0 if "MISS" not in lines else 1


def cmd_report(args) -> int:
    led = _ledger(args)
    events, results = led.events(), led.results()
    scores = _all_scores(led)
    if not scores:
        print("no results yet")
        return 1

    classes = sorted({e.source_class for e in events.values()})
    by_class = {c: _all_scores(led, c) for c in classes}

    from .power import analyse
    rate = _events_per_day(led)
    pairs, powers = [], []
    arms = [(s.provider, s.mode) for s in
            sorted(scores, key=lambda s: (s.median_ttl is None, s.median_ttl or 0))
            if s.provider != "origin"]
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            a = observations(events, results, *arms[i])
            b = observations(events, results, *arms[j])
            _, p = logrank(a, b)
            na = f"{arms[i][0]}/{arms[i][1]}"
            nb = f"{arms[j][0]}/{arms[j][1]}"
            if p == p:
                pairs.append((na, nb, p))
            powers.append(analyse(na, a, nb, b, p, rate))

    root = pathlib.Path(__file__).resolve().parent.parent
    (root / "docs").mkdir(exist_ok=True)
    stale_series = [(f"{sc.provider}/{sc.mode}",
                     staleness_by_rung(events, results, sc.provider, sc.mode))
                    for sc in sorted(scores, key=lambda s: (s.median_ttl is None,
                                                            s.median_ttl or 0))]
    from . import sensitivity as _sens
    try:
        sens_rows = _sens.run(led)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! sensitivity pass skipped: {exc}")
        sens_rows = []

    html = report.full_page(
        report.dashboard_html(scores, events, results, by_class, pairs, powers,
                              stale_series, sens_rows))
    (root / "docs" / "index.html").write_text(html, encoding="utf-8")
    (root / "RESULTS.md").write_text(
        "# Results\n\n" + report.summary_md(scores, events, results) + "\n",
        encoding="utf-8")
    print(f"wrote docs/index.html ({len(html)//1024}KB) and RESULTS.md")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tti", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", help="ledger directory (default: ./runs)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    doc = sub.add_parser("doctor", help="check sources and providers are reachable")
    doc.add_argument("--subjects", type=int, default=2,
                     help="subjects to poll per source (default 2; 0 for all)")
    doc.set_defaults(fn=cmd_doctor)

    d = sub.add_parser("discover", help="poll sources and enqueue probes")
    d.add_argument("--sources", nargs="*", help="limit to these sources")
    d.set_defaults(fn=cmd_discover)

    p = sub.add_parser("probe", help="run probes that are due")
    p.add_argument("--limit", type=int, help="cap probes this run")
    p.add_argument("--dry-run", action="store_true", help="print, do not call")
    p.set_defaults(fn=cmd_probe)

    sub.add_parser("score", help="print the leaderboard").set_defaults(fn=cmd_score)
    sub.add_parser("status", help="queue and budget state").set_defaults(fn=cmd_status)
    sub.add_parser("report", help="write RESULTS.md and docs/index.html"
                   ).set_defaults(fn=cmd_report)
    sub.add_parser("demo", help="render docs/demo.html from a synthetic run"
                   ).set_defaults(fn=cmd_demo)
    sub.add_parser("power", help="can this run support the claim it invites?"
                   ).set_defaults(fn=cmd_power)
    sub.add_parser("sensitivity", help="how much does the ranking depend on grading rules?"
                   ).set_defaults(fn=cmd_sensitivity)

    rg = sub.add_parser("regrade", help="re-grade stored payloads, no API calls")
    rg.add_argument("--write", action="store_true", help="apply the new verdicts")
    rg.set_defaults(fn=cmd_regrade)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
