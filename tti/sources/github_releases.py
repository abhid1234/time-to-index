"""GitHub releases.

`published_at` on a release object is set by GitHub when the release is
published, and the previous release of the same repository is the superseded
answer. Unauthenticated this API allows 60 requests/hour, which will not
cover a watchlist; set GITHUB_TOKEN for 5,000/hour.
"""

from __future__ import annotations

import datetime as dt
import time

from .. import config, http
from ..models import Event
from . import BaseSource, register

API = "https://api.github.com/repos/{repo}/releases?per_page=5"


def _iso(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


class GithubReleases(BaseSource):
    name = "github_release"
    source_class = "code_release"
    workers = 4          # unauthenticated GitHub allows 60 requests/hour

    def collect(self, seen):
        headers = {"Accept": "application/vnd.github+json"}
        tok = config.api_key("GITHUB_TOKEN")
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        return self.fan_out(lambda repo: self._one(repo, seen, headers),
                            config.watchlist().get("github", []))

    def _one(self, repo: str, seen, headers) -> list[Event]:
            out: list[Event] = []
            rels = http.get_json(API.format(repo=repo), headers=headers, timeout=15.0)
            live = [r for r in rels if not r.get("draft") and not r.get("prerelease")
                    and r.get("published_at")]
            if not live:
                return out
            live.sort(key=lambda r: _iso(r["published_at"]), reverse=True)
            latest, prev = live[0], (live[1] if len(live) > 1 else None)
            tag = latest.get("tag_name") or ""
            if not tag or seen.get((self.name, repo)) == tag:
                return out

            prev_tag = (prev or {}).get("tag_name")
            bare = tag.lstrip("vV")
            out.append(Event(
                source=self.name,
                source_class=self.source_class,
                subject=repo,
                published_at=_iso(latest["published_at"]),
                discovered_at=time.time(),
                question=(
                    f"What is the most recent release tag of the GitHub "
                    f"repository {repo}?"
                ),
                answer=tag,
                answer_aliases=[t for t in {tag, bare, f"v{bare}"} if len(t) >= 3],
                predecessor=prev_tag,
                predecessor_aliases=(
                    [t for t in {prev_tag, prev_tag.lstrip("vV"), "v" + prev_tag.lstrip("vV")}
                     if len(t) >= 3] if prev_tag else []
                ),
                url=latest.get("html_url", ""),
                meta={"name": latest.get("name") or ""},
            ))
            return out


@register("github_release")
def _factory() -> GithubReleases:
    return GithubReleases()
