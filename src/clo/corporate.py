"""Buy-and-hold portfolio of same-rated corporate bonds on the same factor paths.

n identical bullet bonds with an annual coupon y, held to the horizon. A bond that
defaults in year t pays no coupon that year and returns R at the end of it, so per unit
of par its PV loss at the coupon rate is DF(t - 1) - R DF(t) (the coupons it did pay are
worth exactly what they were promised). Survivors repay par at the horizon.
"""
from __future__ import annotations

import numpy as np

from .copula import conditional_pd
from .factor import FactorPaths


def corporate_losses(paths: FactorPaths, rho: float, thresholds: np.ndarray, n_names: int,
                     coupon: float, recovery_fn, rng: np.random.Generator,
                     market_p_fn=None) -> dict[str, np.ndarray]:
    """PV loss of the portfolio per unit of par, plus its cumulative default fraction.

    thresholds: (T,) yearly cohort thresholds from factor.cohort_thresholds.
    recovery_fn(t, market_p) -> recovery per path; market_p_fn(t) gives the market-wide
    conditional default rate that drives recoveries (same index as the loan pool).
    """
    T = len(thresholds)
    n = paths.n
    surv = np.full(n, n_names, dtype=np.int64)
    loss = np.zeros(n)
    cum_def = np.zeros(n)
    for t in range(T):
        p = conditional_pd(thresholds[t], paths.z[:, t], paths.s[:, t], rho)
        d = rng.binomial(surv, p)
        surv -= d
        mp = market_p_fn(t) if market_p_fn is not None else p
        rec = np.asarray(recovery_fn(t, mp), dtype=float) * np.ones(n)
        df_prev = (1.0 + coupon) ** -t
        df_now = (1.0 + coupon) ** -(t + 1)
        loss += d / n_names * (df_prev - rec * df_now)
        cum_def += d / n_names
    return {"loss": loss, "default_frac": cum_def}
