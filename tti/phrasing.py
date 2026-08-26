"""Question phrasing variants.

`docs/METHODOLOGY.md` lists this as a limitation of the first version:
questions come from one template per source, so a provider whose query
rewriting favours a different phrasing is being under-measured, and nothing
in the harness could tell.

It matters more for this benchmark than for a quality benchmark. An agent
does not ask the question a template would write. It asks whatever its own
planner produced that turn, and if a provider returns the new fact for
"latest version of next" but not for "what version of next shipped most
recently", the freshness number attached to it is about the phrasing as much
as the index.

So: a bounded second axis. The same event, the same rung, the same provider,
asked three ways. The metric is agreement -- of the events where *any*
phrasing came back fresh, how many phrasings did? A provider at 100% is
phrasing-insensitive at this rung. One at 40% has the document and does not
reliably surface it, which is a different problem from not having it, and
one an agent hits far more often than a benchmark does.

Cost is why this is opt-in and rung-limited. Three phrasings at every rung
triples the bill; three phrasings at one rung adds two probes per event.
"""

from __future__ import annotations

from .models import Event

# Each entry is (template, requires) where `requires` names the meta keys the
# template needs. Templates that cannot be filled are skipped rather than
# rendered with an empty slot -- a question with a hole in it measures the
# hole.
_TEMPLATES: dict[str, list[str]] = {
    "npm": [
        "What is the current latest published version of the npm package {subject}?",
        "Which version of the {subject} npm package was released most recently?",
        "{subject} npm latest release version",
    ],
    "pypi": [
        "What is the current latest released version of the Python package {subject} on PyPI?",
        "Which version of {subject} was most recently published to PyPI?",
        "{subject} PyPI latest version",
    ],
    "github_release": [
        "What is the most recent release tag of the GitHub repository {subject}?",
        "Which version did {subject} release most recently on GitHub?",
        "{subject} latest GitHub release tag",
    ],
    "edgar": [
        "What is the SEC accession number of the most recent Form {form} filed by {company}?",
        "Which accession number did {company}'s latest Form {form} filing receive?",
        "{company} most recent {form} SEC accession number",
    ],
    "arxiv": [
        'What is the arXiv identifier of the paper titled "{title}"?',
        'Which arXiv ID was assigned to the preprint "{title}"?',
        '"{title}" arXiv id',
    ],
    "federal_register": [
        'What is the Federal Register document number for the document titled "{title}"?',
        'Which document number did the Federal Register assign to "{title}"?',
        '"{title}" Federal Register document number',
    ],
}

# Deliberately spanning three registers, because that is the spread an agent
# actually produces: a full natural-language question, a differently-worded
# question with the same content, and a terse keyword string of the kind a
# planner emits when it has already decided what it is looking for.
REGISTERS = ("question", "reworded", "keywords")


def variants(event: Event) -> list[str]:
    """All phrasings for an event, canonical first.

    Index 0 is always `event.question` exactly, so phrasing 0 probes are
    identical to a run with the feature switched off and the two are
    comparable.
    """
    out = [event.question]
    tpl = _TEMPLATES.get(event.source, [])
    slots = {"subject": event.subject, **{k: str(v) for k, v in event.meta.items()}}
    for t in tpl[1:]:
        try:
            q = t.format(**slots)
        except (KeyError, IndexError):
            continue        # a template we cannot fill is skipped, not patched
        if q not in out:
            out.append(q)
    return out


def variant(event: Event, index: int) -> str | None:
    v = variants(event)
    return v[index] if 0 <= index < len(v) else None


def count(event: Event) -> int:
    return len(variants(event))
