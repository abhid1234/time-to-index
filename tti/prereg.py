"""The analysis plan, and the lock that makes editing it visible.

`docs/PREREGISTRATION.md` carries one fenced ```yaml prereg block. That block
is simultaneously the human document and the machine's copy -- deliberately
one set of bytes, because two copies of a plan drift and the drift always
favours whoever is reading the results.

Three things happen here:

    parse()       pull the block out of the markdown and validate its shape.
    plan_hash()   hash the *canonical* form, not the file. Rewording the
                  surrounding prose must not invalidate a plan; moving a
                  threshold must.
    classify()    given the arms actually present in a run, say which were
                  declared in advance, which are exploratory, and which were
                  declared and produced nothing.

The last one is the least obvious and the most load-bearing. An arm that was
declared and then produced no data is how a benchmark loses its worst result
without anybody deciding to: the table is built from what is in the ledger, so
an arm that failed everywhere simply is not a row. Naming it costs one line and
closes the gap.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "docs" / "PREREGISTRATION.md"

# The one fence we read. A plain ```yaml block is documentation; the `prereg`
# infix is the opt-in, so the file can contain YAML examples without one of
# them silently becoming the plan.
_FENCE = re.compile(r"^```yaml[ \t]+prereg[ \t]*$(.*?)^```[ \t]*$",
                    re.MULTILINE | re.DOTALL)

REQUIRED = ("plan_version", "primary_endpoint", "arms_declared_in_advance",
            "ladder_seconds", "hypotheses", "exclusions_declared_in_advance",
            "stopping_rule")


class PreregError(RuntimeError):
    """The plan is missing, unparseable, or does not say what a plan must say.

    Raised rather than defaulted. A benchmark that falls back to "no plan" when
    it cannot read its plan has the same output as one that never had a plan,
    and no way to tell the two apart.
    """


@dataclass
class Hypothesis:
    id: str
    statement: str
    test: str = ""
    threshold: str = ""
    falsified_if: str = ""


@dataclass
class Plan:
    version: int
    registered: str
    primary_endpoint: str
    secondary_endpoints: list[str]
    arms: list[str]
    ladder: list[int]
    hypotheses: list[Hypothesis]
    exclusions: list[dict]
    stopping_rule: str
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def hash(self) -> str:
        return plan_hash(self.raw)

    def declares(self, provider: str, mode: str) -> bool:
        return f"{provider}/{mode}" in self.arms


def _norm(v: Any) -> Any:
    """Canonical form: whitespace-collapsed strings, sorted mappings.

    YAML block scalars carry the line breaks of whatever column the author
    happened to wrap at. Re-wrapping a sentence is an edit to the document and
    not an edit to the plan, and a hash that cannot tell those apart makes the
    lock useless -- it would fire on every typo fix, and a lock that cries wolf
    gets ignored, which is the same as not having one.
    """
    if isinstance(v, str):
        return " ".join(v.split())
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(v[k]) for k in sorted(v)}
    if isinstance(v, bool):
        return v
    return v


def canonical(raw: dict) -> str:
    return yaml.safe_dump(_norm(raw), sort_keys=True, default_flow_style=False,
                          allow_unicode=True, width=10_000)


def plan_hash(raw: dict) -> str:
    return hashlib.sha256(canonical(raw).encode("utf-8")).hexdigest()[:16]


def parse(path: pathlib.Path | None = None) -> Plan:
    path = pathlib.Path(path) if path else DEFAULT_PATH
    if not path.exists():
        raise PreregError(f"{path} does not exist; there is no analysis plan")
    m = _FENCE.search(path.read_text(encoding="utf-8"))
    if not m:
        raise PreregError(
            f"{path.name} has no ```yaml prereg block. The plan and the "
            f"document are meant to be the same bytes; a document without the "
            f"block is prose that nothing enforces.")
    try:
        raw = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        raise PreregError(f"{path.name}: the prereg block is not valid YAML: "
                          f"{exc}") from exc
    if not isinstance(raw, dict):
        raise PreregError(f"{path.name}: the prereg block must be a mapping")

    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise PreregError(f"{path.name}: the plan does not declare "
                          f"{', '.join(missing)}")

    hyps = []
    for i, h in enumerate(raw.get("hypotheses") or []):
        if not isinstance(h, dict) or "id" not in h or "statement" not in h:
            raise PreregError(f"{path.name}: hypothesis {i} needs an id and a "
                              f"statement")
        if not str(h.get("falsified_if", "")).strip():
            # A hypothesis with no falsification condition is not a hypothesis.
            # It is a hope, and it will be satisfied by whatever arrives.
            raise PreregError(
                f"{path.name}: hypothesis {h['id']} declares no "
                f"`falsified_if`. A hypothesis that cannot come out false is "
                f"not pre-registered, it is pre-assumed.")
        hyps.append(Hypothesis(
            id=str(h["id"]), statement=str(h["statement"]),
            test=str(h.get("test", "")), threshold=str(h.get("threshold", "")),
            falsified_if=str(h["falsified_if"])))
    if not hyps:
        raise PreregError(f"{path.name}: the plan declares no hypotheses")

    arms = [str(a).split("#")[0].strip()
            for a in raw.get("arms_declared_in_advance") or []]
    arms = [a for a in arms if a]
    if not arms:
        raise PreregError(f"{path.name}: the plan declares no arms")
    for a in arms:
        if a.count("/") != 1:
            raise PreregError(f"{path.name}: arm {a!r} is not provider/mode")

    ladder = raw.get("ladder_seconds") or []
    if not ladder or list(ladder) != sorted(set(ladder)):
        raise PreregError(f"{path.name}: ladder_seconds must be a strictly "
                          f"increasing list")

    return Plan(
        version=int(raw["plan_version"]),
        registered=str(raw.get("registered", "")),
        primary_endpoint=" ".join(str(raw["primary_endpoint"]).split()),
        secondary_endpoints=[" ".join(str(s).split())
                             for s in raw.get("secondary_endpoints") or []],
        arms=arms, ladder=[int(r) for r in ladder], hypotheses=hyps,
        exclusions=list(raw.get("exclusions_declared_in_advance") or []),
        stopping_rule=" ".join(str(raw["stopping_rule"]).split()),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Classification against a run
# ---------------------------------------------------------------------------

@dataclass
class Classification:
    declared: list[str] = field(default_factory=list)
    exploratory: list[str] = field(default_factory=list)
    # Enabled in this run (a key was present) and produced no scoreable row.
    declared_but_silent: list[str] = field(default_factory=list)
    # Declared, but never enabled here -- no key -- so no probe was dispatched.
    # A different fact from silence: the first real dashboard listed all six
    # provider arms as "produced nothing" on a run where none had a key.
    declared_not_enabled: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.exploratory and not self.declared_but_silent


def classify(plan: Plan, present: list[tuple[str, str]],
             control: str = "origin",
             enabled: list[tuple[str, str]] | None = None) -> Classification:
    """Sort the arms in a run against the arms in the plan.

    `present` is (provider, mode) for every arm that produced at least one
    scoreable observation. `enabled` is (provider, mode) for every arm the
    runner could dispatch -- configured, with a key; None means "treat every
    declared arm as enabled", which is the pre-existing behaviour. The control
    arm is declared in the plan and excluded from the leaderboard, so it is
    neither exploratory nor missing -- it is simply not the subject of this
    comparison.
    """
    seen = {f"{p}/{m}" for p, m in present}
    on = None if enabled is None else {f"{p}/{m}" for p, m in enabled}
    declared = [a for a in plan.arms if not a.startswith(f"{control}/")]
    silent = [a for a in declared if a not in seen]
    return Classification(
        declared=sorted(a for a in declared if a in seen),
        exploratory=sorted(a for a in seen
                           if a not in plan.arms and not a.startswith(f"{control}/")),
        declared_but_silent=sorted(a for a in silent if on is None or a in on),
        declared_not_enabled=sorted(a for a in silent if on is not None and a not in on),
    )


# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------

LOCK_NAME = "prereg.lock"


def lock_path(run_dir: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(run_dir) / LOCK_NAME


def lock(run_dir: pathlib.Path, plan: Plan) -> str:
    """Record the plan hash for this run, once. Returns the locked hash.

    Written on the first probe rather than at configuration time, because a
    plan edited before any data exists is not a plan being edited after seeing
    results -- it is a plan being written. The lock is meaningless until there
    is something to be tempted by.
    """
    p = lock_path(run_dir)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(plan.hash + "\n", encoding="utf-8")
    tmp.replace(p)
    return plan.hash


def locked_hash(run_dir: pathlib.Path) -> str | None:
    p = lock_path(run_dir)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip() or None


@dataclass
class LockStatus:
    locked: str | None
    current: str
    started: bool

    @property
    def drifted(self) -> bool:
        return self.started and self.locked is not None \
            and self.locked != self.current


def status(run_dir: pathlib.Path, plan: Plan, started: bool) -> LockStatus:
    """`started` may be inferred from the ledger, but the lock outranks it.

    A caller normally decides "collection began" from `bool(ledger.results())`.
    That is empty in one case that matters: a results file whose every line is
    torn. The reader skips malformed lines by design, so the run looks like it
    never started, the drift check is skipped, and a plan edited after the data
    passes silently -- exactly when the ledger damage should be making everyone
    more careful, not less.

    The lock file only exists because a probe was dispatched. Its presence is
    the stronger evidence and wins.
    """
    lk = locked_hash(run_dir)
    return LockStatus(locked=lk, current=plan.hash,
                      started=bool(started) or lk is not None)


DRIFT_NOTE = (
    "The analysis plan has changed since this run began collecting. That is "
    "not forbidden and it is not necessarily wrong — plans are sometimes "
    "wrong. It is reported here, every time, because a plan edited after the "
    "data exists is a different kind of claim from a plan written before it, "
    "and only one of those two facts survives if nobody prints it.")
