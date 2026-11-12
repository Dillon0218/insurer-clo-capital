"""Step 4: validation against the NAIC factors, NAIC stress results and the historical record."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clo.context import RATINGS, Settings, capital_factors, inputs, load, metrics, run, save

NAIC_LIKE = Settings("naic_like_replication", rho=0.10, phi=0.0, n_corp=824, corp_rec_const=0.48)


def main() -> None:
    cap = capital_factors().set_index("rating")
    res = run(NAIC_LIKE)
    m = metrics(res).set_index(["rating", "instrument"])
    rows = []
    for r in RATINGS:
        k, c = m.loc[(r, "Corporate")], m.loc[(r, "CLO")]
        rp = k["el"] + 0.5 * k["sd"]                    # Moody's Analytics risk premium
        corp_factor = k["q96"] - rp
        clo_factor = c["cte90"] - rp
        rows.append({"rating": r, "designation": cap.loc[r, "designation"],
                     "corp_model_var96_minus_rp": corp_factor, "corp_naic_2021": cap.loc[r, "factor_old"],
                     "corp_ratio": corp_factor / cap.loc[r, "factor_old"],
                     "clo_model_cte90_minus_rp": clo_factor, "clo_naic_2026": cap.loc[r, "factor_new"],
                     "clo_ratio": clo_factor / cap.loc[r, "factor_new"],
                     "corp_pass": (0.5 <= corp_factor / cap.loc[r, "factor_old"] <= 2.0) if r != "AAA" else None,
                     "clo_pass": (0.5 <= clo_factor / cap.loc[r, "factor_new"] <= 2.0) if r in ("BBB", "BB") else None})
    save(pd.DataFrame(rows), "04_naic_replication.csv")
    print(pd.DataFrame(rows).round(4).to_string())

    # V4: severe recession scenario vs NAIC's own YE2019 scenario D results
    rec = load("03_recession.csv")
    stepdown = rec[(rec["instrument"] == "CLO") & rec["recovery"].str.startswith("NAIC")].set_index("rating")
    band = {"AAA": (0, 0.01), "AA": (0, 0.01), "A": (0, 0.01), "BBB": (0.05, 0.40), "BB": (0.80, 1.0)}
    v4 = [{"rating": r, "model_principal_loss": stepdown.loc[r, "principal_loss"],
           "model_pv_loss": stepdown.loc[r, "pv_loss"],
           "naic_principal_loss": stepdown.loc[r, "naic_ye2019_principal_loss"],
           "band_lo": band[r][0], "band_hi": band[r][1],
           "pass": bool(band[r][0] <= stepdown.loc[r, "principal_loss"] < band[r][1] + 1e-12)
           if r in ("AAA", "AA", "A") else bool(band[r][0] <= stepdown.loc[r, "principal_loss"] <= band[r][1])}
          for r in RATINGS]
    pi = inputs().history
    pi = pi[pi["series"] == "naic_cmb_ye2019_scenario_D_pi_loss"].set_index("rating")["rate"]
    v4 = pd.DataFrame(v4)
    v4["naic_principal_and_interest_loss"] = v4["rating"].map(pi)
    save(v4, "04_recession_vs_naic.csv")
    print(pd.DataFrame(v4).round(4).to_string())

    # V5: base-model 10-year probability of principal loss vs the historical record
    base = load("02_loss_metrics.csv")
    base = base[(base["variant"] == "base") & (base["instrument"] == "CLO")].set_index("rating")
    h = inputs().history
    mdy = h[h["series"] == "moodys_clo_10y_cohort_2007_2017"].set_index("rating")["rate"]
    sp1 = h[h["series"] == "sp_clo1_lifetime_defaults"].set_index("rating")
    sp2 = h[h["series"] == "sp_clo2_lifetime_defaults"].set_index("rating")
    mdy_map = {"AAA": ["Aaa"], "AA": ["Aa2"], "A": ["A2"], "BBB": ["Baa2", "Baa3"], "BB": ["Ba2", "Ba3"]}
    v5 = []
    for r in RATINGS:
        hist_max = max([float(mdy[x]) for x in mdy_map[r]] + [float(sp1.loc[r, "rate"]), float(sp2.loc[r, "rate"])])
        v5.append({"rating": r, "model_p_principal_loss_10y": base.loc[r, "p_principal_loss"],
                   "model_p_any_loss_10y": base.loc[r, "p_loss"],
                   "moodys_2007_2017_cohort": "; ".join(f"{x} {float(mdy[x]):.0%}" for x in mdy_map[r]),
                   "sp_clo1_lifetime": f"{int(sp1.loc[r, 'n_defaults'])}/{int(sp1.loc[r, 'n_tranches'])}",
                   "sp_clo2_lifetime": f"{int(sp2.loc[r, 'n_defaults'])}/{int(sp2.loc[r, 'n_tranches'])}",
                   "highest_historical_rate": hist_max,
                   "model_below_history_flag": bool(base.loc[r, "p_principal_loss"] < hist_max)})
    save(pd.DataFrame(v5), "04_history.csv")
    print(pd.DataFrame(v5).round(4).to_string())

    # V6: recoveries the simulation actually applied, default-weighted
    ps = load("02_pool_stats.csv").set_index("variant").loc["base"]
    save(pd.DataFrame([
        {"instrument": "first-lien loan", "model_default_weighted": ps["loan_recovery_default_weighted"],
         "moodys_1982_2009_issuer_weighted": 0.656},
        {"instrument": "senior unsecured bond", "model_default_weighted": ps["bond_recovery_default_weighted"],
         "moodys_1982_2009_issuer_weighted": 0.366}]), "04_recovery_check.csv")


if __name__ == "__main__":
    main()
