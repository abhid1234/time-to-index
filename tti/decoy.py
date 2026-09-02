"""The instrument's own false-positive rate.

Every number this project reports rests on one unchecked assumption: that when
the pipeline says FRESH, the provider really did surface the new fact. Two ways
that can be false, and neither shows up anywhere in a leaderboard:

    The grader over-matches. A version-shaped token appears in unrelated
    prose, a changelog lists every release ever made, a search result quotes
    a range. `15.4.1` matching inside `15.4.10` was exactly this, and it
    shipped.

    The provider hallucinates. A generative answer layer invents a plausible
    version number. It looks like retrieval and it is not.

Both inflate recall, both leave the payload looking perfectly ordinary, and
nothing in the existing output can distinguish either from a real hit.

So: grade every stored payload a second time against a **counterfactual**
answer -- a version-shaped token, of the same shape as the real one, for the
same subject, that the registry confirms was never published. A FRESH verdict
against a version that does not exist is a false positive by construction, and
the rate of them is the error bar that belongs on every recall number in the
report.

Two properties make this worth doing rather than merely worth saying:

    It costs nothing. The payloads are already stored. `tti decoy` makes zero
    provider calls; the only network traffic is asking the registry to confirm
    the counterfactual really is absent.

    It cannot be gamed by tuning the grader. Loosening the rules to raise
    recall raises the false-positive rate in the same motion, and both numbers
    are printed side by side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .grader import grade
from .models import ABSENT, ERROR, SKIPPED, Event

# Semantic-ish versions only. A counterfactual has to be the same *shape* as
# the real answer or it tests nothing: if the decoy is obviously unlike any
# real token, the grader declines it for the wrong reason and the measured
# false-positive rate is an artifact of the decoy's weirdness.
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)([-+].*)?$")


class Undecoyable(ValueError):
    """No safe counterfactual exists for this event."""


def mint(event: Event, offset: int = 7) -> str:
    """A version-shaped token for this subject that was never published.

    The patch component is pushed far enough past the real one to be outside
    any plausible release, and the offset is fixed rather than random so the
    whole check is reproducible: two people running `tti decoy` on the same
    ledger must get the same number, or it is not a measurement.

    Raises rather than inventing something for a non-semver answer. A decoy
    that does not look like a real answer measures the decoy.
    """
    m = _SEMVER.match(event.answer.strip())
    if not m:
        raise Undecoyable(f"{event.answer!r} is not a plain semantic version")
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    cand = f"{major}.{minor}.{patch + offset}"
    # Must not collide with anything the event itself declares, or a hit would
    # be a true positive wearing a decoy's name.
    known = set(event.answer_aliases) | set(event.predecessor_aliases)
    if cand in known:
        raise Undecoyable(f"{cand} is already an alias of this event")
    return cand


def as_decoy_event(event: Event, token: str) -> Event:
    """The same event with the counterfactual substituted for the answer.

    Aliases are dropped deliberately. The real aliases describe the real
    release; carrying them over would let a payload match the true answer
    through an alias and be scored as a false positive.
    """
    return Event(
        source=event.source, source_class=event.source_class,
        subject=event.subject, published_at=event.published_at,
        discovered_at=event.discovered_at, question=event.question,
        answer=token, answer_aliases=[token], predecessor=None,
        predecessor_aliases=[], url="", origins=[], meta={},
        event_id=f"decoy-{event.event_id}",
    )


@dataclass
class ArmFalsePositives:
    provider: str
    mode: str
    graded: int = 0          # payloads re-graded against a counterfactual
    hits: int = 0            # payloads that matched one
    examples: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.hits / self.graded if self.graded else float("nan")


@dataclass
class Report:
    arms: list[ArmFalsePositives] = field(default_factory=list)
    events_decoyed: int = 0
    events_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    unverified: int = 0      # counterfactuals we could not confirm are absent

    @property
    def any_graded(self) -> bool:
        return any(a.graded for a in self.arms)


def run(ledger, verify_absent=None, verbose: bool = True) -> Report:
    """Re-grade every stored payload against a counterfactual answer.

    `verify_absent(event, token) -> bool | None` confirms with the publisher
    that the token really was never released. None means "could not ask" --
    counted separately, because an unverified counterfactual is weaker
    evidence than a verified one and pretending otherwise would overstate the
    check that exists to keep us honest.
    """
    events = ledger.events()
    rep = Report()

    decoys: dict[str, Event] = {}
    for ev in events.values():
        try:
            token = mint(ev)
        except Undecoyable as exc:
            rep.events_skipped += 1
            reason = str(exc).split(" is ")[-1]
            rep.skip_reasons[reason] = rep.skip_reasons.get(reason, 0) + 1
            continue
        if verify_absent is not None:
            ok = verify_absent(ev, token)
            if ok is False:
                # The counterfactual turned out to be a real release. Not a
                # failure of anything: registries publish, and a fixed offset
                # will occasionally land on a version that exists. Dropping it
                # is the only correct move -- grading against it would count
                # true retrieval as a false positive.
                rep.events_skipped += 1
                rep.skip_reasons["counterfactual actually exists"] = \
                    rep.skip_reasons.get("counterfactual actually exists", 0) + 1
                continue
            if ok is None:
                rep.unverified += 1
        decoys[ev.event_id] = as_decoy_event(ev, token)
    rep.events_decoyed = len(decoys)

    by_arm: dict[tuple[str, str], ArmFalsePositives] = {}
    for r in ledger.results():
        if r.verdict in (ERROR, SKIPPED) or not r.raw_ref:
            continue
        decoy = decoys.get(r.event_id)
        if decoy is None:
            continue
        payload = ledger.load_raw(r.raw_ref)
        if payload is None:
            continue
        arm = by_arm.setdefault((r.provider, r.mode),
                                ArmFalsePositives(r.provider, r.mode))
        arm.graded += 1
        verdict, fresh_hits, _, _ = grade(decoy, payload)
        if verdict != ABSENT:
            arm.hits += 1
            if len(arm.examples) < 5:
                arm.examples.append(
                    (decoy.subject, decoy.answer,
                     ", ".join(fresh_hits[:3]) or verdict))
            if verbose:
                print(f"  ! {r.provider}/{r.mode} matched {decoy.answer} for "
                      f"{decoy.subject} — a version that was never published")

    rep.arms = sorted(by_arm.values(), key=lambda a: (-a.rate, a.provider))
    return rep


def npm_absent(event: Event, token: str) -> bool | None:
    """Ask the npm registry whether a version exists. None if we cannot ask.

    Only npm and PyPI subjects can be checked this way; everything else
    returns None and is counted as unverified rather than assumed absent.
    """
    from . import http
    from .sources.npm import fetch_packument

    try:
        if event.source == "npm":
            # Through the shared bounded fetch. With the module default this
            # raised on the twelve largest packages and the check quietly
            # returned "unverified" for exactly the subjects that matter.
            doc, _ = fetch_packument(event.subject)
            key = "versions"
        elif event.source == "pypi":
            doc = http.get_json(f"https://pypi.org/pypi/{event.subject}/json")
            key = "releases"
        else:
            return None
    except Exception:
        return None
    versions = doc.get(key) if isinstance(doc, dict) else None
    if not isinstance(versions, dict):
        return None
    return token not in versions
