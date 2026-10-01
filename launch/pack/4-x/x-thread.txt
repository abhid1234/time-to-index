# X thread

Counts are measured by `check_counts.py`, the way X counts: every URL is 23 characters.

---

**1/**

A search index that is wrong looks exactly like one that is fast.

Every retrieval benchmark scores both the same: zero.

In production they are nothing alike. So I built the thing that separates them, and ran it for nearly four weeks.

---

**2/**

Returns nothing → your agent retries, widens, or says it doesn't know. Annoying, and visible.

Returns yesterday's answer → your agent cites it. To your customer. With no signal downstream that it's stale.

One is a shrug. The other is a lie with a citation.

---

**3/**

The clearest single catch:

uv 0.12.15 released on GitHub. Five minutes later, four search indexes and a control were asked for the current version.

---

**3b/**

Control (direct fetch of the release page): 0.12.15, in 416ms.

Exa: 0.12.14.
Parallel (advanced): 0.12.14.

Brave: nothing.
Parallel (fast): nothing.

None of the four had it. Half confidently asserted the old one.

---

**3c/**

Same wrong version. Independently. At the same instant.

The control proves the release was live and fetchable right then.

Every conventional benchmark scores those two stale rows the same as the two empty ones: zero.

---

**4/**

But the result I'd lead with is one I didn't go looking for.

Every fresh answer in the whole run — all 12 — came from Federal Register documents.

12 of 40 current at t+5m.

npm, PyPI and GitHub releases: 0 of 38.

Fisher p = 0.0002.

---

**4b/**

So "how fast is this search API?" is badly underspecified. Fast for what?

A new US regulation: findable in five minutes more often than not.

A new version of a package half the internet depends on: never. And 5 times, the old version instead.

---

**5/**

The leaderboard can now rank, in part.

Parallel (advanced) separates from Brave and from Exa after Holm–Bonferroni — adjusted p 0.018 and 0.036.

The other four pairs are still underpowered, and the dashboard says so rather than sorting them.

---

**5b/**

Two caveats, same breath.

All 9 of Parallel's fresh answers were Federal Register. On package registries it was never fresh either.

And the fastest arm is also tied for the most stale answers — two apiece with Exa.

---

**5c/**

That last point is the whole argument.

A benchmark that collapses retrieval into one number has to decide whether that arm is good or bad.

It's both. Speed and staleness are different axes, and scoring them together is how you lose the one that costs you.

---

**6/**

How it works: no crawling, which is the part people assume is hard.

I watch sources that timestamp their own publications. t=0 is the publisher's clock, never mine.

Asking a crawler when something appeared is asking the defendant to time the race.

---

**6b/**

Every index gets the same question at fixed lags — and I fetch the source directly as a control.

That's what makes the uv row a stale index, not a slow publisher.

(It fails on every Federal Register page, 10 of 10. Disclosed, not patched post-hoc.)

---

**7/**

Artificial Analysis launched a Search Index for these same APIs in August. Serious work, and the best cost analysis published on them.

Its three component benchmarks are all answer-correctness scores.

Nothing returned and yesterday's answer both score zero.

---

**8/**

The part I keep turning over: their harness gives the agent 25 turns.

Empty result set → it retries and widens until it finds the answer.

Stale answer → no signal to retry on. It submits.

Agentic harnesses absorb ABSENT, preserve STALE.

---

**9/**

To be fair to them: burn all 25 turns without finishing and you score zero, so absence can cost correctness in the tail.

But short of that it costs turns, tokens and latency — which their cost and time columns do capture.

A stale answer costs none of those.

---

**10/**

Most of the build wasn't measurement. It was machinery to stop the numbers being nicer than the truth.

Plan hashed + locked before collection. Probe fires late → thrown away, not recorded at a lag I didn't observe. Failed call → ERROR, never ABSENT.

---

**11/**

And then I told the same lie myself.

Rungs that hadn't come round yet rendered as empty GREY squares — in a grid where grey already meant ABSENT.

On the page whose entire argument is that distinction.

---

**11b/**

Then the totals line counted squares that were never dispatched as "graded provider calls." It overstated its own sample by 5x — three lines under a legend explaining what a skip is.

Every bug was in the presentation, not the measurement.

---

**12/**

What I got wrong: I ran it on GitHub Actions.

Asks for a 10-min cron. Gets one every few hours. So every verdict above is at t+5m — later rungs almost never land in their window.

37 events in 27 days. Dropping the rest is correct. The runner is the fix.

---

**13/**

Playground — run the ladder, flip the scoring rule, watch the leaderboard invert. Real measured data underneath.

https://abhid1234.github.io/time-to-index/playground.html

---

**14/**

Code, MIT, full ledger — every raw payload, every verdict, every price. Pre-registered.

If you work on one of these indexes and think the methodology is unfair to you, I want to hear it.

https://github.com/abhid1234/time-to-index
