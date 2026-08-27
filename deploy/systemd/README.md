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
