"""Offline self-check: is this installation's arithmetic trustworthy?

Distinct from `tti doctor`, which asks whether the network is reachable.
This asks whether the thing that would be reported is correct, and it asks
it of the installation as it stands right now: the config file that was
actually edited, the ledger that was actually collected, on this machine's
Python and this machine's floating point. The test suite proves the repo is
correct at the commit CI ran; it says nothing about the copy on the box that
will produce the numbers.

Five checks, in the order in which a failure is worth knowing:

    config      the files parse and the invariants hold. A run started
                against an invalid config is a run whose spend cap and
                ladder are not what the file says.
    estimator   Turnbull reproduces published Kaplan-Meier values on the
                Freireich 1963 6-MP arm. This is the load-bearing one: the
                headline number is a survival quantile, and this ties it to
                literature rather than to arithmetic written here.
    grader      the version-boundary cases that were real bugs. `15.4.1`
                must not match inside `15.4.10`, and `v15.4.2` must match
                `15.4.2`. Both shipped wrong once.
    ledger      the files on disk parse, and no probe id appears twice.
    platform    advisory locking is available. Without it two overlapping
                cron runs double-spend and double-count, and nothing in the
                output would say so.

Nothing here touches the network, nothing costs money, and nothing writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Freireich 1963, 6-MP arm: the canonical worked example for the
# product-limit estimator. 1 marks a right-censored observation.
FREIREICH_T = [6, 6, 6, 6, 7, 9, 10, 10, 11, 13, 16, 17, 19, 20, 22, 23,
               25, 32, 32, 34, 35]
FREIREICH_C = [0, 0, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0,
               1, 1, 1, 1, 1]
# Published survival values, to three decimals.
FREIREICH_S = {6: 0.857, 7: 0.807, 10: 0.753, 13: 0.690, 22: 0.538,
               23: 0.448}

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    notes: list[str] = field(default_factory=list)


def check_config() -> Check:
    from . import config

    problems = config.check_all()
    if problems:
        return Check("config", FAIL,
                     f"{len(problems)} problem(s) in the config files",
                     problems)
    return Check("config", OK, "settings, providers, watchlist and corpus "
                               "parse and satisfy their invariants")


def check_estimator() -> Check:
    """Turnbull must collapse onto Kaplan-Meier where the two provably agree.

    Every observation here is either an exact event or right-censored, and on
    that shape the interval-censored NPMLE reduces to the product-limit
    estimator. Any disagreement is this installation's problem, because the
    right answer is published.
    """
    from .metrics import Observation, kaplan_meier
    from .survival import INF, Interval, fit

    eps = 1e-6
    obs = [Interval(t - eps, float(t)) if not c else Interval(float(t), INF)
           for t, c in zip(FREIREICH_T, FREIREICH_C, strict=True)]
    est = fit(obs)
    km = kaplan_meier([Observation(float(t), not c)
                       for t, c in zip(FREIREICH_T, FREIREICH_C, strict=True)])
    km_at = dict(zip(km.times, km.survival, strict=True))

    notes, worst = [], 0.0
    for t, published in sorted(FREIREICH_S.items()):
        s_km = km_at.get(float(t))
        s_tb = 1.0 - est.cdf_upper(float(t))
        if s_km is None:
            notes.append(f"S({t}): Kaplan-Meier produced no value at all")
            continue
        if abs(s_km - published) > 2e-3:
            notes.append(f"S({t}): KM {s_km:.4f}, published {published:.3f}")
        if abs(s_tb - s_km) > 1e-6:
            notes.append(f"S({t}): Turnbull {s_tb:.6f}, KM {s_km:.6f}")
        worst = max(worst, abs(s_tb - s_km))

    if km.quantile(0.5) != 23.0:
        notes.append(f"median: {km.quantile(0.5)}, published 23 weeks")
    if est.dropped:
        notes.append(f"{est.dropped} observation(s) matched no support "
                     f"interval and were dropped by the NPMLE")
    if notes:
        return Check("estimator", FAIL,
                     "the reported estimator does not reproduce published "
                     "values", notes)
    return Check("estimator", OK,
                 f"Turnbull reproduces published Kaplan-Meier values on "
                 f"Freireich 1963 (worst disagreement {worst:.2e})")


def check_grader() -> Check:
    """The two version-boundary bugs that shipped, as runtime assertions.

    Both produced a plausible verdict rather than a crash, which is why they
    survived a reading of the code.
    """
    from .grader import grade
    from .models import ABSENT, FRESH, STALE, Event

    def ev(answer: str, predecessor: str | None = None) -> Event:
        return Event(source="verify", source_class="synthetic",
                     subject="pkg", published_at=0.0, discovered_at=0.0,
                     question="q", answer=answer, predecessor=predecessor)

    cases = [
        # (label, event, payload, expected verdict)
        ("a prefix of a longer version is not a match",
         ev("15.4.1", "15.4.0"), {"text": "pkg 15.4.10 is out"}, ABSENT),
        ("a v-prefixed token matches the bare version",
         ev("15.4.2", "15.4.1"), {"text": "released v15.4.2 today"}, FRESH),
        ("the superseded version is STALE, not ABSENT",
         ev("2.0.0", "1.9.9"), {"text": "current release is 1.9.9"}, STALE),
        ("a page mentioning neither is ABSENT",
         ev("3.1.0", "3.0.9"), {"text": "unrelated prose"}, ABSENT),
    ]
    notes = []
    for label, event, payload, expected in cases:
        got, _, _, _ = grade(event, payload)
        if got != expected:
            notes.append(f"{label}: got {got}, expected {expected}")
    if notes:
        return Check("grader", FAIL,
                     "the grader disagrees with its own regression cases",
                     notes)
    return Check("grader", OK,
                 f"{len(cases)} version-boundary cases graded as expected")


def check_ledger(run_dir=None) -> Check:
    from .ledger import Ledger

    led = Ledger(run_dir)
    if not led.results_path.exists() and not led.events_path.exists():
        return Check("ledger", OK, f"no ledger yet at {led.root} — nothing "
                                   f"to check")
    bad = led.integrity()
    if not bad:
        n = len(led.results())
        return Check("ledger", OK,
                     f"{led.root}: every line parses, {n} result(s), "
                     f"no duplicate probe ids")
    notes = []
    for fname, counts in sorted(bad.items()):
        notes.append(
            f"{fname}: {counts['unparseable']} unparseable, "
            f"{counts['wrong_shape']} wrong shape, "
            f"{counts['duplicates']} duplicate probe id(s), "
            f"of {counts['total']} line(s)")
    # A torn line is survivable — the reader skips it. Duplicate probe ids
    # mean two runs overlapped, which inflated a rate and double-counted a
    # spend, and that is a fact about numbers already reported.
    dupes = any(c["duplicates"] for c in bad.values())
    return Check("ledger", FAIL if dupes else WARN,
                 "duplicate probe ids: two runs overlapped" if dupes
                 else "damaged lines are skipped on read, not repaired",
                 notes)


def check_platform() -> Check:
    from . import lock

    if lock.SUPPORTED:
        return Check("platform", OK,
                     "advisory file locking available; overlapping "
                     "discover/probe runs are prevented")
    return Check("platform", WARN,
                 "advisory file locking unavailable on this platform",
                 ["Two cron runs that overlap will both dispatch every due "
                  "probe: double spend, duplicate results, inflated rates.",
                  "Serialise the jobs yourself, or run them somewhere with "
                  "fcntl.flock."])


def run_all(run_dir=None) -> list[Check]:
    return [check_config(), check_estimator(), check_grader(),
            check_ledger(run_dir), check_platform()]


def worst(checks: list[Check]) -> str:
    if any(c.status == FAIL for c in checks):
        return FAIL
    if any(c.status == WARN for c in checks):
        return WARN
    return OK
