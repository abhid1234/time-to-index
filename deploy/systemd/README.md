# Running the full ladder

The 5-minute and 15-minute rungs need a runner whose timing is actually
accurate. GitHub Actions cron drifts by minutes to tens of minutes, and
`tti probe` drops any probe that fires more than 10 minutes past its due
time rather than recording it at a rung it did not observe. On a jittery
runner that means the short rungs quietly stop producing data — which the
`rung-slip` count in `tti probe` will tell you about, but which no amount of
retrying will fix.

On any small always-on box:

```bash
sudo cp tti-*.service tti-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tti-discover.timer tti-probe.timer
systemctl list-timers 'tti-*'
```

`AccuracySec=30s` is the line that matters. systemd's default accuracy is one
minute and it deliberately batches timers to let the CPU sleep, which is
exactly the wrong behaviour for a 5-minute rung.

## Overlapping runs

`tti probe` and `tti discover` each take an advisory lock in the run
directory. A second invocation that cannot take it prints why and exits
zero, because it is early rather than broken and a cron wrapper should not
page anyone for it.

systemd will not start a second instance of a `oneshot` unit while the first
is still running, so the timers here are already safe. The lock matters for
plain cron, for a hand-run command during a scheduled run, and for the
GitHub Actions path.

## Turn the hosted cron off when you turn these on

The units above collect into the run directory on the box. They do not push.
`.github/workflows/probe.yml` collects into its own checkout and does push,
committing `ledger/`, `RESULTS.md` and the two pages on every run.

Leave both running and you do not get one run at a better cadence. You get
**two independent runs against one pre-registration**: two ledgers, two sets
of probe IDs, two event streams, and a published site that shows only the
hosted one — which is the starved one, since that is the cadence problem you
moved the runner to solve. Nothing errors. The site just quietly keeps
reporting the smaller of two datasets.

So pick one collector.

**Moving collection to the box (the usual choice).** Disable the hosted
schedule first, then seed the box from the ledger the hosted run has already
built, so the history is continuous rather than restarted:

```bash
# 1. stop the hosted collector — comment out the `schedule:` block in
#    .github/workflows/probe.yml, keeping `workflow_dispatch:` so the
#    workflow can still be run by hand. Commit and push that first.

# 2. seed the box from the committed ledger
git clone https://github.com/<you>/time-to-index /opt/time-to-index
cd /opt/time-to-index
mkdir -p runs/raw
cp ledger/*.jsonl ledger/prereg.lock runs/
for f in ledger/raw/*.tar.gz; do tar -xzf "$f" -C runs; done

# 3. keep the plan lock. A fresh one silently re-registers the plan and
#    `tti verify` can no longer detect drift against what was promised.
tti verify        # must pass before the first probe, not after
```

Publishing from the box is then yours to arrange — a `tti report` plus a
commit and push on a third timer, or an rsync to wherever the pages are
served. The workflow's `Persist ledger` and `Commit` steps are the reference
for what has to be written back: the JSONL files, `prereg.lock`, and one
gzipped archive per run of the raw payloads that run produced.

**Keeping collection hosted.** Then don't enable these timers. You keep the
~3% event yield that a several-hour cron delivers, and the 5m and 15m rungs
stay mostly unmeasured. That is a legitimate choice for a demonstration and a
bad one for a result.

Whichever you pick, `tti status` on the collector is the check: if two
machines both report recent probes, you have the split-brain above.
