"""SEC EDGAR.

`https://data.sec.gov/submissions/CIK##########.json` lists recent filings
with `acceptanceDateTime` -- the instant EDGAR accepted the document, in
US/Eastern, recorded by the SEC rather than the filer. Dissemination follows
acceptance by minutes for most forms.

This is the highest-stakes source class in the benchmark. A stale answer to
"what did this company most recently file" is the exact failure that makes a
research agent unusable, and the accession number is a near-unique token, so
the grader has almost no false-positive surface here.

SEC requires a declared contact in User-Agent (see their fair-access policy);
set TTI_USER_AGENT before running this collector.
"""

from __future__ import annotations

import datetime as dt
import time

from .. import config, http
from ..models import Event
from . import BaseSource, register

API = "https://data.sec.gov/submissions/CIK{cik:0>10}.json"
EASTERN = dt.timezone(dt.timedelta(hours=-4))   # EDGAR stamps US/Eastern

# Forms worth asking about: periodic reports and material-event disclosures.
FORMS = {"10-K", "10-Q", "8-K", "6-K", "20-F", "S-1", "424B4", "DEF 14A"}


def _accept_ts(s: str) -> float:
    # "2026-08-25T16:31:07.000Z" or "2026-08-25T16:31:07.000-04:00"
    s = s.replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return 0.0
    if d.tzinfo is None:
        d = d.replace(tzinfo=EASTERN)
    return d.timestamp()


class Edgar(BaseSource):
    name = "edgar"
    source_class = "regulatory_filing"
    workers = 5          # SEC fair-access policy caps sustained request rate

    def collect(self, seen):
        return self.fan_out(lambda row: self._one(row, seen),
                            config.watchlist().get("edgar", []))

    def _one(self, row: dict, seen) -> list[Event]:
            out: list[Event] = []
            cik, company = str(row["cik"]), row["name"]
            doc = http.get_json(API.format(cik=cik), timeout=20.0)
            recent = (doc.get("filings") or {}).get("recent") or {}
            forms = recent.get("form") or []
            accns = recent.get("accessionNumber") or []
            accepted = recent.get("acceptanceDateTime") or []
            dates = recent.get("filingDate") or []
            if not forms:
                return out

            # Walk newest-first; take the newest filing of a form we track,
            # and the next filing of the same form as its predecessor.
            idx = next((i for i, f in enumerate(forms) if f in FORMS), None)
            if idx is None:
                return out
            form = forms[idx]
            prev_idx = next((i for i in range(idx + 1, len(forms)) if forms[i] == form), None)

            accn = accns[idx]
            subject = f"{cik}:{form}"
            if seen.get((self.name, subject)) == accn:
                return out

            accn_dashless = accn.replace("-", "")
            prev_accn = accns[prev_idx] if prev_idx is not None else None
            out.append(Event(
                source=self.name,
                source_class=self.source_class,
                subject=subject,
                published_at=_accept_ts(accepted[idx]) if idx < len(accepted) else 0.0,
                discovered_at=time.time(),
                question=(
                    f"What is the SEC accession number of the most recent "
                    f"Form {form} filed by {company}?"
                ),
                answer=accn,
                answer_aliases=[accn, accn_dashless],
                predecessor=prev_accn,
                predecessor_aliases=(
                    [prev_accn, prev_accn.replace("-", "")] if prev_accn else []
                ),
                url=(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                     f"{accn_dashless}/{accn}-index.htm"),
                meta={"company": company, "form": form,
                      "filing_date": dates[idx] if idx < len(dates) else ""},
            ))
            return out


@register("edgar")
def _factory() -> Edgar:
    return Edgar()
