"""Waterfall: conservation of cash, zero loss without defaults, the static tranche formula,
seniority, and OC diversion."""
import numpy as np
import pytest

from clo.factor import deterministic_path, simulate_factor
from clo.waterfall import Bucket, CLOStructure, Tranche, run_waterfall

SIZES = [("AAA", 0.62), ("AA", 0.12), ("A", 0.06), ("BBB", 0.06), ("BB", 0.04)]


def make(**kw):
    spreads = kw.pop("spreads", [0.013, 0.018, 0.022, 0.032, 0.060])
    triggers = kw.pop("triggers", [None, 1.20, 1.12, 1.06, 1.03])
    tranches = [Tranche(n, s, sp, tr) for (n, s), sp, tr in zip(SIZES, spreads, triggers)]
    buckets = kw.pop("buckets", [Bucket("B+", 60, -1.9), Bucket("B", 100, -1.8), Bucket("B-", 40, -1.5)])
    base = dict(tranches=tranches, buckets=buckets, base_rate=0.04, loan_spread=0.035,
                senior_fee=0.002, sub_fee=0.003, reinvest_years=5, repay_rate=0.25, horizon=10)
    base.update(kw)
    return CLOStructure(**base)


def const_rec(r):
    return lambda t, p: r


def test_no_defaults_every_class_is_paid_in_full():
    st = make(buckets=[Bucket("B", 200, -np.inf)])
    paths = simulate_factor(50, 10, 0.5, None, np.random.default_rng(0))
    res = run_waterfall(st, paths, 0.2, const_rec(0.7), np.random.default_rng(1))
    assert np.allclose(res.loss, 0.0, atol=1e-12)
    assert res.conservation_error < 1e-12
    assert np.all(res.equity_cash.sum(axis=1) > st.equity_size)


def test_cash_is_conserved_with_defaults():
    st = make()
    paths = simulate_factor(2_000, 10, 0.5, 5.0, np.random.default_rng(2))
    res = run_waterfall(st, paths, 0.25, const_rec(0.6), np.random.default_rng(3))
    assert res.conservation_error < 1e-12
    assert np.all((res.loss >= 0) & (res.loss <= 1))


@pytest.mark.parametrize("n_def", [0, 10, 25, 40, 60, 100, 150, 200])
def test_one_period_static_waterfall_matches_tranche_formula(n_def):
    """No interest, one period: class loss = min(max(L - attach, 0), thickness) / thickness."""
    st = make(spreads=[0.0] * 5, triggers=[None] * 5, base_rate=0.0, loan_spread=0.0,
              senior_fee=0.0, sub_fee=0.0, reinvest_years=0, horizon=1,
              buckets=[Bucket("B", 200, 0.0)])
    rec = 0.4
    override = np.full((1, 1, 1), n_def)
    res = run_waterfall(st, deterministic_path([0.0]), 0.2, const_rec(rec),
                        np.random.default_rng(0), defaults_override=override)
    pool_loss = n_def / 200 * (1 - rec)
    attach = st.equity_size
    for k, (_, size) in reversed(list(enumerate(SIZES))):
        expected = min(max(pool_loss - attach, 0.0), size) / size
        assert res.loss[0, k] == pytest.approx(expected, abs=1e-12)
        attach += size


def test_principal_is_lost_in_order_of_seniority():
    """If a class is left with unpaid balance, every class below it got no principal back.

    (PV losses need not be ordered path by path: a wiped-out BB has collected a higher
    coupon than a wiped-out BBB along the way.)
    """
    st = make()
    paths = simulate_factor(5_000, 10, 0.5, None, np.random.default_rng(4))
    res = run_waterfall(st, paths, 0.3, const_rec(0.5), np.random.default_rng(5))
    assert (res.shortfall[:, :-1] > 1e-9).any()
    for k in range(4):
        hit = res.shortfall[:, k] > 1e-9
        assert np.all(res.shortfall[hit, k + 1:] >= 1.0 - 1e-12)


def test_pv_losses_ordered_without_coupons():
    st = make(spreads=[0.0] * 5, base_rate=0.0, loan_spread=0.0, senior_fee=0.0, sub_fee=0.0,
              triggers=[None] * 5)
    paths = simulate_factor(5_000, 10, 0.5, None, np.random.default_rng(4))
    res = run_waterfall(st, paths, 0.3, const_rec(0.5), np.random.default_rng(5))
    assert np.all(np.diff(res.loss, axis=1) >= -1e-12)


def test_oc_failure_diverts_interest_to_senior_notes():
    """Heavy year-1 defaults: junior OC fails, equity gets nothing, AAA is paid down early."""
    st = make(buckets=[Bucket("B", 200, 0.0)], reinvest_years=0, repay_rate=0.0)
    override = np.zeros((1, 10, 1))
    override[0, 0, 0] = 50                      # 25% of par defaults in year 1
    res = run_waterfall(st, deterministic_path(np.zeros(10)), 0.2, const_rec(0.5),
                        np.random.default_rng(0), defaults_override=override)
    aaa_interest = (0.04 + 0.013) * 0.62
    assert res.oc_fail_years[0, 3] >= 1 and res.oc_fail_years[0, 4] >= 1
    assert res.equity_cash[0, 0] == pytest.approx(0.0, abs=1e-12)
    assert res.cash[0, 0, 0] > aaa_interest + 0.125 + 1e-6   # recovery cash 0.125 + diverted interest
    assert res.conservation_error < 1e-12


def test_linear_runoff_repays_everything_by_the_horizon():
    st = make(buckets=[Bucket("B", 200, -np.inf)], amortization="linear")
    paths = simulate_factor(20, 10, 0.5, None, np.random.default_rng(0))
    res = run_waterfall(st, paths, 0.2, const_rec(0.7), np.random.default_rng(1))
    assert np.allclose(res.loss, 0.0, atol=1e-12)
    assert np.allclose(res.principal_loss, 0.0, atol=1e-12)
    assert np.allclose(res.shortfall, 0.0, atol=1e-12)
    # sequential pay-down after the reinvestment period: AAA is repaid before BB gets principal
    aaa_done = np.argmax(np.cumsum(res.cash[0, :, 0]) > 0.64)
    assert res.cash[0, :aaa_done, 4].max() <= (0.04 + 0.06) * 0.04 + 1e-12


def test_fractional_defaults_match_tranche_formula_in_one_period():
    st = make(spreads=[0.0] * 5, triggers=[None] * 5, base_rate=0.0, loan_spread=0.0,
              senior_fee=0.0, sub_fee=0.0, reinvest_years=0, horizon=1,
              buckets=[Bucket("B", 100, 0.0), Bucket("B-", 100, 0.0)])
    frac = np.array([[[0.10, 0.30]]])          # 20% of the pool defaults
    res = run_waterfall(st, deterministic_path([0.0]), 0.2, const_rec(0.4),
                        np.random.default_rng(0), default_fraction=frac)
    pool_loss = 0.20 * 0.6                     # 12%: equity (10%) gone, BB (10-14%) half gone
    assert res.pool_loss_frac[0] == pytest.approx(pool_loss)
    assert res.principal_loss[0, 4] == pytest.approx(0.5)
    assert res.principal_loss[0, 3] == pytest.approx(0.0, abs=1e-12)
