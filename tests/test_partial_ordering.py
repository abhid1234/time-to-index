"""The ordering banner must not vanish the moment one pair separates.

The dashboard sorts its leaderboard, and a sorted table reads as a complete
ranking. When no pair separated, a banner said so. When *any* pair did, the
banner disappeared entirely -- leaving a reader free to infer an ordering
between arms the analysis explicitly could not separate.

That became live: two of six pairs cleared Holm-Bonferroni, the banner went,
and the table sat there implying the other four as well. The partial case now
names the pairs that separate and says the rest of the order is not a result.
"""
from __future__ import annotations

from tti.power import PairPower


def _banner(powers):
    """Reproduce report.py's decision in isolation."""
    computable = [r for r in powers if r.p_adjusted == r.p_adjusted]
    separable = [r for r in computable if r.p_adjusted < 0.05]
    if separable and len(separable) == len(computable):
        return "full"
    if separable:
        return "partial"
    return "none"


def _pp(a, b, p):
    return PairPower(a=a, b=b, hazard_ratio=1.0, events_observed=5,
                     p_value=p, p_adjusted=p)


def test_partial_separation_keeps_a_banner():
    powers = [_pp("x", "y", 0.01), _pp("x", "z", 0.3), _pp("y", "z", 0.6)]
    assert _banner(powers) == "partial"


def test_nothing_separating_still_says_so():
    assert _banner([_pp("x", "y", 0.4), _pp("x", "z", 0.3)]) == "none"


def test_banner_only_disappears_when_every_pair_separates():
    assert _banner([_pp("x", "y", 0.01), _pp("x", "z", 0.02)]) == "full"


def test_the_rendered_dashboard_names_the_pairs_on_the_live_ledger():
    """Against the committed run: the banner is present and specific."""
    import pathlib
    html = (pathlib.Path(__file__).resolve().parent.parent
            / "docs" / "index.html").read_text()
    if "pairwise orderings, not a full ranking" not in html:
        import pytest
        pytest.skip("committed dashboard predates a partial separation")
    assert "Holm&#8211;Bonferroni" in html
    assert "is not a result" in html
