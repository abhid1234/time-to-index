"""arXiv.

The Atom API returns `published` for each entry, set at announcement. There
is no supersession here -- a new paper does not make an old paper's identifier
wrong -- so arXiv events contribute to time-to-index and recall but are
excluded from the staleness denominator. That exclusion is enforced by
`Event.measures_staleness`, not by convention.

The identifier (2608.01234) is the answer token: distinctive enough that a
match is real evidence the page was retrieved.
"""

from __future__ import annotations

import datetime as dt
import re
import time
import xml.etree.ElementTree as ET

from .. import config, http
from ..models import Event
from . import BaseSource, register

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}
ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


class ArXiv(BaseSource):
    name = "arxiv"
    source_class = "preprint"
    workers = 2          # arXiv asks for no more than one request every 3s

    def collect(self, seen):
        return self.fan_out(lambda cat: self._one(cat, seen),
                            config.watchlist().get("arxiv", []))

    def _one(self, category: str, seen) -> list[Event]:
            out: list[Event] = []
            xml = http.get_text(API, params={
                "search_query": f"cat:{category}",
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": "5",
            }, timeout=25.0)
            root = ET.fromstring(xml)

            for entry in root.findall("a:entry", NS):
                raw_id = (entry.findtext("a:id", "", NS) or "")
                m = ID_RE.search(raw_id)
                title = " ".join((entry.findtext("a:title", "", NS) or "").split())
                pub = entry.findtext("a:published", "", NS)
                if not (m and title and pub):
                    continue
                ident = m.group(1)
                if seen.get((self.name, ident)):
                    continue
                out.append(Event(
                    source=self.name,
                    source_class=self.source_class,
                    subject=ident,
                    published_at=dt.datetime.fromisoformat(
                        pub.replace("Z", "+00:00")).timestamp(),
                    discovered_at=time.time(),
                    question=(
                        f'What is the arXiv identifier of the paper titled '
                        f'"{title}"?'
                    ),
                    answer=ident,
                    answer_aliases=[ident, f"arXiv:{ident}", f"abs/{ident}"],
                    predecessor=None,
                    url=f"https://arxiv.org/abs/{ident}",
                    meta={"category": category, "title": title},
                ))
            return out


@register("arxiv")
def _factory() -> ArXiv:
    return ArXiv()
