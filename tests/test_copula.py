"""Copula marginals, the Vasicek closed form, and the correlation calibration."""
import numpy as np
import pytest
from scipy import stats

from clo.copula import (calibrate_rho, conditional_pd, default_rate_moments,
                        expected_conditional_pd, factor_from_default_rate,
                        latent_threshold, rho_from_probit, vasicek_cdf, vasicek_quantile)
from clo.factor import ar1_from_probit, cohort_thresholds, simulate_factor


@pytest.mark.parametrize("nu", [None, 4.0, 10.0])
@pytest.mark.parametrize("p", [0.0005, 0.03, 0.20])
def test_marginal_default_probability_by_quadrature(p, nu):
    """Integrating the conditional PD over the factor returns the marginal PD exactly."""
    c = latent_threshold(p, nu)
    assert expected_conditional_pd(c, 0.25, nu) == pytest.approx(p, rel=1e-6)


@pytest.mark.parametrize("nu", [None, 5.0])
def test_marginal_default_probability_name_level(nu):
    """Simulate the latent variables name by name: each name defaults with probability p."""
    rng = np.random.default_rng(1)
    p, rho, n_scen, n_names = 0.04, 0.20, 200_000, 5
    z = rng.standard_normal((n_scen, 1))
    e = rng.standard_normal((n_scen, n_names))
    a = np.sqrt(rho) * z + np.sqrt(1 - rho) * e
    if nu is not None:
        a = a / np.sqrt(rng.chisquare(nu, size=(n_scen, 1)) / nu)
    freq = (a < latent_threshold(p, nu)).mean(axis=0)
    se = np.sqrt(p * (1 - p) / n_scen)
    assert np.all(np.abs(freq - p) < 4 * se)


def test_t_copula_has_more_joint_tail_defaults():
    """Same marginal and correlation: the t copula puts more mass on many defaults at once."""
    p, rho = 0.03, 0.15
    q_g = vasicek_quantile(p, rho, 0.995)
    rng = np.random.default_rng(2)
    z = rng.standard_normal(400_000)
    s = np.sqrt(rng.chisquare(4.0, 400_000) / 4.0)
    dr_t = conditional_pd(latent_threshold(p, 4.0), z, s, rho)
    assert np.quantile(dr_t, 0.995) > q_g


def test_vasicek_quantile_matches_large_pool_simulation():
    """Known closed form: the q-quantile of a large homogeneous pool's default rate."""
    p, rho, q = 0.03, 0.12, 0.995
    rng = np.random.default_rng(3)
    z = rng.standard_normal(400_000)
    dr = conditional_pd(stats.norm.ppf(p), z, 1.0, rho)
    sim = np.quantile(dr, q)
    closed = vasicek_quantile(p, rho, q)
    assert sim == pytest.approx(closed, rel=0.01)
    assert vasicek_cdf(closed, p, rho) == pytest.approx(q, abs=1e-10)


def test_vasicek_quantile_known_value():
    """Hand-checkable case: p = 1%, rho = 20%, q = 99.9% (Basel IRB worst case default rate).

    Phi^-1(0.01) = -2.326348, Phi^-1(0.999) = 3.090232;
    (-2.326348 + sqrt(0.2) * 3.090232) / sqrt(0.8) = -1.055820 -> Phi = 0.145525.
    """
    assert vasicek_quantile(0.01, 0.20, 0.999) == pytest.approx(0.145525, abs=2e-6)


def test_binomial_pool_matches_vasicek_variance():
    """Finite pool default rate variance = Vasicek variance + binomial noise p(1-p)... term."""
    p, rho, n_names = 0.04, 0.10, 200
    mean, std = default_rate_moments(p, rho)
    rng = np.random.default_rng(4)
    z = rng.standard_normal(300_000)
    cp = conditional_pd(stats.norm.ppf(p), z, 1.0, rho)
    dr = rng.binomial(n_names, cp) / n_names
    expected_var = std**2 + (mean - (std**2 + mean**2)) / n_names
    assert dr.mean() == pytest.approx(p, rel=0.01)
    assert dr.var() == pytest.approx(expected_var, rel=0.02)


@pytest.mark.parametrize("nu", [None, 6.0])
def test_calibrate_rho_round_trip(nu):
    p, rho = 0.035, 0.18
    m, s = default_rate_moments(p, rho, nu)
    assert m == pytest.approx(p, rel=1e-6)
    assert calibrate_rho(m, s, nu) == pytest.approx(rho, rel=1e-6)


def test_probit_estimator_and_ar1_recover_simulated_parameters():
    rng = np.random.default_rng(5)
    p, rho, phi = 0.04, 0.15, 0.5
    fp = simulate_factor(1, 40_000, phi, None, rng)
    dr = conditional_pd(stats.norm.ppf(p), fp.z[0], 1.0, rho)
    assert rho_from_probit(dr) == pytest.approx(rho, rel=0.03)
    assert ar1_from_probit(dr) == pytest.approx(phi, abs=0.02)


def test_factor_from_default_rate_inverts_conditional_pd():
    c, rho = stats.norm.ppf(0.03), 0.2
    dr = np.array([0.005, 0.03, 0.11])
    z = factor_from_default_rate(dr, c, rho)
    assert conditional_pd(c, z, 1.0, rho) == pytest.approx(dr, rel=1e-10)


def test_factor_is_stationary_unit_variance():
    rng = np.random.default_rng(6)
    fp = simulate_factor(200_000, 10, 0.6, None, rng)
    assert np.allclose(fp.z.std(axis=0), 1.0, atol=0.01)
    assert np.corrcoef(fp.z[:, 3], fp.z[:, 4])[0, 1] == pytest.approx(0.6, abs=0.01)


@pytest.mark.parametrize("nu", [None, 5.0])
def test_cohort_thresholds_reproduce_cumulative_curve(nu):
    """With persistent factors, solved thresholds still hit the cumulative default curve."""
    rng = np.random.default_rng(7)
    cum = np.array([0.01, 0.025, 0.045, 0.065, 0.085])
    rho, phi = 0.15, 0.5
    cal = simulate_factor(200_000, 5, phi, nu, rng)
    c = cohort_thresholds(cum, cal, rho)
    test = simulate_factor(200_000, 5, phi, nu, np.random.default_rng(8))
    surv = np.ones(test.n)
    for t in range(5):
        surv = surv * (1 - conditional_pd(c[t], test.z[:, t], test.s[:, t], rho))
        assert 1 - surv.mean() == pytest.approx(cum[t], rel=0.01)
