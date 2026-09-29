# The other half: can an agent read the page at all?

A provider can only return what it could read. Two commands, no keys and no
ledger required, measure the corpus rather than the providers:

```bash
tti crawlability https://yoursite.com --find "the fact you care about"
tti routes https://yoursite.com --sample 8    # sample the site's own sitemap
tti survey                                     # scan data/corpus.yaml
tti survey --out-dir docs                      # ...and render corpus.html
tti watch --out-dir docs                       # ...with the change history
```

The corpus half gets its own page rather than a section of the provider
dashboard, because the two measure different things on different schedules
and a combined page would imply a joint analysis that only exists once both
have run. It refuses whatever the terminal refuses: unreachable, unstable and
intercepted targets appear as excluded with the reason, never folded into the
rate.

`crawlability` answers the two questions that decide whether a page enters an
AI system: is the content in the served bytes as text, and is the crawler
allowed to fetch it. Run against three package registries:

```
crates.io/crates/serde       sveltekit   client_shell        32 chars visible of 5,056
pypi.org/project/httpx/      —           static_html      9,898 chars visible of 141,336
pkg.go.dev/…/gin             —           static_html     93,012 chars visible of 429,377
```

Same kind of site, same kind of fact, opposite outcomes. The sharpest
category the survey reports is pages that **allow every AI crawler in
robots.txt and ship them nothing at all** — no readable body and no metadata.
Nobody chose that. It falls out of a rendering default, and the robots.txt
records that the team wanted the opposite.

`tti watch` records each run and reports where posture *moved*. That is the
statement a single scan cannot make and the only one that is actionable:
nobody decides to become invisible to agents, they ship a refactor and no
signal turns red. There is no build check, no deploy gate and no dashboard
panel that goes red when a route stops being readable, so a regression is
only ever visible in hindsight — and only if something was watching.

```bash
tti watch                 # record a run
tti watch --report        # what moved, without fetching
```

It refuses to overclaim: one run is not a series, and under a day of history
"nothing changed" describes the observation window rather than the web. Both
are printed rather than assumed.

`tti routes` exists because one page is enough to prove a failure and not
enough to describe a site. Marketing pages are almost always server-rendered;
the interesting failures are on detail pages. It reads the site's own sitemap,
samples evenly across the sorted route list (deterministically, so two runs
examine the same routes and a site that changed is distinguishable from a
sample that moved), and reports the spread.

Four things keep these claims straight, and each was added because an earlier
version of one was wrong:

- **A verdict needs repeat fetches to agree.** The same URL returned 5,056
  bytes of client shell on one run and a zero-byte 404 on the next. A page
  that answers differently across fetches is excluded, not judged.
- **A response has to be big enough to be a page** before it can be called a
  bad one. An early version reported a proxy error as "client shell, not
  readable".
- **Metadata counts.** A shell that ships JSON-LD or OpenGraph is
  `metadata_only`, not unreadable: an agent learns what the page is without
  executing anything. It still does not learn what the page says, so it is a
  third state rather than a pardon.
- **Identical bodies across distinct URLs are interception, not a posture.**
  Six different PyPI project pages returned byte-identical 3,036-byte bodies
  with HTTP 200, and the first version of `tti routes` duly reported that PyPI
  is entirely client-rendered. It is not. CDN challenges, WAF blocks and
  soft-404s all answer 200 and all classify cleanly as a client shell. Every
  member of an identical group is now excluded — not all-but-one, because
  keeping a representative assumes one of them is the real page and in the
  interception case none of them is.

This half is deliberately vendor-neutral and framework-neutral. Posture
predicts retrievability; framework only correlates with it, and the
aggregation says so.
