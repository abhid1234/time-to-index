# Results

**No real run has happened yet.** This file is written by `tti report` and
will be replaced by measured numbers the first time the harness runs against
live provider APIs.

Nothing in this repository currently contains a finding about any product.
`docs/demo.html` is a synthetic run with made-up providers (`provider-a/b/c`)
whose latencies are drawn from a seeded generator; it exists to show what the
instrument renders and to check that the estimator recovers latencies it was
never shown. It is labelled as such on the page itself.

Saying this in the file that will eventually hold the leaderboard is
deliberate. An empty results file that looks like a template is how a repo
gets read as having found something it has not.

## When results do land

They get published on schedule regardless of which provider wins, including
if the provider I find most interesting comes last, and including if the
answer is that the differences are inside the noise and the metric is boring.
`tti power` is in the repo precisely so that last outcome can be stated with
a number attached rather than as a shrug.

Corrections are issued in-repo rather than silently re-run. If a vendor
shows that an adapter sends a call their API was not designed for, the fix is
a commit and a note here, not a quiet re-render.
