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
import contextlib
import datetime as dt
import pathlib
import sys
import time
import urllib.parse

from . import __version__, config, providers, report, sources
from .budget import Budget, unit_cost, utc_day
from .grader import grade
from .ledger import Ledger
from .metrics import (
    ProviderScore,
    fmt_duration,
    logrank,
    observations,
    recall_by_render,
    score,
    staleness_by_rung,
)
from .models import ERROR, SKIPPED
from .scheduler import _count_results, discover, run_due


def _ledger(args) -> Ledger:
    return Ledger(pathlib.Path(args.run_dir) if args.run_dir else None)


ROOT = pathlib.Path(__file__).resolve().parent.parent


def _out_dir(args) -> pathlib.Path:
    """Where rendered pages go.

    Defaults to the repo's docs/ so `tti report` publishes where GitHub Pages
    looks. Overridable because a command that can only write into its own
    source tree is a command the test suite has to either skip or let dirty
    the working copy, and both are worse than a flag.
    """
    d = pathlib.Path(getattr(args, "out_dir", None) or (ROOT / "docs"))
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------

def cmd_doctor(args) -> int:
    # Config first: every check below reads it, and a run that starts from a
    # file nobody validated can be wrong in ways no probe would reveal.
    problems = config.check_all()
    if problems:
        print("configuration")
        for pr in problems:
            print(f"  ✗ {pr}")
        print("\nFix these before anything else. Nothing below is meaningful while")
        print("the configuration is not.")
        return 2
    print("configuration  ✓ all files valid")

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
    est = 0.0
    unpriced: set[str] = set()
    for pr in due:
        try:
            est += unit_cost(pr.provider, pr.mode)
        except config.ConfigError:
            unpriced.add(f"{pr.provider}/{pr.mode}")
    if due:
        print(f"due cost  ${est:.4f} to clear the {len(due)} probes due now")
    if unpriced:
        print(f"  ! {len(unpriced)} arm(s) in the ledger are not in "
              f"providers.yaml: {', '.join(sorted(unpriced))}")
        print("    Their probes cannot be priced and will be refused by the cap.")

    bad = led.integrity()
    if bad:
        print("\nledger integrity")
        for fname, counts in sorted(bad.items()):
            parts = []
            if counts["unparseable"]:
                parts.append(f"{counts['unparseable']} unparseable "
                             f"(a torn write, usually the last line)")
            if counts["wrong_shape"]:
                parts.append(f"{counts['wrong_shape']} wrong shape "
                             f"(an older schema)")
            print(f"  ! {fname}: {', '.join(parts)} of {counts['total']} records")
        print("  These are skipped, not fatal — one interrupted write must not make")
        print("  a month of collection unreadable. But they are records that no")
        print("  longer count, so every rate computed from this ledger is over a")
        print("  smaller denominator than the file length suggests.")
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


def cmd_crawlability(args) -> int:
    """Can an AI agent read this page?

    Standalone: it needs no ledger, no keys, and no run. Point it at a URL
    and it answers the two questions that decide whether a page enters an AI
    system at all -- is the content in the served HTML, and is the crawler
    allowed to fetch it.
    """
    import json as _json
    import urllib.parse

    from . import framework as fw
    from . import http as _http

    _http.set_retry_ceiling(1)
    out_rows = []
    for url in args.urls:
        row = {"url": url}
        try:
            resp = _http.raw_get(url, timeout=25, headers={
                "Accept": "text/html,application/xhtml+xml"})
            html = resp.text
            if resp.status_code != 200:
                raise _http.HttpError(
                    f"HTTP {resp.status_code} — a non-200 is not a verdict about "
                    f"the site's rendering")
        except Exception as exc:  # noqa: BLE001
            row["error"] = str(exc)[:200]
            out_rows.append(row)
            if not args.json:
                print(f"\n{url}\n  could not fetch: {row['error'][:100]}")
            continue

        prof = fw.profile(html)
        verdict, why = fw.VERDICTS[prof.posture]
        row.update({"framework": prof.framework, "posture": prof.posture,
                    "verdict": verdict, "bytes": prof.bytes_total,
                    "visible_chars": prof.visible_chars,
                    "text_ratio": round(prof.text_ratio, 5),
                    "evidence": prof.evidence})

        parts = urllib.parse.urlsplit(url)
        robots = ""
        with contextlib.suppress(Exception):
            robots = _http.get_text(f"{parts.scheme}://{parts.netloc}/robots.txt",
                                    timeout=15, retries=0)
        matrix = fw.robots_matrix(robots, url) if robots else {}
        row["robots"] = matrix
        blocked = [a for a, ok in matrix.items() if ok is False]

        if args.find:
            in_bytes, in_text = fw.finds_token(html, args.find)
            row["find"] = {"token": args.find, "in_bytes": in_bytes,
                           "in_visible_text": in_text}

        out_rows.append(row)
        if args.json:
            continue

        print(f"\n{url}")
        print(f"  {prof.summary()}")
        if prof.evidence:
            print(f"  detected by: {', '.join(prof.evidence[:3])}")
        print(f"  verdict: {verdict.upper()} — {why}")
        if args.find:
            f = row["find"]
            if f["in_visible_text"]:
                print(f"  '{args.find}' is in the readable HTML.")
            elif f["in_bytes"]:
                print(f"  '{args.find}' is in the served bytes but NOT in the "
                      f"readable HTML — it is inside a script or data payload. "
                      f"Whether an agent finds it depends on that agent's extractor.")
            else:
                print(f"  '{args.find}' is not in the served bytes at all. "
                      f"Nothing that does not run JavaScript can find it here.")
        llms = ""
        with contextlib.suppress(Exception):
            llms = _http.get_text(fw.llms_txt_url(url), timeout=10, retries=0)
        if llms and len(llms) > 40:
            info = fw.summarise_llms_txt(llms)
            row["llms_txt"] = info
            print(f"  llms.txt: present — {info['bytes']:,} bytes, "
                  f"{info['sections']} sections, {info['links']} links"
                  + (f", titled {info['title'][:40]!r}" if info["title"] else ""))
            print("    A deliberate statement that the site wants to be read. Reported,")
            print("    not scored — the convention is too young to grade against.")
        else:
            row["llms_txt"] = None

        if not robots:
            print("  robots.txt: not readable — no crawler policy could be checked")
        elif blocked:
            print(f"  robots.txt blocks {len(blocked)} of {len(matrix)} AI agents:")
            for a in blocked:
                print(f"      {a:22s} {fw.AI_AGENTS[a]}")
        else:
            print(f"  robots.txt allows all {len(matrix)} AI agents checked")

    if args.json:
        print(_json.dumps(out_rows, indent=2))
    _http.set_retry_ceiling(None)
    return 0


def cmd_routes(args) -> int:
    """Sample a site's own sitemap and profile the routes it declares.

    One page is enough to prove a failure exists and not enough to describe a
    site. Marketing pages are almost always server-rendered; the interesting
    failures are on detail pages.
    """
    from . import routes as rt
    from . import survey as sv_mod

    for site in args.sites:
        rs = rt.sample(site, args.sample)
        print(f"\n{rs.site}")
        if not rs.ok:
            print(f"  {rs.note or 'no routes discovered'}")
            continue
        print(f"  {rs.discovered:,} routes declared in "
              f"{len(rs.sitemap_urls)} sitemap(s); sampling {len(rs.sampled)} "
              f"evenly across the sorted list")

        sv = sv_mod.run([(u, "route") for u in rs.sampled],
                        workers=args.workers, repeat=args.repeat)
        if sv.intercepted:
            print(f"  ! {len(sv.intercepted)} of {len(rs.sampled)} sampled routes "
                  f"returned a body identical to another route's.")
            print("    One page served for many is a challenge, block or proxy —")
            print("    not a rendering posture. Those routes are excluded.")
        hit, n = sv.readable_rate()
        if not n:
            print("  no route could be judged — fetches failed, disagreed, or all")
            print("  returned the same intercepted body")
            continue
        for r in sorted(sv.usable, key=lambda r: r.prof.text_ratio):
            mark = " " if r.readable else "!"
            path = urllib.parse.urlsplit(r.url).path or "/"
            print(f"   {mark} {r.prof.text_ratio*100:5.2f}%  "
                  f"{r.prof.visible_chars:>7,}c  {r.prof.posture:15s} {path[:52]}")
        share = hit / n
        print(f"  {hit}/{n} sampled routes readable ({share*100:.0f}%)")
        if share == 1.0:
            print("  Uniformly readable across the sample.")
        elif share == 0.0:
            print("  No sampled route was readable. This is a site-wide posture,")
            print("  not one bad page.")
        else:
            print("  Mixed. A site-level claim either way would be wrong — the")
            print("  readable routes and the unreadable ones are different pages,")
            print("  and only the second kind is actionable.")
    return 0


def cmd_watch(args) -> int:
    """Record a survey into a ledger, or report how postures have moved.

    A single scan says a page is unreadable today. It cannot say the page used
    to be readable, which is the actionable statement: nobody decides to
    become invisible to agents, they ship a refactor and no signal turns red.
    """
    from . import survey as sv_mod
    from . import watch as w

    run_dir = pathlib.Path(args.run_dir) if args.run_dir else config.RUNS
    hist = w.history(run_dir)

    if not args.report:
        targets = [(u, "cli") for u in args.urls] if args.urls else None
        sv = sv_mod.run(targets, workers=args.workers, repeat=args.repeat)
        n = w.record(sv, run_dir)
        hit, judged = sv.readable_rate()
        print(f"recorded {n} observations · {hit}/{judged} readable this run")
        hist = w.history(run_dir)

    cov = w.coverage(hist)
    if not cov.runs:
        print("no history yet — run `tti watch` at least twice, days apart")
        return 1

    print(f"\n{cov.urls} URLs · {cov.runs} runs · {cov.span_days:.1f} days of history "
          f"· {cov.judged_rate*100:.0f}% of observations judged")
    if cov.runs < 2:
        print("  One run is not a series. Nothing can be said about change yet.")
        return 0
    if cov.span_days < 1:
        print("  Under a day of history. Sites redeploy on the order of days, so")
        print("  'nothing changed' here is a statement about the window, not the web.")

    ch = w.changes(hist)
    if not ch:
        print("\nNo posture changed between judged observations.")
    else:
        worse = [c for c in ch if c.worsened]
        print(f"\n{len(ch)} change(s), {len(worse)} of them regressions:")
        for c in ch:
            mark = "!" if c.worsened else " "
            when = dt.datetime.fromtimestamp(c.at, dt.timezone.utc).strftime("%Y-%m-%d")
            print(f" {mark} {when}  {c.url[8:60]:52s} {c.describe()}")
        if worse:
            print("\n  Each regression shipped in a routine change. No build check, no")
            print("  deploy gate and no dashboard turns red when a route stops being")
            print("  readable, which is why these are only visible in hindsight.")

    if cov.never_judged:
        print(f"\n{len(cov.never_judged)} URL(s) were never judged in any run and "
              f"contribute nothing:")
        for u in cov.never_judged[:8]:
            print(f"  {u}")
    return 0


def cmd_survey(args) -> int:
    """Scan a corpus of pages and report how much of it an agent can read.

    Needs no keys and no ledger. The output is about the web, not about any
    provider, which is the half of this project a site owner can act on.
    """
    import json as _json

    from . import survey as sv_mod

    targets = None
    if args.urls:
        targets = [(u, "cli") for u in args.urls]
    sv = sv_mod.run(targets, workers=args.workers, repeat=args.repeat)

    if args.json:
        print(_json.dumps([{
            "url": r.url, "category": r.category, "status": r.status,
            "usable": r.usable, "readable": r.readable, "verdict": r.verdict,
            "framework": r.prof.framework if r.prof else None,
            "posture": r.prof.posture if r.prof else None,
            "visible_chars": r.prof.visible_chars if r.prof else 0,
            "bytes": r.prof.bytes_total if r.prof else 0,
            "text_ratio": round(r.prof.text_ratio, 5) if r.prof else 0,
            "robots_blocked": r.robots_blocked, "error": r.error,
        } for r in sorted(sv.results, key=lambda r: r.url)], indent=2))
        return 0

    hit, n = sv.readable_rate()
    meta = sv.metadata_only()
    print(f"{hit} of {n} pages readable without executing JavaScript"
          + (f" · {len(meta)} metadata-only" if meta else "")
          + (f" · {len(sv.intercepted)} intercepted" if sv.intercepted else "")
          + (f" · {len(sv.unstable)} unstable" if sv.unstable else "")
          + (f" · {len(sv.unreachable) - len(sv.unstable)} unreachable"
             if len(sv.unreachable) > len(sv.unstable) else ""))

    if n:
        print()
        for r in sorted(sv.usable, key=lambda r: r.prof.text_ratio):
            mark = " " if r.readable else "!"
            blocked = f"  robots blocks {len(r.robots_blocked)}" if r.robots_blocked else ""
            print(f" {mark} {r.prof.text_ratio*100:5.2f}%  "
                  f"{r.prof.visible_chars:>7,}c  {r.prof.framework:11s} "
                  f"{r.prof.posture:15s} {r.url[8:58]}{blocked}")

        print("\nby category")
        for cat, (h, t) in sv.by_category().items():
            print(f"  {cat:20s} {h}/{t} readable")

        empty = sv.open_and_empty()
        partial = [r for r in sv.open_but_unreadable() if r not in empty]
        if empty:
            print(f"\n{len(empty)} page(s) allow every AI crawler in robots.txt and "
                  f"ship them nothing at all — no readable body, no metadata:")
            for r in empty:
                print(f"  {r.url}  ({r.prof.visible_chars} visible chars)")
            print("  Nobody chose this. It falls out of a rendering default, and the")
            print("  robots.txt records that the team wanted the opposite.")
        if partial:
            print(f"\n{len(partial)} more allow every AI crawler and ship metadata "
                  f"only — a summary, not the content:")
            for r in partial:
                print(f"  {r.url}")

    if meta:
        print(f"\n{len(meta)} page(s) ship readable metadata over an unreadable body:")
        for r in meta:
            st = r.prof.structured
            print(f"  {r.url[8:56]:50s} JSON-LD {st.jsonld_chars}c "
                  f"{st.jsonld_types or ''}")
        print("  An agent learns what the page is about. It does not learn what the")
        print("  page says, which is usually the fact it was sent there for.")

    if sv.unstable:
        print(f"\n{len(sv.unstable)} target(s) gave different answers across repeat "
              f"fetches and were excluded:")
        for r in sv.unstable[:10]:
            print(f"  {r.url[8:56]:50s} {' / '.join(r.postures_seen)}")

    if sv.unreachable and args.verbose:
        print(f"\nnot judged ({len(sv.unreachable)}):")
        for r in sv.unreachable[:24]:
            print(f"  {r.url[:58]:60s} {r.why_unusable[:52]}")
    return 0


def cmd_forecast(args) -> int:
    """Days-to-signal, from how often the watchlist has actually shipped."""
    from . import forecast as fc_mod

    fc = fc_mod.run(args.sources or None)
    ok, bad = fc.readable, [r for r in fc.rows if r.error]
    print(f"{len(ok)} subjects readable over the last {fc.window_days} days"
          + (f" · {len(bad)} unreachable" if bad else ""))
    print(f"observed rate   {fc.per_day:6.1f} events/day")
    print(f"  of which can measure staleness "
          f"{fc.superseding_per_day:.1f}/day (npm, pypi, releases, filings)")
    top, eff = fc.concentration()
    if top == top:
        flag = "  <-- one subject dominates the corpus" if top > 0.10 else ""
        print(f"concentration   top subject {top:5.1%} · "
              f"{eff:.0f} effective subjects{flag}")

    for name, why in fc_mod.UNBOUNDED.items():
        if name in (args.sources or config.settings().get("sources", [])):
            print(f"  + {name}: {why}")

    print(f"\n{'to detect a hazard ratio of':32s} {'events':>7s} {'days':>7s}")
    for hr in (2.0, 1.5, 1.2):
        d = fc.days_for(hr)
        need = fc_mod.events_for_power(hr)
        print(f"{'  ' + str(hr):32s} {need:7.0f} {('—' if d is None else f'{d:.0f}'):>7s}")

    quiet = fc.quiet()
    if quiet:
        print(f"\n{len(quiet)} subjects shipped nothing in {fc.window_days} days and are "
              f"pure cost:")
        print("  " + ", ".join(f"{r.subject}" for r in quiet[:16]))
        print("  Each still costs one poll per cycle. Drop them or accept the noise.")

    busiest = sorted(ok, key=lambda r: -r.releases)[:8]
    if busiest and busiest[0].releases:
        print("\nbusiest subjects:")
        for r in busiest:
            print(f"  {r.source:14s} {r.subject:22s} {r.releases:3d}  "
                  f"({r.per_day*7:.1f}/wk)")

    if bad:
        print(f"\n{len(bad)} unreachable — this forecast is a lower bound:")
        for r in bad[:5]:
            print(f"  {r.source:14s} {r.subject:22s} {r.error[:60]}")
    return 0


def cmd_placeholder(args) -> int:
    out = _out_dir(args) / "index.html"
    out.write_text(report.placeholder_page(), encoding="utf-8")
    print(f"wrote {out} — replaced by `tti report` on the first run")
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
    out = _out_dir(args) / "demo.html"
    lines = demo_mod.render(pathlib.Path(tempfile.mkdtemp()), out, config.ladder())
    print(f"wrote {out}  (synthetic — not a result about any product)")
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

    out_dir = _out_dir(args)
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

    render_table = {f"{sc.provider}/{sc.mode}":
                    recall_by_render(events, results, sc.provider, sc.mode)
                    for sc in scores}
    render_table = {k: v for k, v in render_table.items() if v}

    html = report.full_page(
        report.dashboard_html(scores, events, results, by_class, pairs, powers,
                              stale_series, sens_rows, render_table or None))
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    results_md = (out_dir.parent / "RESULTS.md" if out_dir.name == "docs"
                  else out_dir / "RESULTS.md")
    results_md.write_text(
        "# Results\n\n" + report.summary_md(scores, events, results) + "\n",
        encoding="utf-8")
    print(f"wrote {out_dir / 'index.html'} ({len(html)//1024}KB) and {results_md}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tti", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"tti {__version__}")
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
    rp = sub.add_parser("report", help="write RESULTS.md and docs/index.html")
    rp.add_argument("--out-dir", help="where to write rendered pages "
                    "(default: the repo's docs/)")
    rp.set_defaults(fn=cmd_report)
    dm = sub.add_parser("demo", help="render docs/demo.html from a synthetic run")
    dm.add_argument("--out-dir", help="where to write the page")
    dm.set_defaults(fn=cmd_demo)
    ph = sub.add_parser("placeholder", help="write the pre-run docs/index.html")
    ph.add_argument("--out-dir", help="where to write the page")
    ph.set_defaults(fn=cmd_placeholder)
    cw = sub.add_parser("crawlability",
                        help="can an AI agent read this page? (no keys, no ledger)")
    cw.add_argument("urls", nargs="+", help="one or more page URLs")
    cw.add_argument("--find", help="check whether this exact string is agent-visible")
    cw.add_argument("--json", action="store_true", help="machine-readable output")
    cw.set_defaults(fn=cmd_crawlability)

    rt = sub.add_parser("routes",
                        help="sample a site's sitemap and profile its routes")
    rt.add_argument("sites", nargs="+", help="site root, e.g. https://example.com")
    rt.add_argument("--sample", type=int, default=8, help="routes to sample (default 8)")
    rt.add_argument("--repeat", type=int, default=2,
                    help="fetches per route; a verdict needs them to agree")
    rt.add_argument("--workers", type=int, default=6)
    rt.set_defaults(fn=cmd_routes)

    wt = sub.add_parser("watch",
                        help="record crawlability over time and report what moved")
    wt.add_argument("urls", nargs="*", help="URLs to record (default: data/corpus.yaml)")
    wt.add_argument("--report", action="store_true",
                    help="only report on existing history; do not fetch")
    wt.add_argument("--repeat", type=int, default=2)
    wt.add_argument("--workers", type=int, default=12)
    wt.set_defaults(fn=cmd_watch)

    sv = sub.add_parser("survey",
                        help="how much of a corpus is readable without JavaScript?")
    sv.add_argument("urls", nargs="*", help="URLs to scan (default: data/corpus.yaml)")
    sv.add_argument("--workers", type=int, default=12)
    sv.add_argument("--repeat", type=int, default=2,
                    help="fetches per URL; a verdict needs them to agree (default 2)")
    sv.add_argument("--json", action="store_true")
    sv.add_argument("--verbose", action="store_true", help="list unreachable targets")
    sv.set_defaults(fn=cmd_survey)

    fx = sub.add_parser("forecast", help="days until this run can support a claim")
    fx.add_argument("--sources", nargs="*", help="limit to these sources")
    fx.set_defaults(fn=cmd_forecast)
    sub.add_parser("power", help="can this run support the claim it invites?"
                   ).set_defaults(fn=cmd_power)
    sub.add_parser("sensitivity", help="how much does the ranking depend on grading rules?"
                   ).set_defaults(fn=cmd_sensitivity)

    rg = sub.add_parser("regrade", help="re-grade stored payloads, no API calls")
    rg.add_argument("--write", action="store_true", help="apply the new verdicts")
    rg.set_defaults(fn=cmd_regrade)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except config.ConfigError as exc:
        # Exit 2, distinct from a command that ran and reported a problem, so
        # a cron wrapper can tell "misconfigured" from "nothing to do".
        print(f"\nconfiguration error\n  {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
