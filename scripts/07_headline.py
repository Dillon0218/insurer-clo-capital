"""Step 7: every number quoted in the README, in one table, read from steps 1-5."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clo.context import RATINGS, load, save


def main() -> None:
    rows = []

    def add(key, value, source, note=""):
        rows.append({"key": key, "value": float(value), "source_table": source, "note": note})

    ph = load("00_plan_hash.csv").iloc[0]
    add("plan_unchanged", ph["unchanged"], "00_plan_hash.csv", ph["sha256"])
    cor = load("01_correlation.csv")
    add("rho_gaussian", cor.iloc[0]["value"], "01_correlation.csv")
    add("rho_probit", cor.iloc[1]["value"], "01_correlation.csv")
    add("phi", cor.iloc[2]["value"], "01_correlation.csv")
    add("rho_t_nu10", cor[(cor["parameter"] == "rho") & (cor["nu"] == 10)]["value"].iloc[0], "01_correlation.csv")
    add("rho_t_nu30", cor[(cor["parameter"] == "rho") & (cor["nu"] == 30)]["value"].iloc[0], "01_correlation.csv")
    add("nu_min_feasible", cor[cor["parameter"] == "nu_min_feasible"]["value"].iloc[0], "01_correlation.csv")
    pool = load("01_pool.csv")
    add("pool_avg_annual_pd", (pool["n_loans"] * pool["annual_pd"]).sum() / pool["n_loans"].sum(), "01_pool.csv")
    rr = load("01_recovery_regression.csv").set_index("instrument")
    for k, lab in (("first-lien loan", "loan"), ("senior unsecured bond", "bond")):
        add(f"rec_{lab}_slope", rr.loc[k, "slope_per_unit_default_rate"], "01_recovery_regression.csv")
        add(f"rec_{lab}_r2", rr.loc[k, "r2"], "01_recovery_regression.csv")
        add(f"rec_{lab}_at_2009", rr.loc[k, "fitted_at_2009_sg"], "01_recovery_regression.csv")
    fit = load("01_model_fit_one_year.csv").set_index("source")
    add("model_b_dr_p995_gaussian", fit.loc["model gaussian", "p995"], "01_model_fit_one_year.csv")
    add("hist_b_dr_max", fit.loc["S&P 1981-2020", "max"], "01_model_fit_one_year.csv")

    ps = load("02_pool_stats.csv").set_index("variant")
    for v, lab in (("base", "base"), (ps.index[1], "t10")):
        add(f"pool_loss_mean_{lab}", ps.loc[v, "pool_loss_mean"], "02_pool_stats.csv")
        add(f"pool_loss_p995_{lab}", ps.loc[v, "pool_loss_p995"], "02_pool_stats.csv")
        add(f"pool_default_mean_{lab}", ps.loc[v, "pool_default_mean"], "02_pool_stats.csv")
        add(f"conservation_error_{lab}", ps.loc[v, "conservation_error"], "02_pool_stats.csv")
    add("loan_rec_weighted", ps.loc["base", "loan_recovery_default_weighted"], "02_pool_stats.csv")
    add("bond_rec_weighted", ps.loc["base", "bond_recovery_default_weighted"], "02_pool_stats.csv")

    d = load("02_decisions.csv")
    m = load("02_loss_metrics.csv")
    for v, lab in (("base", "base"), (d["variant"].unique()[1], "t10")):
        dd = d[d["variant"] == v].set_index("rating")
        mm = m[m["variant"] == v].set_index(["rating", "instrument"])
        for r in RATINGS:
            for col in ("el_clo", "el_corp", "es_clo", "es_corp", "tail_multiple", "el_multiple",
                        "relative_coverage_old", "relative_coverage_new", "coverage_corp",
                        "coverage_clo_old", "coverage_clo_new", "factor_old", "factor_new"):
                add(f"{lab}_{r}_{col}", dd.loc[r, col], "02_decisions.csv")
            for kind in ("CLO", "Corporate"):
                for col in ("p_loss", "p_principal_loss", "var", "loss_given_loss", "es_ci_lo", "es_ci_hi"):
                    add(f"{lab}_{r}_{kind}_{col}", mm.loc[(r, kind), col], "02_loss_metrics.csv")

    rec = load("03_recession.csv")
    for _, x in rec.iterrows():
        tag = "naic40" if str(x["recovery"]).startswith("NAIC") else ("loan617" if "61.7" in str(x["recovery"]) else "corp")
        add(f"recession_{tag}_{x['rating']}_principal", x["principal_loss"], "03_recession.csv")
        if np.isfinite(x["pv_loss"]):
            add(f"recession_{tag}_{x['rating']}_pv", x["pv_loss"], "03_recession.csv")
        if "cum_default" in x and np.isfinite(x["cum_default"]):
            add(f"recession_{tag}_{x['rating']}_cum_default", x["cum_default"], "03_recession.csv")

    rep = load("04_naic_replication.csv").set_index("rating")
    for r in RATINGS:
        add(f"v2_corp_ratio_{r}", rep.loc[r, "corp_ratio"], "04_naic_replication.csv")
        add(f"v2_corp_model_{r}", rep.loc[r, "corp_model_var96_minus_rp"], "04_naic_replication.csv")
        add(f"v3_clo_model_{r}", rep.loc[r, "clo_model_cte90_minus_rp"], "04_naic_replication.csv")
        add(f"v3_clo_ratio_{r}", rep.loc[r, "clo_ratio"], "04_naic_replication.csv")
    hist = load("04_history.csv").set_index("rating")
    for r in RATINGS:
        add(f"v5_model_p_principal_{r}", hist.loc[r, "model_p_principal_loss_10y"], "04_history.csv")
    ph2 = load("05_posthoc_moodys_pd.csv")
    for _, x in ph2.iterrows():
        lab = "naiclike" if "NAIC-like" in x["variant"] else "base"
        add(f"posthoc_{lab}_{x['rating']}_clo_model", x["clo_cte90_minus_rp"], "05_posthoc_moodys_pd.csv")
        add(f"posthoc_{lab}_{x['rating']}_clo_ratio", x["clo_ratio"], "05_posthoc_moodys_pd.csv")
        if x["rating"] == "AAA":
            add(f"posthoc_{lab}_pool_loss_mean", x["pool_loss_mean"], "05_posthoc_moodys_pd.csv")

    s = load("05_sensitivity.csv")
    plan = s[s["origin"] == "PLAN"]
    for r in ("A", "BBB", "BB"):
        g = plan[plan["rating"] == r]
        add(f"sens_{r}_tail_multiple_min", g["tail_multiple"].min(), "05_sensitivity.csv")
        add(f"sens_{r}_tail_multiple_max", g["tail_multiple"].max(), "05_sensitivity.csv")
        add(f"sens_{r}_rc_new_min", g["relative_coverage_new"].min(), "05_sensitivity.csv")
        add(f"sens_{r}_rc_new_max", g["relative_coverage_new"].max(), "05_sensitivity.csv")
        add(f"sens_{r}_n_rc_new_below_067", int((g["relative_coverage_new"] < 1 / 1.5).sum()), "05_sensitivity.csv")
        add(f"sens_{r}_n_tail_worse", int((g["tail_multiple"] >= 1.5).sum()), "05_sensitivity.csv")
    add("sens_n_variants", plan["variant"].nunique(), "05_sensitivity.csv")
    for v in plan["variant"].unique():
        g = plan[plan["variant"] == v].set_index("rating")
        key = v.split(" (")[0].split(",")[0].replace(" ", "_").replace("%", "pct")
        for r in ("BBB", "BB"):
            add(f"sens[{key}]_{r}_tail_multiple", g.loc[r, "tail_multiple"], "05_sensitivity.csv", v)
            add(f"sens[{key}]_{r}_rc_new", g.loc[r, "relative_coverage_new"], "05_sensitivity.csv", v)
    sm = load("05_sensitivity_metrics.csv")
    for v in ("BB 3% thick (equity 9%)", "BB 5% thick (equity 7%)"):
        x = sm[(sm["variant"] == v) & (sm["rating"] == "BB") & (sm["instrument"] == "CLO")].iloc[0]
        key = "bb3" if "3%" in v else "bb5"
        add(f"{key}_es", x["es"], "05_sensitivity_metrics.csv")
        add(f"{key}_el", x["el"], "05_sensitivity_metrics.csv")
        add(f"{key}_p_loss", x["p_loss"], "05_sensitivity_metrics.csv")
    out = pd.DataFrame(rows)
    assert out["key"].is_unique, "duplicate headline keys"
    save(out, "00_headline_numbers.csv")
    print(f"{len(rows)} numbers written")


if __name__ == "__main__":
    main()
