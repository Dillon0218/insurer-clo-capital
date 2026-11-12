"""Step 3: the NAIC 'Similar to 2008' severe recession scenario, deterministic."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clo.context import (HORIZON, RATINGS, Settings, calibration, clo_structure, corp_thresholds,
                         inputs, save)
from clo.copula import conditional_pd, factor_from_default_rate
from clo.factor import deterministic_path
from clo.waterfall import run_waterfall

SP_TO_MOODYS = {"BB+": "Ba1", "BB": "Ba2", "BB-": "Ba3", "B+": "B1", "B": "B2", "B-": "B3", "CCC/C": "Caa"}
LOAN_REC_STEPDOWN = 0.40     # NAIC YE2019 report: senior secured loan recovery 64% -> 40%
LOAN_REC_2008 = 0.617        # Moody's 2008 first-lien loan, issuer-weighted trading price
BOND_REC_2008 = 0.338        # Moody's 2008 senior unsecured bond, issuer-weighted trading price


def marginal(cum: np.ndarray) -> np.ndarray:
    prev = np.concatenate([[0.0], cum[:-1]])
    return (cum - prev) / (1.0 - prev)


def main() -> None:
    inp, cal = inputs(), calibration()
    vec = inp.naic_2008.set_index("moodys_rating")[[f"y{t}" for t in range(1, 11)]] / 100.0
    s = Settings("naic_2008")
    st = clo_structure(s, None)
    frac = np.zeros((1, HORIZON, len(st.buckets)))
    for j, b in enumerate(st.buckets):
        frac[0, :, j] = marginal(vec.loc[SP_TO_MOODYS[b.name]].to_numpy())
    path = deterministic_path(np.zeros(HORIZON))
    rows = []
    for label, rec in (("NAIC stepdown recovery 40%", LOAN_REC_STEPDOWN),
                       ("Moody's 2008 loan recovery 61.7%", LOAN_REC_2008)):
        wf = run_waterfall(st, path, cal.rho_gauss, lambda t, p, r=rec: np.full(1, r),
                           np.random.default_rng(0), default_fraction=frac)
        for k, name in enumerate(wf.names):
            rows.append({"scenario": "NAIC Similar to 2008", "recovery": label, "rating": name,
                         "instrument": "CLO", "principal_loss": float(wf.principal_loss[0, k]),
                         "pv_loss": float(wf.loss[0, k]),
                         "oc_fail_years": int(wf.oc_fail_years[0, k])})
        rows.append({"scenario": "NAIC Similar to 2008", "recovery": label, "rating": "pool",
                     "instrument": "collateral", "principal_loss": float(wf.pool_loss_frac[0]),
                     "pv_loss": np.nan, "cum_default": float(wf.pool_default_frac[0])})

    # corporates: factor path backed out from the B2 marginal default rates, base rho
    rho, phi = cal.rho_gauss, cal.phi
    b_bucket = [b for b in st.buckets if b.name == "B"][0]
    m_b2 = marginal(vec.loc["B2"].to_numpy())
    z = factor_from_default_rate(m_b2, b_bucket.threshold, rho)
    save(pd.DataFrame({"year": range(1, HORIZON + 1), "b2_marginal_default": m_b2, "z": z}),
         "03_factor_path.csv")
    spreads = {t.name: t.spread for t in st.tranches}
    for r in RATINGS:
        c = corp_thresholds(r, rho, phi, None)
        y = inp.base_rate + spreads[r]
        surv, loss, cum = 1.0, 0.0, 0.0
        for t in range(HORIZON):
            p = float(conditional_pd(c[t], z[t], 1.0, rho))
            d = surv * p
            loss += d * ((1 + y) ** -t - BOND_REC_2008 * (1 + y) ** -(t + 1))
            cum += d
            surv -= d
        rows.append({"scenario": "NAIC Similar to 2008", "recovery": "Moody's 2008 bond recovery 33.8%",
                     "rating": r, "instrument": "Corporate", "principal_loss": cum * (1 - BOND_REC_2008),
                     "pv_loss": loss, "cum_default": cum})
    naic = inp.history[inp.history["series"] == "naic_cmb_ye2019_scenario_D_principal_loss"].set_index("rating")["rate"]
    df = pd.DataFrame(rows)
    df["naic_ye2019_principal_loss"] = df["rating"].map(naic)
    save(df, "03_recession.csv")
    print(df.round(4).to_string())


if __name__ == "__main__":
    main()
