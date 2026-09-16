# time-to-index — launch pack

Everything for the launch post lives here, **in the repo**. It used to live in
a scratch directory outside it; a container reset took the whole thing —
copy, generators and rendered video — and only what had been pushed survived.
That is the same lesson the project is about, learned the expensive way.

606 tests green on `main`, three pages live on GitHub Pages.

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

1. **Substack.** Paste `blog.html`, then fill the four placeholders below.
   Everything else links to this post, so it goes first.

   | in the draft | replace with |
   |---|---|
   | `diagrams/absent-vs-stale.png` | upload `diagrams/absent-vs-stale.png` |
   | `diagrams/architecture.png` | upload `diagrams/architecture.png` |
   | `diagrams/interval.png` | upload `diagrams/interval.png` |
   | the line reading `>>> EMBED ... HERE <<<` | the video embed, then delete the line |

   The last one is the one that gets published by accident — it is plain text
   in the middle of the closing section and reads as prose if you skim.
2. **Video.** Upload `time-to-index-launch.mp4` (6:15), set `thumbnail.png`,
   put the Substack link in the description. Do this first of the three social
   posts: the LinkedIn copy refers to the video sitting above it.

   **It has captions, not a voiceover.** ElevenLabs is 403 at this sandbox's
   egress proxy, before any key is checked, and Piper's voice models moved to
   HuggingFace, which is blocked too. The captions are not a consolation
   prize — X and LinkedIn autoplay muted, which is how most people will meet
   this, and a screen recording with no words on it is one nobody can follow.
   To add narration later see "If you want a voiceover" below; it does not
   need a re-record.

   On X, attach `time-to-index-teaser.mp4` (1:06, under the 140-second cap on
   a free account) to post 1 as native media. It costs no characters, and
   autoplay on the first post is what carries a thread. The cut is the uv
   0.12.15 row — the finding itself, captioned, self-contained.
3. **LinkedIn.** Paste `linkedin.md`. It truncates around 200 characters and
   the first line carries it: *"A search index that is wrong looks exactly like
   one that is fast."*
4. **X.** 21 posts, in order — 1 through 15, with 6b–6d after 6, 7b after 7,
   and 12b–12c after 12. Posts 14 and 15 carry the links.

Send me the Substack URL afterwards and I'll thread it back through the
README, the video description and both posts.

## If you want a voiceover

The handoff is built and needs no re-record.

```
python vo.py --script        # prints all 26 lines, each with its filename
# render them, save as build/vo-external/<beat>-<index>.wav
python make_video.py         # picks them up and re-times everything
```

`make_video.py` reads the real length of each wav and re-lays the whole script
against the recording that already exists, so a take that runs long pushes the
rest later instead of talking over it. Captions stay; they are timed from the
same placement, so audio and text cannot drift apart.

## The claim you are now making about named products

Posts 6b–6d, the blog section "Then it caught the thing it was built for", and
the LinkedIn post all name **Exa (`auto`)** and **Parallel (`advanced`)** as
having returned `0.12.14` five minutes after `uv 0.12.15` was released, and
name **Parallel (`advanced`)** and **Brave (`web`)** for two earlier STALE
verdicts.

Every one of those sentences is backed by a raw payload in `ledger/raw/`, and
all of them place the caveat in the same breath as the claim: four verdicts, on
three packages, across three arms — not a rate, not a ranking. The dashboard
refuses to rank itself at this n and says so above its own table.

If someone from either company replies, that is the ground you want to be
standing on, and it is the ground the copy actually stands on. Don't let a
reply pull you into defending a ranking you never made.

## Two things about the run itself

**The Parallel credit ran out.** Two calls came back HTTP 402 and are recorded
as ERROR, excluded from every rate — a failure I caused is not a failure of
theirs. But it means Parallel stops contributing data until the account is
topped up, and the post names Parallel. Worth fixing before you publish.

**Every verdict in the run is at t+5m.** Not by design — by yield. With a
several-hour cron against a ten-minute tolerance, every rung after the first
has roughly a 1-in-30 chance of being graded, so 100 provider squares in this
run were never dispatched. The copy says this plainly in "What it isn't"; the
fix is `deploy/systemd/`, whose README warns about running it alongside the
Actions cron — that would give you two ledgers against one pre-registration.

## The two questions you'll get

**"Why only thirteen events?"** GitHub Actions asks for a ten-minute cron and
delivers one every few hours. An event only counts if noticed within ten
minutes of publication, so ~97% are dropped. Dropping them is correct. The fix
is a box with real timers.

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
| `diagrams/` | Three PNGs at 2x, rendered through the same browser and palette as the playground. |
| `thumbnail.png` | 1280×720, screenshotted from the live page at 2x rather than drawn. |
| `check_claims.py`, `check_counts.py` | The two pre-flight checks above. |
| `make_diagrams.py`, `make_thumb.py`, `md2substack.py`, `make_blogpage.py` | The generators. |

Generators that screenshot the live page need `python -m http.server 8890`
running in `docs/`.
