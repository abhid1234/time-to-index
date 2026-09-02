"""Federal Register.

`publication_date` is the date of the printed issue and `document_number`
(2026-12345) is assigned at scheduling. Documents appear on the public
inspection desk before publication, so this source has the useful property
that the fact exists on the open web at a time the government itself
publishes, with no vendor in between.

No supersession, so like arXiv this contributes to time-to-index and recall
only.

A caveat that bounds what this source can say. `published_at` is anchored to
the printed issue's morning; the document was on the public-inspection desk
before that, sometimes the previous business day. A provider that indexed the
public-inspection copy would look faster than the issue time implies. The
direction of that error is known -- it flatters providers, never penalises
them -- and it is stated here rather than corrected, because the correction
would need the public-inspection endpoint and a second timestamp per event.
"""

from __future__ import annotations

import datetime as dt
import time

from .. import http
from ..models import Event
from . import BaseSource, register
from .tz import eastern

API = "https://www.federalregister.gov/api/v1/documents.json"


class FederalRegister(BaseSource):
    name = "federal_register"
    source_class = "gov_publication"

    def collect(self, seen):
        return self.fan_out(lambda _: self._one(seen), [API])

    def _one(self, seen) -> list[Event]:
        doc = http.get_json(API, params={
                "order": "newest",
                "per_page": "10",
                "fields[]": ["document_number", "title", "publication_date",
                         "html_url", "agencies", "type"],
        }, timeout=20.0)

        out: list[Event] = []
        for r in doc.get("results", []):
            num = r.get("document_number")
            title = " ".join((r.get("title") or "").split())
            date = r.get("publication_date")
            if not (num and title and date) or seen.get((self.name, num)):
                continue
            agency = ""
            ags = r.get("agencies") or []
            if ags and isinstance(ags[0], dict):
                agency = ags[0].get("name") or ""
            # 8 a.m. Eastern on the issue date, in Eastern time -- not a fixed
            # UTC hour, which was wrong by one for five months of the year.
            published = dt.datetime.strptime(date, "%Y-%m-%d").replace(
                hour=8, tzinfo=eastern()).timestamp()
            out.append(Event(
                source=self.name,
                source_class=self.source_class,
                subject=num,
                published_at=published,
                discovered_at=time.time(),
                question=(
                    f'What is the Federal Register document number for the '
                    f'{r.get("type") or "document"} titled "{title}"'
                    + (f" from the {agency}?" if agency else "?")
                ),
                answer=num,
                answer_aliases=[num],
                predecessor=None,
                url=r.get("html_url", ""),
                origins=[u for u in (r.get("html_url"),
                         f"https://www.federalregister.gov/api/v1/documents/{num}.json")
                         if u],
                meta={"agency": agency, "title": title, "type": r.get("type") or ""},
            ))
        return out


@register("federal_register")
def _factory() -> FederalRegister:
    return FederalRegister()
