# LinkedIn post

A search index that is wrong looks exactly like one that is fast.

Every retrieval benchmark I can find works the same way: ask a question, check whether the right answer came back, score it out of one. Which puts two completely different failures in the same bucket.

The API returns nothing → your agent retries, widens the query, or says it doesn't know. Annoying, and visible.

The API confidently returns yesterday's answer → your agent cites it. To your customer. With no signal anywhere downstream that the number is stale.

One is a shrug. The other is a lie with a citation. Scored out of one they're identical. So I spent a couple of weekends building the instrument that separates them, and let it run for three and a half weeks.

Here is the clearest single thing it caught.

uv 0.12.15 was released on GitHub. Five minutes later, four search indexes were asked for the current version. The control — a direct fetch of the release page — got 0.12.15 in 416 ms.

Exa returned 0.12.14. Parallel's advanced mode returned 0.12.14. Brave and Parallel's fast mode returned nothing.

Not one of the four had the current answer, and half of them confidently asserted the superseded one. The control proves the release was live and fetchable right then. Every conventional benchmark scores those two stale rows exactly like the two empty ones: zero.

But the result I'd lead with is one I didn't go looking for.

Every fresh answer in the whole run — all 12 — came from Federal Register documents. 12 of 40 were current five minutes after publication. Across npm, PyPI and GitHub releases: 0 of 34. Fisher p = 0.0003.

So "how fast is this search API?" is badly underspecified. A new US regulation was findable within five minutes more often than not. A new version of a package half the internet depends on — never. And when a package answer did come back, five times it was the version the release had just replaced.

The leaderboard can now rank, in part. Parallel's advanced mode separates from Brave and from Exa after Holm–Bonferroni correction (adjusted p 0.018 and 0.036). The other four pairs are still underpowered and the dashboard says so.

Two caveats in the same breath. All nine of Parallel's fresh answers were Federal Register documents; on package registries it was never fresh either. And the fastest arm is also tied for the most stale answers — two apiece with Exa.

That last point is the whole argument. Any benchmark that collapses retrieval into one number has to decide whether that arm is good or bad. It's both. Speed and staleness are different axes, and scoring them together is how you lose the one that costs you.

How it works, briefly: no crawling. I watch sources that timestamp their own publications, so t=0 is the publisher's clock, never mine — you can't measure lateness without an agreed zero. Every index gets the same question at fixed lags, and at each one I fetch the source directly as a control, so "the index was slow" isn't confused with "the page wasn't live yet" — on every source except the Federal Register, where it turned out the control fails 10 times out of 10. I'm disclosing that rather than patching it post-hoc; the post has the details.

34 events, 74 graded calls, about 34 cents. Pre-registered, every raw payload in the repo.

The video above is the page being driven, narrated.

Playground — run the ladder, flip the scoring rule, watch the ranking invert:
https://abhid1234.github.io/time-to-index/playground.html

Code and full ledger, MIT:
https://github.com/abhid1234/time-to-index

If you work on one of these indexes and think the methodology is unfair to you, I want to hear it. The plan was pre-registered precisely so that argument can be about the method rather than the result.
