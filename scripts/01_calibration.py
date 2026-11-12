"""Step 1: plan hash, correlation and persistence, recovery link, pool and structure."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clo.context import (HORIZON, Settings, T_GRID, calibration, clo_structure, factor_paths,
                         inputs, plan_hash, pool_buckets, save, t_headline_nu)
from clo.copula import conditional_pd, default_rate_moments, latent_threshold

PLAN_HASH_AT_WRITING = "168d7a88e725df783a3c7a0504321478b3692ce1f2fbf33f1660ae153cd4d319"


def main() -> None:
    h = plan_hash()
    save(pd.DataFrame([{"file": "PLAN.md", "sha256": h, "sha256_when_written": PLAN_HASH_AT_WRITING,
                        "unchanged": h == PLAN_HASH_AT_WRITING,
                        "written": "2026-11-11 22:38 PST", "checked": datetime.now().isoformat(timespec="seconds")}]),
         "00_plan_hash.csv")
    if h != PLAN_HASH_AT_WRITING:
        print("WARNING: PLAN.md has changed since it was written")

    inp, cal = inputs(), calibration()
    rows = [
        {"parameter": "rho", "copula": "gaussian", "nu": np.nan, "value": cal.rho_gauss,
         "method": "method of moments on S&P B one-year default rate: mean 3.34%, SD 3.24% (Table 4)"},
        {"parameter": "rho", "copula": "gaussian", "nu": np.nan, "value": cal.rho_probit,
         "method": "probit estimator: Var(Phi^-1(DR)) / (1 + Var), S&P B annual series 1981-2020"},
        {"parameter": "phi", "copula": "both", "nu": np.nan, "value": cal.phi,
         "method": "lag-1 autocorrelation of Phi^-1(S&P B annual default rate), 1981-2020"},
        {"parameter": "rho", "copula": "naic", "nu": np.nan, "value": 0.10,
         "method": "Academy / Moody's Analytics bond model assumption (independent draw each year)"},
    ]
    for nu in T_GRID:
        sd0 = default_rate_moments(inp.b_mean, 1e-9, nu)[1]
        rows.append({"parameter": "rho", "copula": "t", "nu": nu, "value": cal.rho_t[nu],
                     "method": f"same moment match; SD of one-year B default rate at rho=0 is {sd0:.4f}"
                               + ("" if np.isfinite(cal.rho_t[nu]) else " > 0.0324: infeasible")})
    nu_star = optimize.brentq(lambda nu: default_rate_moments(inp.b_mean, 1e-9, nu)[1] - inp.b_std, 3.0, 30.0)
    rows.append({"parameter": "nu_min_feasible", "copula": "t", "nu": nu_star, "value": nu_star,
                 "method": "nu at which the t copula's one-year B default rate SD equals 3.24% with rho = 0"})
    rows.append({"parameter": "t_headline_nu", "copula": "t", "nu": t_headline_nu(), "value": t_headline_nu(),
                 "method": "smallest nu on the PLAN grid for which the volatility match is feasible (PLAN said 5)"})
    save(pd.DataFrame(rows), "01_correlation.csv")

    rec = inp.recovery_years.set_index("year")
    sg = inp.annual_dr.set_index("year")["speculative_grade"]
    rr = []
    for label, col, (a, b), r2 in (("first-lien loan", "first_lien_bank_loan_pct", cal.rec_loan, cal.rec_loan_r2),
                                   ("senior unsecured bond", "sr_unsecured_bond_pct", cal.rec_bond, cal.rec_bond_r2)):
        y = rec[col].dropna()
        rr.append({"instrument": label, "intercept": a, "slope_per_unit_default_rate": b, "r2": r2,
                   "n_years": len(y), "first_year": int(y.index.min()), "last_year": int(y.index.max()),
                   "mean_recovery_in_sample": float(y.mean() / 100),
                   "fitted_at_long_run_sg_3.71pct": a + b * inp.sg_pd,
                   "fitted_at_2009_sg": a + b * float(sg.loc[2009]) / 100})
    save(pd.DataFrame(rr), "01_recovery_regression.csv")

    _, pool = pool_buckets(200, None)
    save(pool, "01_pool.csv")

    st = clo_structure(Settings(), None)
    out, att = [], st.equity_size
    for t in reversed(st.tranches):
        out.append((t.name, att, att + t.size))
        att += t.size
    ad = {n: (a, d) for n, a, d in out}
    cum_notes = 0.0
    final = []
    for t in st.tranches:
        cum_notes += t.size
        final.append({"tranche": t.name, "size": t.size, "attachment": ad[t.name][0],
                      "detachment": ad[t.name][1], "spread": t.spread, "coupon": st.base_rate + t.spread,
                      "oc_trigger": t.oc_trigger, "initial_oc_ratio": st.collateral_par / cum_notes})
    final.append({"tranche": "Equity", "size": st.equity_size, "attachment": 0.0, "detachment": st.equity_size})
    save(pd.DataFrame(final), "01_structure.csv")
    save(pd.DataFrame([{"base_rate": st.base_rate, "loan_spread": st.loan_spread, "senior_fee": st.senior_fee,
                        "sub_fee": st.sub_fee, "reinvest_years": st.reinvest_years, "horizon": HORIZON,
                        "amortization": st.amortization}]), "01_deal_terms.csv")

    # one-year 'B' default rate in the model vs history (large pool, 100,000 draws)
    b = inp.annual_dr["B"] / 100
    fit = [{"source": "S&P 1981-2020", "mean": float(b.mean()), "sd": float(b.std(ddof=1)),
            "p995": np.nan, "max": float(b.max()), "table4_weighted_mean": inp.b_mean, "table4_sd": inp.b_std}]
    for copula, nu in (("gaussian", None), ("t", t_headline_nu())):
        s = Settings(copula=copula, nu=nu)
        rho, phi, nu_ = s.resolved()
        fp = factor_paths(s, nu_, phi)
        dr = conditional_pd(latent_threshold(inp.b_mean, nu_), fp.z[:, 0], fp.s[:, 0], rho)
        fit.append({"source": f"model {copula}" + (f" nu={nu_:g}" if nu_ else ""), "mean": float(dr.mean()),
                    "sd": float(dr.std()), "p995": float(np.quantile(dr, 0.995)), "max": float(dr.max())})
    save(pd.DataFrame(fit), "01_model_fit_one_year.csv")
    print(pd.read_csv(Path(__file__).resolve().parents[1] / "outputs/tables/01_correlation.csv")[["parameter", "copula", "nu", "value"]])


if __name__ == "__main__":
    main()
