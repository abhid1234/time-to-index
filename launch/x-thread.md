# X thread

Counts are measured by `check_counts.py`, the way X counts: every URL is 23 characters.

---

**1/**

A search index that is wrong looks exactly like one that is fast.

Every retrieval benchmark scores both the same: zero.

In production they are nothing alike. So I built the thing that separates them.

---

**2/**

Returns nothing → your agent retries, widens, or says it doesn't know. Annoying, and visible.

Returns yesterday's answer → your agent cites it. To your customer. With no signal downstream that it's stale.

One is a shrug. The other is a lie with a citation.

---

**3/**

The design involves no crawling, which is the part people assume is hard.

I watch sources that timestamp their own publications — npm, PyPI, GitHub releases, SEC EDGAR, arXiv.

When a package publishes, the registry says exactly when. That's t=0, on their clock.

---

**4/**

You cannot measure lateness without an agreed zero.

Asking a crawler when something appeared is asking the defendant to time the race.

---

**5/**

Every search API then gets the same question at six fixed lags:

5m · 15m · 1h · 6h · 24h · 72h

And at each rung I fetch the source URL directly as a control — so "the index was slow" is never confused with "the page wasn't live yet."

---

**6/**

Here's the clearest thing it has caught.

uv 0.12.15 released on GitHub. Collector saw it 274s later.

At t+5m, four search indexes and the control were asked for the current version.

---

**6b/**

Control: 0.12.15, in 416ms.

Exa: 0.12.14.
Parallel (advanced): 0.12.14.

Brave: nothing.
Parallel (fast): nothing.

None of the four had it. Half confidently asserted the superseded one.

---

**6c/**

Same wrong version. Independently. At the same instant.

The control proves the release was live and fetchable right then. Not a publishing delay.

The indexes had a stale answer and served it with no hint that it was stale.

---

**6d/**

Every conventional benchmark scores those two stale rows the same as the two empty ones: zero.

In production they are not the same event.

One makes your agent retry. The other makes it cite 0.12.14 to your customer.

---

**7/**

This is where a project like mine starts overselling, so let me get ahead of it.

4 STALE, on 3 packages, across 3 different arms.

That's not a rate. Not a ranking. Not "Exa and Parallel are stale."

---

**7b/**

13 events and 22 graded calls cannot support a comparison between providers. No pair of arms separates after adjustment, and the dashboard refuses to rank itself for exactly that reason.

Better I hand you the sample size than you find it yourself.

---

**8/**

Artificial Analysis launched a Search Index for these same APIs on 18 Aug. Serious work, and the best cost analysis published on them.

Its three component benchmarks are all answer-correctness scores.

Nothing returned and yesterday's answer both score zero.

---

**9/**

The part I keep turning over: their harness gives the agent 25 turns.

Empty result set → it retries and widens until it finds the answer.

Stale answer → no signal to retry on. It submits.

Agentic harnesses absorb ABSENT, preserve STALE.

---

**10/**

To be fair to them: burn all 25 turns without finishing and you score zero, so absence can cost correctness in the tail.

But short of that it costs turns, tokens and latency — which their cost and time columns do capture.

A stale answer costs none of those.

---

**11/**

Most of the build wasn't measurement. It was machinery to stop the numbers being nicer than the truth.

Plan hashed + locked before collection. Probe fires late → thrown away, not recorded at a lag I didn't observe. Failed call → ERROR, never ABSENT.

---

**12/**

And then I told the same lie myself.

Rungs that hadn't come round yet rendered as empty GREY squares — in a grid where grey already meant ABSENT.

On the page whose entire argument is that distinction.

---

**12b/**

Then the totals line counted squares that were never dispatched as "graded provider calls."

124 graded, it said. The itemised verdicts added to 24.

Overstating its own sample by 5x, three lines under a legend explaining what a skip is.

---

**12c/**

Unmeasured rungs are now the only state with no fill at all. An outline, with the reason in it: not due yet, not run yet, never scheduled.

Every bug was in the presentation, not the measurement — exactly where I'd been telling everyone else to look.

---

**13/**

And the part I got wrong: I ran it on GitHub Actions.

Asks for a 10-min cron. Gets one every few hours.

So each rung after the first has ~1-in-30 odds of ever being graded. 13 events in 12 days.

Dropping them is correct. The runner is the fix.

---

**14/**

Playground — run the ladder, then flip the scoring rule and watch the leaderboard invert. Real measured data underneath.

https://abhid1234.github.io/time-to-index/playground.html

---

**15/**

Code, MIT, full ledger — every raw payload, every verdict, every price.

If you work on one of these indexes and think the methodology is unfair to you, I want to hear it. The plan is pre-registered so that argument can be about the method.

https://github.com/abhid1234/time-to-index
