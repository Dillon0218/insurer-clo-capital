"""Capital factor lookup: the 2021 and 2026 tables and the thin-tranche surcharge rule."""
import pytest

from clo.context import capital_factors


def test_factors_match_naic_tables():
    f = capital_factors().set_index("rating")
    assert f.loc["AAA", "factor_old"] == pytest.approx(0.00158)
    assert f.loc["BBB", "factor_old"] == pytest.approx(0.01523)
    assert f.loc["BBB", "factor_new"] == pytest.approx(0.03240)
    assert f.loc["BB", "factor_new_base"] == pytest.approx(0.25150)


def test_thin_surcharge_applies_only_at_2c_or_below_and_4pct_or_thinner():
    base = capital_factors().set_index("rating")
    assert base.loc["BB", "thin_surcharge"] == pytest.approx(0.1177)      # 3.B, 4% thick
    assert base.loc["BBB", "thin_surcharge"] == 0.0                         # 2.B is above 2.C
    thick = capital_factors({"BB": 0.05}).set_index("rating")
    assert thick.loc["BB", "thin_surcharge"] == 0.0
    thin_bbb = capital_factors({"BBB": 0.03}).set_index("rating")
    assert thin_bbb.loc["BBB", "thin_surcharge"] == 0.0
