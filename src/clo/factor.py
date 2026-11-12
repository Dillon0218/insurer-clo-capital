"""The common economic factor, year by year, and default thresholds for static cohorts.

Z_t is a stationary AR(1) with unit variance, so every single year has exactly the
one-factor copula above, and persistence phi makes bad years cluster the way 2001-02
and 2008-09 did. For the t copula each year also gets its own mixing draw S_t.

A buy-and-hold bond portfolio is a static cohort: name by name it must reproduce a
published cumulative default curve P(1), ..., P(T). With phi > 0 the survivors of a bad
year are more likely to face another bad year, so the naive yearly thresholds
Phi^-1(hazard) would miss the curve. `cohort_thresholds` solves for the yearly
thresholds that hit it exactly on a large calibration sample of factor paths.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import optimize, stats

from .copula import conditional_pd


@dataclass(frozen=True)
class FactorPaths:
    z: np.ndarray        # (n, T) systematic factor
    s: np.ndarray        # (n, T) t-copula scale sqrt(W / nu); ones for Gaussian
    nu: float | None

    @property
    def n(self) -> int:
        return self.z.shape[0]

    @property
    def horizon(self) -> int:
        return self.z.shape[1]


def simulate_factor(n: int, horizon: int, phi: float, nu: float | None,
                    rng: np.random.Generator) -> FactorPaths:
    e = rng.standard_normal((n, horizon))
    z = np.empty_like(e)
    z[:, 0] = e[:, 0]
    k = np.sqrt(1.0 - phi * phi)
    for t in range(1, horizon):
        z[:, t] = phi * z[:, t - 1] + k * e[:, t]
    if nu is None:
        s = np.ones_like(z)
    else:
        s = np.sqrt(rng.chisquare(nu, size=(n, horizon)) / nu)
    return FactorPaths(z=z, s=s, nu=nu)


def deterministic_path(z: np.ndarray) -> FactorPaths:
    """A single Gaussian path (used for the historical replay)."""
    z = np.atleast_2d(np.asarray(z, dtype=float))
    return FactorPaths(z=z, s=np.ones_like(z), nu=None)


def cohort_thresholds(cum_pd: np.ndarray, paths: FactorPaths, rho: float) -> np.ndarray:
    """Yearly thresholds c_t so a large static cohort defaults exactly on cum_pd.

    Solves E[S_{t-1} p_t(c_t)] = P(t) - P(t-1) sequentially, where S_{t-1} is the
    large-pool surviving fraction along each calibration path.
    """
    cum_pd = np.asarray(cum_pd, dtype=float)
    T = len(cum_pd)
    if T > paths.horizon:
        raise ValueError("calibration paths shorter than the default curve")
    surv = np.ones(paths.n)
    c = np.empty(T)
    prev = 0.0
    for t in range(T):
        target = cum_pd[t] - prev
        if target <= 0.0:
            c[t] = -np.inf
            prev = cum_pd[t]
            continue
        z, s = paths.z[:, t], paths.s[:, t]
        f = lambda x: float(np.mean(surv * conditional_pd(x, z, s, rho))) - target
        lo, hi = -12.0, 6.0
        while f(lo) > 0 and lo > -1e6:      # t copula with small nu: very heavy left tail
            lo *= 4.0
        c[t] = optimize.brentq(f, lo, hi, xtol=1e-12)
        surv = surv * (1.0 - conditional_pd(c[t], z, s, rho))
        prev = cum_pd[t]
    return c


def ar1_from_probit(dr: np.ndarray) -> float:
    """Lag-1 autocorrelation of Phi^-1(default rate): the persistence of the factor."""
    y = stats.norm.ppf(np.asarray(dr, dtype=float))
    y = y - y.mean()
    return float(np.sum(y[1:] * y[:-1]) / np.sum(y * y))
