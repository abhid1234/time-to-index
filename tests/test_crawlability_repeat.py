"""`tti crawlability --repeat`: one request is not a verdict.

`survey` already required agreement across repeat fetches. `crawlability`
did not, and the setup notes told people to run it with `--repeat 3` -- a
flag it did not have. Now it does, with the same rule.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tti import framework as fw
from tti import http as H
from tti.cli import main


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


def _serve(monkeypatch, bodies, postures):
    """raw_get returns bodies in order; profile() returns postures in order."""
    it_b, it_p = iter(bodies), iter(postures)
    monkeypatch.setattr(H, "raw_get", lambda url, **kw: _Resp(next(it_b)))
    monkeypatch.setattr(fw, "profile",
                        lambda html: fw.PageProfile(posture=next(it_p),
                                                    bytes_total=len(html),
                                                    visible_chars=len(html) // 2))
    monkeypatch.setattr(H, "get_text", lambda *a, **kw: "")   # no robots, no llms
    monkeypatch.setattr("time.sleep", lambda s: None)


def test_disagreeing_fetches_yield_no_verdict(monkeypatch, capsys):
    _serve(monkeypatch, ["<html>a</html>", "<html>b</html>"],
           ["server_rendered", "client_shell"])
    assert main(["crawlability", "http://x.test/p", "--repeat", "2"]) == 0
    out = capsys.readouterr().out
    assert "UNSTABLE" in out
    assert "server_rendered / client_shell" in out
    assert "verdict: READABLE" not in out


def test_agreeing_fetches_yield_a_verdict_from_the_richest_body(monkeypatch, capsys):
    calls = []
    real = fw.PageProfile
    def prof(html):
        calls.append(len(html))
        return real(posture="server_rendered", bytes_total=len(html),
                    visible_chars=len(html) // 2)
    monkeypatch.setattr(H, "raw_get",
                        lambda url, **kw: _Resp(["<html>short</html>",
                                                 "<html>much longer body</html>"][len(calls)]))
    monkeypatch.setattr(fw, "profile", prof)
    monkeypatch.setattr(H, "get_text", lambda *a, **kw: "")
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert main(["crawlability", "http://x.test/p", "--repeat", "2", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    row = rows[0] if isinstance(rows, list) else rows["pages"][0]
    assert row["attempts"] == 2
    assert row["postures_seen"] == ["server_rendered", "server_rendered"]
    assert row["bytes"] == len("<html>much longer body</html>")


def test_repeat_one_keeps_the_old_single_fetch_behaviour(monkeypatch, capsys):
    _serve(monkeypatch, ["<html>a</html>"], ["server_rendered"])
    assert main(["crawlability", "http://x.test/p", "--repeat", "1"]) == 0
    assert "UNSTABLE" not in capsys.readouterr().out
