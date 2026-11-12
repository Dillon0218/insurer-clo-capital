"""One-factor Gaussian and t copulas for default (Vasicek framework).

Latent variable for name i in a year:

    Gaussian:  A_i = sqrt(rho) Z + sqrt(1 - rho) e_i
    t:         A_i = (sqrt(rho) Z + sqrt(1 - rho) e_i) / S,   S = sqrt(W / nu),  W ~ chi2(nu)

Z, e_i ~ N(0, 1) independent. The name defaults when A_i < c, with c = Phi^-1(p) or
t_nu^-1(p), so its marginal default probability is p in both cases. Conditional on the
common draws (Z, S) defaults are independent with probability

    p(Z, S) = Phi((c S - sqrt(rho) Z) / sqrt(1 - rho)),

which is all the simulation needs: the number of defaults in a group of n identical
names is Binomial(n, p(Z, S)). S = 1 gives the Gaussian copula.

The common S is what gives the t copula tail dependence: a small W pushes every latent
variable outward at once.
"""
from __future__ import annotations

import numpy as np
from scipy import integrate, optimize, special, stats

# Integrals over Z use probabilists' Gauss-Hermite; over W, adaptive quadrature.
# Both are deterministic, so calibrations are exact functions of their inputs.
_GH_X, _GH_W = np.polynomial.hermite_e.hermegauss(160)
_GH_W = _GH_W / np.sqrt(2.0 * np.pi)


def latent_threshold(p, nu: float | None = None):
    """Default threshold c with P(A < c) = p."""
    p = np.asarray(p, dtype=float)
    return stats.norm.ppf(p) if nu is None else stats.t.ppf(p, nu)


def conditional_pd(c, z, s, rho: float):
    """P(default | Z = z, S = s) for threshold c. Broadcasts over all arguments."""
    return special.ndtr((np.asarray(c) * s - np.sqrt(rho) * z) / np.sqrt(1.0 - rho))


def _over_s(fun, nu: float | None):
    """E[fun(S)] for S = sqrt(W / nu), W ~ chi2(nu); fun(1) when nu is None.

    Adaptive quadrature in W: the integrand has a square-root kink at W = 0 for small
    nu, which fixed Gauss-Laguerre rules handle poorly.
    """
    if nu is None:
        return np.asarray(fun(1.0))
    g = lambda w: fun(np.sqrt(w / nu)) * stats.chi2.pdf(w, nu)
    val, _ = integrate.quad_vec(g, 0.0, np.inf, epsabs=1e-15, epsrel=1e-11, limit=400)
    return np.asarray(val)


def _pd_powers(c: float, rho: float, s) -> np.ndarray:
    """[E_Z p(Z, s), E_Z p(Z, s)^2] for a fixed scale s."""
    cond = conditional_pd(c, _GH_X, s, rho)
    return np.array([_GH_W @ cond, _GH_W @ cond**2])


def expected_conditional_pd(c, rho: float, nu: float | None = None) -> float:
    """E[p(Z, S)]; equals the marginal default probability (a copula marginal check)."""
    return float(_over_s(lambda s: _pd_powers(c, rho, s), nu)[0])


def default_rate_moments(p: float, rho: float, nu: float | None = None) -> tuple[float, float]:
    """Mean and standard deviation of the large-pool annual default rate p(Z, S)."""
    c = float(latent_threshold(p, nu))
    m1, m2 = _over_s(lambda s: _pd_powers(c, rho, s), nu)
    return float(m1), float(np.sqrt(max(m2 - m1 * m1, 0.0)))


def calibrate_rho(mean_dr: float, std_dr: float, nu: float | None = None) -> float:
    """Asset correlation that reproduces the observed volatility of annual default rates.

    Method of moments: hold the marginal default probability at the sample mean and solve
    for the rho at which the model's large-pool default rate has the sample standard
    deviation. For the t copula the same volatility is matched at the given nu, so the
    Gaussian and t versions differ only in tail shape, not in ordinary-year volatility.
    """
    f = lambda r: default_rate_moments(mean_dr, r, nu)[1] - std_dr
    lo, hi = 1e-6, 0.95
    if f(lo) > 0:
        raise ValueError("default rate volatility below the zero-correlation level")
    return float(optimize.brentq(f, lo, hi, xtol=1e-10))


def rho_from_probit(dr: np.ndarray) -> float:
    """Alternative estimator: Var(Phi^-1(DR)) = rho / (1 - rho) under the Gaussian model."""
    y = stats.norm.ppf(np.asarray(dr, dtype=float))
    v = float(np.var(y, ddof=1))
    return v / (1.0 + v)


def vasicek_quantile(p: float, rho: float, q: float) -> float:
    """Closed-form q-quantile of the large homogeneous pool default rate (Vasicek 2002)."""
    return float(stats.norm.cdf((stats.norm.ppf(p) + np.sqrt(rho) * stats.norm.ppf(q)) / np.sqrt(1.0 - rho)))


def vasicek_cdf(x: float, p: float, rho: float) -> float:
    """P(large-pool default rate <= x)."""
    return float(stats.norm.cdf((np.sqrt(1.0 - rho) * stats.norm.ppf(x) - stats.norm.ppf(p)) / np.sqrt(rho)))


def factor_from_default_rate(dr, c: float, rho: float):
    """Invert p(Z, 1) = dr for Z: the Gaussian factor value that produces a default rate."""
    dr = np.asarray(dr, dtype=float)
    return (c - np.sqrt(1.0 - rho) * stats.norm.ppf(dr)) / np.sqrt(rho)
