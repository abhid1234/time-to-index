# Contributing

The point of this repo is that someone who disagrees with its numbers can
check them, change the thing they disagree with, and see how much it
actually moves. Everything below is in service of that.

## Disagreeing with a result

Start here rather than with code. Every provider response is on disk under
`runs/raw/`.

```bash
tti regrade               # re-score stored payloads under the current rules
tti sensitivity           # re-score under seven deliberately different rule sets
```

If you think the matching rules are wrong, edit `tti/grader.py`, run
`tti regrade`, and see how many verdicts move. If the leaderboard is
unchanged, the rule you objected to was not deciding anything. If it
reorders, that is a finding and it should be filed as an issue.

## Adding a provider

One file in `tti/providers/`, about twenty lines. The adapter's only job is
to take a question string and return the vendor's verbatim JSON. It must not
normalise, reshape, or score anything — the grader reads the raw payload, and
a helpful adapter that "cleans up" a response is an adapter that decides the
result.

```python
from .. import config, http
from . import register

class Yours:
    name = "yours"

    def modes(self):     return ["base"]
    def available(self): return config.api_key("YOURS_API_KEY") is not None

    def search(self, question, mode, *, max_results, max_chars):
        return http.post_json(
            "https://api.yours.example/search",
            headers={"x-api-key": config.api_key("YOURS_API_KEY")},
            json={"query": question, "n": max_results})

@register("yours")
def _factory(): return Yours()
```

Then add it to `data/providers.yaml` with its published price and the URL
that price came from, and to `arms` in `data/settings.yaml`.

Two rules:

- **Send what the vendor documents.** Not a tuned call. If the documented
  shape does not fit the harness cleanly, say so in
  `docs/INTEGRATION-NOTES.md` rather than quietly picking a favourable
  variant. There is already one provider whose request contract genuinely
  differs, and it is flagged rather than smoothed over.
- **No key means skipped, never simulated.** There must be no fixture path
  that can reach a published number.

Add a shape to `tests/test_envelopes.py` so the flattener is pinned against
your response envelope.

## Adding a source

One file in `tti/sources/`. The bar is a single sentence: **the source must
stamp its own publication time.** Not a CMS "published" field that moves when
the page is edited — a receipt, written by the publisher at the moment of
publication.

Subclass `BaseSource` and use `fan_out`, which caps concurrency per host and
records per-subject errors. Do not catch and swallow: a source that returns
zero because a host is unreachable looks exactly like a source that returns
zero because nothing shipped, and telling those apart is most of what this
harness does.

If the fact can be superseded — a version, a filing, a release tag — set
`predecessor`, which is what makes staleness measurable. If it cannot, leave
it `None` and the event is excluded from the staleness denominator
automatically.

Set `origins` most-crawler-representative first: the human-facing page a
search engine would index, then any API fallback. The control arm records
which one answered, so a fallback is visible rather than laundered.

## Changing the statistics

`tti/survival.py` and `tti/metrics.py` are the load-bearing files. Two things
are non-negotiable:

- **Turnbull must still reduce to Kaplan–Meier** on right-censored data.
  That test runs against published Freireich 1963 values and is what ties the
  estimator to something other than this repo's own arithmetic.
- **Nothing may report a point estimate the ladder cannot support.** Medians
  are brackets because the survival function is genuinely undefined inside a
  support interval. A change that prints a single number there is inventing
  information.

If you add a metric, add the case where it should refuse to answer. Most of
the tests here are about the refusals.

## Running the tests

```bash
pip install -e ".[dev]"
pytest -q
ruff check tti tests
tti demo          # the estimator must recover the generator's own draws
```

The suite makes no network calls, by design. A test run that depends on a
live registry fails for reasons unrelated to the change, and a benchmark
whose own CI is flaky has no standing to publish reliability numbers about
anyone else.

## What will get pushed back on

- Anything that makes a failure quieter. Swallowed exceptions, silent caps,
  defaults that hide a partial run.
- A metric without the case where it declines to answer.
- Tuning one provider's call and not the others'.
- Results published without the raw payloads that produced them.
- A destructive write that is not atomic. `Ledger.rewrite_results` is the
  only one, and it exists because the direct version could truncate a month
  of collection when interrupted.
