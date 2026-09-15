# LinkedIn post

A search index that is wrong looks exactly like one that is fast.

Every retrieval benchmark I can find works the same way: ask a question, check whether the right answer came back, score it out of one. Which puts two completely different failures in the same bucket.

The API returns nothing → your agent retries, widens the query, or says it doesn't know. Annoying, and visible.

The API confidently returns yesterday's answer → your agent cites it. To your customer. With no signal anywhere downstream that the number is stale.

One is a shrug. The other is a lie with a citation. Scored out of one they are identical, and in production they are nothing alike. So I spent a couple of weekends building the instrument that separates them.

The design involves no crawling at all, which is the part people assume is hard. I watch sources that timestamp their own publications — npm, PyPI, GitHub releases, SEC EDGAR, arXiv. When a package publishes, the registry itself says exactly when. That's t=0, on the publisher's clock, never mine. You can't measure lateness without an agreed zero, and asking a crawler when something appeared is asking the defendant to time the race.

Every search API then gets the same question at six fixed lags — 5 minutes to 72 hours — and at each rung I fetch the source URL directly as a control, so "the index was slow" is never confused with "the page wasn't live yet."

Twelve days in, here is the clearest thing it has caught.

uv 0.12.15 was released on GitHub. My collector saw it 274 seconds later. Five minutes after the release went live, four search indexes and the control were asked what the current version was.

The control fetched 0.12.15 in 416 ms.
Exa returned 0.12.14. Parallel's advanced mode returned 0.12.14.
Brave and Parallel's fast mode returned nothing at all.

So: not one of the four had the current answer, and half of them confidently asserted the superseded one — the same wrong version, independently, at the same instant. The control proves the release was live and fetchable at that moment. This was not a publishing delay.

Every conventional benchmark scores those two stale rows exactly the same as the two empty ones: zero. In production they are not the same event at all. One makes your agent retry. The other makes it cite 0.12.14 to your customer.

Across the run: four STALE verdicts, on three separate packages, across three different arms.

And the part I have to say in the same breath: that is not a rate, not a ranking, and emphatically not "Exa and Parallel are stale." Thirteen events and twenty-two graded calls cannot support a comparison between providers — no pair of arms separates after adjustment, and the dashboard refuses to rank itself for exactly that reason.

What four instances do establish: the failure mode is real, it happens at the front of the ladder where agents actually live, it happens to more than one provider, and about a cent finds it.

One more thing, for anyone evaluating these APIs.

Artificial Analysis launched a Search Index for exactly these providers on 18 August — serious work, published methodology, and the most useful cost analysis anyone has done on these APIs. Its three component benchmarks are all answer-correctness scores, run through a harness that gives the agent 25 turns with unlimited tool calls.

Give an agent that budget and an empty result set, and it retries, rephrases and widens until it finds the answer. Give it a confidently superseded answer and it has no signal to retry on, so it submits. Their methodology is careful about the limit: burn all 25 turns without finishing and you score zero, so an absence can cost correctness in the tail. But short of that it costs turns, tokens and latency, and their cost and time columns capture all three. A stale answer costs none of them — fast, cheap, wrong, and caught by no column at all.

Which means the more agentic the harness — the closer to how anyone actually runs these in production — the more absence gets priced into cost, and the more staleness survives into the graded score. The failure mode that matters most in production is the one a production-shaped benchmark is least able to see.

And then I told the same lie myself — three times, as it turned out. Rungs that hadn't come round yet rendered as empty grey squares, in a grid where grey already meant ABSENT. On the page whose entire argument is that distinction. Then the totals line counted squares that were never dispatched as "graded provider calls," overstating its own sample by five times.

None of them was in the measurement. All three were in the presentation, which is exactly where I'd been telling everyone else to look. The post has the details.

The video above is the page being driven, with the argument narrated over it.

Or drive it yourself — run the ladder, then flip the scoring rule and watch the ranking invert:
https://abhid1234.github.io/time-to-index/playground.html

Code, MIT, full ledger, every raw payload and every price:
https://github.com/abhid1234/time-to-index

If you work on one of these indexes and think the methodology is unfair to you, I want to hear it. The plan is pre-registered precisely so that argument can be about the method rather than the result.
