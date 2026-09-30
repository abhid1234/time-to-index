# time-to-index — launch pack

Everything for the launch post lives here, **in the repo**. It used to live in
a scratch directory outside it; a container reset took the whole thing —
copy, generators and rendered video — and only what had been pushed survived.
That is the same lesson the project is about, learned the expensive way.

610 tests green on `main`, three pages live on GitHub Pages.

## Read it first

Open `blog-preview.html`. That is the post as it will read — same type,
palette and diagrams as the playground. `blog.html` is the Substack paste
buffer and is not meant to be looked at: Substack drops every class and style,
so that file is deliberately bare tags and it looks wrong in a browser.

## Run these before you post

```
python check_claims.py     # every number vs the live ledger
python check_counts.py     # every X post vs the 280 limit
```

Both exit non-zero on a problem. **Run them immediately before you post, not
when you finish writing** — the gap between those two moments is exactly where
drift happens. `check_claims.py` has already caught the event count going
seven → eight → ten → thirteen mid-draft; the number appears in prose, in a
narration script and in a thread, and nothing else would have kept them in
step.

Neither script rewrites your prose. A number that moved usually needs the
sentence around it rewritten, not a digit swapped.

## Post in this order

1. **Substack.** Paste `essay.html` — the ~900-word post, the same shape as
   the AgentRoute launch essay. Everything else links to it, so it goes
   first. Upload the four diagrams where the draft shows their paths:

   | in the draft | replace with |
   |---|---|
   | `diagrams/absent-vs-stale.png` | upload `diagrams/absent-vs-stale.png` |
   | `diagrams/architecture.png` | upload `diagrams/architecture.png` |
   | `diagrams/the-catch.png` | upload `diagrams/the-catch.png` |
   | `diagrams/by-source.png` | upload `diagrams/by-source.png` |

   Then embed `time-to-index-short.mp4` under the playground link near the
   top. `blog.md` / `blog.html` is the long version (~3,000 words, with the
   Artificial Analysis comparison); keep it as a follow-up post or link it
   from the repo.

   `the-catch.png` and `by-source.png` are the two diagrams that are not
   illustrative: every value in them is read out of `ledger/` when they
   render, so they cannot drift from what the repo holds. Re-run
   `make_diagrams.py` immediately before posting, for the same reason you run
   the checks then.
2. **Video.** The primary clip is `time-to-index-short.mp4` (1:31, 1080p;
   a 720p copy sits next to it). Same format as the AgentRoute demo: text on
   screen, no voiceover, an original ambient music bed at the same loudness.
   It reads with the sound off, which is how X and LinkedIn autoplay it.
   Set `thumbnail.png` and put the Substack link in the description.

   On X, attach it to post 1 as native media — at 91 seconds it is under the
   140-second cap on a free account, costs no characters, and autoplay on the
   first post is what carries a thread.

   Rebuild it with `python short/make_short.py`: it reads every number from
   the ledger and refuses to render if a claim on screen no longer holds.

   The 7:27 narrated walkthrough (`time-to-index-launch.mp4`) and the 1:11
   teaser are still here if you want a long-form cut for YouTube.
3. **LinkedIn.** Paste `linkedin.md`. It truncates around 200 characters and
   the first line carries it: *"A search index that is wrong looks exactly like
   one that is fast."*
4. **X.** 21 posts, in order — 1 through 14, with 3b–3c after 3, 4b after 4,
   5b–5c after 5, 6b after 6, and 11b after 11. Posts 13 and 14 carry the
   links.

   The uv row is post 3 and the source-class finding is post 4 — evidence
   before method. On X the concrete result has to land before anyone decides
   whether to keep reading.

Send me the Substack URL afterwards and I'll thread it back through the
README, the video description and both posts.

## If you want a different voiceover

`tts.py` already fills `build/vo-external/` from Google's translate_tts. Any
wav you drop there yourself overrides it, and nothing needs re-recording.

```
python vo.py --script        # prints all 27 lines, each with its filename
# render them anywhere, save as build/vo-external/<beat>-<index>.wav
python make_video.py         # picks them up and re-times everything
```

Delete `build/vo-external/` and re-run `make_video.py` for the silent
captioned cut instead.

`make_video.py` reads the real length of each wav and re-lays the whole script
against the recording that already exists, so a take that runs long pushes the
rest later instead of talking over it. Captions stay; they are timed from the
same placement, so audio and text cannot drift apart.

## The claims you are now making about named products — read before posting

This is stronger than anything earlier drafts said, so it is worth being
deliberate about.

**1. Instances.** Exa (`auto`) and Parallel (`advanced`) both returned `0.12.14`
five minutes after `uv 0.12.15` was released. Parallel (`advanced`) and Brave
(`web`) each produced earlier STALE verdicts on other packages. Every one of
those is backed by a raw payload in `ledger/raw/`.

**2. An ordering.** The copy now says Parallel (`advanced`) *separates* from
Brave (`web`) and from Exa (`auto`) after Holm–Bonferroni correction —
adjusted p 0.018 and 0.036. That is a statistical claim about the speed of
named commercial products, made under your byline. It is correctly done:
pre-registered plan, correction across all six pairs, `tti power` output
quoted rather than paraphrased, and `check_claims.py` recomputes both p-values
from the ledger rather than trusting the sentence.

What keeps it defensible is the caveat that travels with it everywhere it
appears: **all nine of Parallel's fresh answers were Federal Register
documents** — on package registries it was never fresh either — and **the
fastest arm is also tied for the most stale answers**. The copy does not say
"Parallel is faster." It says Parallel reached current answers more often on
the one source class where anything was current at all, and was also among the
most likely to serve a stale one.

If someone from any of these companies replies, that is the ground to stand
on. Don't let a reply pull you into a broader ranking than the one the copy
actually makes.

**Disclosed limitation — the origin control fails on the Federal Register.**
10 of 10 Federal Register origin fetches come back `not_found`: the page is
fetched but the document number is not in what the grader sees. It works on
every npm, PyPI and GitHub event. The copy says this plainly in all three
assets. The fresh Federal Register answers don't depend on it — an index
returning the correct document number is proof the page was live — but the 28
ABSENT verdicts there can't be checked against it. Deliberately **not** fixed
before launch: changing how a control is graded after seeing the results is the
move pre-registration exists to stop. Fix it after, in the open.

**3. The source-class finding** makes no claim about any company, and is the
least contestable result in the pack: 12 of 40 Federal Register answers fresh
at t+5m, 0 of 34 across npm, PyPI and GitHub releases, Fisher p = 0.0003. If
you want to lead with the safest strong claim, lead with that one.
## Two things about the run itself

**The two ERRORs are HTTP 402s** from when the Parallel credit ran out, before
it was topped up. They are recorded as ERROR and excluded from every rate — a
failure caused on our side is not a verdict about the provider. Parallel has
answered normally since.

**Every verdict in the run is at t+5m.** Not by design — by yield. With a
several-hour cron against a ten-minute tolerance, every rung after the first
has roughly a 1-in-30 chance of being graded, so 100 provider squares in this
run were never dispatched. The copy says this plainly in "What it isn't"; the
fix is `deploy/systemd/`, whose README warns about running it alongside the
Actions cron — that would give you two ledgers against one pre-registration.

## The two questions you'll get

**"Why only 35 events, and why is every verdict at t+5m?"** GitHub Actions
asks for a ten-minute cron and delivers one every few hours. An event only
counts if noticed within ten minutes of publication, so most are dropped, and
later rungs almost never land inside their window. Dropping them is correct.
The fix is a box with real timers — `deploy/systemd/`, whose README warns
against running it alongside the Actions cron.

**"How is this different from the Artificial Analysis Search Index?"** Their
axis is answer quality; this one is time to retrievability. The README has a
section on it, fact-checked against their published methodology. The sharp
version: their three component benchmarks are all correctness scores, so a
provider that returned nothing and one that returned yesterday's answer score
identically — and their 25-turn agent loop makes that harder to see, not
easier, because an agent retries its way around an absence but has no signal to
retry on when handed a confident stale answer.

## What's here

| file | what it is |
|---|---|
| `blog-preview.html` | **Read the post here.** Self-contained — fonts and all three diagrams base64'd in. |
| `blog.html` | Paste-into-Substack. Deliberately unstyled; looks wrong in a browser and correct in the editor. |
| `blog.md` | The source. Everything else is generated from it. |
| `linkedin.md` | The LinkedIn post. |
| `x-thread.md` | 21 posts. Counts measured, not estimated. |
| `diagrams/` | Five PNGs at 2x, rendered through the same browser and palette as the playground. `the-catch.png` and `by-source.png` are generated from the ledger. |
| `thumbnail.png` | 1280×720, screenshotted from the live page at 2x rather than drawn. |
| `check_claims.py`, `check_counts.py` | The two pre-flight checks above. |
| `tts.py` | Renders the 27 narration lines to wavs through a reachable endpoint. |
| `make_diagrams.py`, `make_thumb.py`, `md2substack.py`, `make_blogpage.py` | The generators. |

Generators that screenshot the live page need `python -m http.server 8890`
running in `docs/`.
