## What changes

## Does it move a verdict?

<!-- If this touches tti/grader.py, a provider adapter or a source, paste the
     before/after from `tti regrade` or `tti sensitivity`. "No verdicts moved"
     is a useful answer. -->

## Checks

- [ ] `pytest -q && ruff check tti tests` passes
- [ ] `tti verify` passes
- [ ] No keys, tokens or private payloads in the diff
