"""CLO cash flow waterfall on an annual grid, vectorised across scenarios.

Collateral: rating buckets of identical loans. Each year, given the common factor,
defaults in a bucket are Binomial(performing loans, p(Z, S)). Defaulted loans pay no
interest that year and return recovery cash at year end.

Order of a payment date (annual):
  1. Defaults; recovery cash; interest on surviving par; after the reinvestment period,
     repayments of a fixed fraction of performing par; in the final year the remaining
     performing loans are sold at the liquidation price.
  2. Interest waterfall: senior fees, then each class in order of seniority. Unpaid
     interest is capitalised (added to the class balance) and keeps accruing at the
     class coupon. After each class's interest, that class's overcollateralisation (OC)
     test: (performing par + principal cash) / (balances of this class and all above).
     If it is below the trigger, the remaining interest pays down notes from the top
     until the test is cured or interest runs out. Then the subordinated fee; the rest
     goes to equity.
  3. Principal: inside the reinvestment period, principal cash buys new loans at par
     in the target mix, and defaulted names are replaced so the loan count stays
     constant. After it, principal pays the notes sequentially, then equity.

A class's loss is 1 - PV(cash received) / initial balance, discounted at its own coupon.
That is zero whenever everything promised is eventually paid, whatever the timing, and
otherwise equals the present value of what was missed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .copula import conditional_pd
from .factor import FactorPaths


@dataclass(frozen=True)
class Tranche:
    name: str
    size: float              # fraction of initial collateral par
    spread: float            # coupon spread over the base rate
    oc_trigger: float | None = None   # OC test after this class's interest, if any


@dataclass(frozen=True)
class Bucket:
    name: str
    n_loans: int
    threshold: float         # latent default threshold for one year (managed pool)


@dataclass
class CLOStructure:
    tranches: list[Tranche]
    buckets: list[Bucket]
    base_rate: float
    loan_spread: float
    senior_fee: float = 0.0      # per year, on collateral par at the start of the year
    sub_fee: float = 0.0
    reinvest_years: int = 5
    repay_rate: float = 0.0      # fraction of performing par repaid each year after reinvestment
    amortization: str = "rate"   # "rate": repay_rate per year; "linear": even run-off to the horizon
    horizon: int = 10
    liquidation_price: float = 1.0
    collateral_par: float = 1.0

    @property
    def equity_size(self) -> float:
        return self.collateral_par - sum(t.size for t in self.tranches)

    @property
    def mix(self) -> np.ndarray:
        n = np.array([b.n_loans for b in self.buckets], dtype=float)
        return n / n.sum()

    def coupons(self) -> np.ndarray:
        return np.array([self.base_rate + t.spread for t in self.tranches])


@dataclass
class WaterfallResult:
    loss: np.ndarray                 # (n, K) PV loss per unit of initial class balance
    cash: np.ndarray                 # (n, T, K) cash received by each class
    equity_cash: np.ndarray          # (n, T)
    pool_default_frac: np.ndarray    # (n,) cumulative defaulted par / initial par
    pool_loss_frac: np.ndarray       # (n,) cumulative (1 - R) x defaulted par / initial par
    oc_fail_years: np.ndarray        # (n, K) years in which each class's OC test failed
    shortfall: np.ndarray            # (n, K) balance left unpaid at the horizon / initial balance
    principal_loss: np.ndarray       # (n, K) 1 - principal repaid / initial balance, floored at 0
    conservation_error: float        # max |cash in - cash out| over all years and paths
    names: list[str] = field(default_factory=list)


def run_waterfall(structure: CLOStructure, paths: FactorPaths, rho: float,
                  recovery_fn, rng: np.random.Generator,
                  defaults_override: np.ndarray | None = None,
                  default_fraction: np.ndarray | None = None) -> WaterfallResult:
    """Simulate the deal on each factor path.

    recovery_fn(t, p_buckets) -> recovery rate per path for year t, given the
    conditional default probabilities of the buckets (n, B).
    defaults_override: optional (n, T, B) default counts (used by tests).
    default_fraction: optional (n, T, B) share of each bucket's performing par that defaults
        in each year (deterministic scenarios; loan counts are then ignored).
    """
    st = structure
    n, T = paths.n, st.horizon
    if paths.horizon < T:
        raise ValueError("factor paths shorter than the deal horizon")
    K, B = len(st.tranches), len(st.buckets)
    c_b = np.array([b.threshold for b in st.buckets])
    n0 = np.array([b.n_loans for b in st.buckets], dtype=np.int64)
    mix = st.mix
    coupons = st.coupons()
    loan_rate = st.base_rate + st.loan_spread

    par = np.tile(mix * st.collateral_par, (n, 1))          # performing par by bucket
    cnt = np.tile(n0, (n, 1))                                 # performing loans by bucket
    bal = np.tile(np.array([t.size for t in st.tranches]), (n, 1))
    cash = np.zeros((n, T, K))
    eq_cash = np.zeros((n, T))
    cum_def = np.zeros(n)
    cum_loss = np.zeros(n)
    oc_fail = np.zeros((n, K), dtype=np.int64)
    prin_paid = np.zeros((n, K))
    max_err = 0.0
    triggers = [t.oc_trigger for t in st.tranches]

    for t in range(T):
        par_start = par.sum(axis=1)
        p = conditional_pd(c_b[None, :], paths.z[:, t:t + 1], paths.s[:, t:t + 1], rho)
        if default_fraction is not None:
            dpar = par * default_fraction[:, t, :]
            par = par - dpar
        else:
            if defaults_override is not None:
                d = np.minimum(defaults_override[:, t, :].astype(np.int64), cnt)
            else:
                d = rng.binomial(cnt, p)
            per_loan = np.divide(par, cnt, out=np.zeros_like(par), where=cnt > 0)
            dpar = d * per_loan
            par = par - dpar
            cnt = cnt - d
        rec = np.asarray(recovery_fn(t, p), dtype=float) * np.ones(n)
        dtot = dpar.sum(axis=1)
        rec_cash = rec * dtot
        cum_def += dtot
        cum_loss += (1.0 - rec) * dtot

        interest = loan_rate * par.sum(axis=1)
        principal = rec_cash.copy()
        if t >= st.reinvest_years:
            frac = 1.0 / (T - t) if st.amortization == "linear" else st.repay_rate
            repay = frac * par
            par = par - repay
            principal += repay.sum(axis=1)
        if t == T - 1:
            principal += st.liquidation_price * par.sum(axis=1)
            par = np.zeros_like(par)
        cash_in = interest + principal

        # interest waterfall
        avail = interest.copy()
        fee = np.minimum(avail, st.senior_fee * par_start)
        avail -= fee
        paid_out = fee.copy()
        collateral = par.sum(axis=1) + principal          # OC numerator
        for k in range(K):
            due = coupons[k] * bal[:, k]
            pay = np.minimum(avail, due)
            avail -= pay
            cash[:, t, k] += pay
            paid_out += pay
            bal[:, k] += due - pay                         # capitalise any shortfall
            trig = triggers[k]
            if trig is not None:
                den = bal[:, :k + 1].sum(axis=1)
                fail = collateral < trig * den
                oc_fail[:, k] += fail
                need = np.where(fail, den - collateral / trig, 0.0)
                divert = np.minimum(avail, need)
                avail -= divert
                paid_out += divert
                for j in range(k + 1):                     # pay down from the top
                    x = np.minimum(divert, bal[:, j])
                    bal[:, j] -= x
                    cash[:, t, j] += x
                    prin_paid[:, j] += x
                    divert -= x
        sub = np.minimum(avail, st.sub_fee * par_start)
        avail -= sub
        paid_out += sub
        eq_cash[:, t] += avail
        paid_out += avail

        # principal waterfall
        if t < st.reinvest_years and t < T - 1:
            par = par + principal[:, None] * mix[None, :]
            cnt = np.tile(n0, (n, 1))
            paid_out += principal
        else:
            rem = principal.copy()
            for k in range(K):
                x = np.minimum(rem, bal[:, k])
                bal[:, k] -= x
                cash[:, t, k] += x
                prin_paid[:, k] += x
                rem -= x
                paid_out += x
            eq_cash[:, t] += rem
            paid_out += rem
        max_err = max(max_err, float(np.max(np.abs(cash_in - paid_out))))

    disc = (1.0 + coupons[None, :]) ** -(np.arange(1, T + 1)[:, None])   # (T, K)
    pv = np.einsum("ntk,tk->nk", cash, disc)
    size = np.array([tr.size for tr in st.tranches])
    loss = np.clip(1.0 - pv / size[None, :], 0.0, 1.0)
    return WaterfallResult(loss=loss, cash=cash, equity_cash=eq_cash,
                           pool_default_frac=cum_def / st.collateral_par,
                           pool_loss_frac=cum_loss / st.collateral_par,
                           oc_fail_years=oc_fail, shortfall=bal / size[None, :],
                           principal_loss=np.clip(1.0 - prin_paid / size[None, :], 0.0, 1.0),
                           conservation_error=max_err,
                           names=[tr.name for tr in st.tranches])
