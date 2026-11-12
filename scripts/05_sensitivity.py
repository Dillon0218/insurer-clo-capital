"""Step 5: the sensitivities listed in PLAN section 7, each changing one input from the base.

Also one diagnostic that is NOT in the PLAN (added after the V3 validation failed, and
labelled as such everywhere): the NAIC-like settings with the loan pool's default rates taken
from the NAIC 'Historical' vectors, which are built on Moody's data, instead of S&P's.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import importlib

from clo import context as C
from clo.context import RATINGS, Settings, calibration, capital_factors, metrics, run, save

def decisions(m: pd.DataFrame, sizes: dict | None) -> pd.DataFrame:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    mod = importlib.import_module("02_simulation")
    return mod.decisions(m, capital_factors(sizes))


def variants() -> list[tuple[Settings, dict | None, str]]:
    cal = calibration()
    v = [
        (Settings("base"), None, "PLAN"),
        (Settings("rho 10% (NAIC)", rho=0.10), None, "PLAN"),
        (Settings(f"rho {cal.rho_probit:.1%} (probit estimator)", rho=cal.rho_probit), None, "PLAN"),
        (Settings("phi 0 (independent years, as NAIC)", phi=0.0), None, "PLAN"),
        (Settings("NAIC-like: rho 10%, phi 0", rho=0.10, phi=0.0), None, "PLAN"),
        (Settings("loan recovery -10 points", loan_rec_shift=-0.10), None, "PLAN"),
        (Settings("corporate recovery 48% (MA LGD 52%)", corp_rec_const=0.48), None, "PLAN"),
        (Settings("BB 3% thick (equity 9%)", tranche_sizes=(("BB", 0.03),)), {"BB": 0.03}, "PLAN"),
        (Settings("BB 5% thick (equity 7%)", tranche_sizes=(("BB", 0.05),)), {"BB": 0.05}, "PLAN"),
        (Settings("BBB 4% thick (equity 10%)", tranche_sizes=(("BBB", 0.04),)), {"BBB": 0.04}, "PLAN"),
        (Settings("BBB 8% thick (equity 6%)", tranche_sizes=(("BBB", 0.08),)), {"BBB": 0.08}, "PLAN"),
    ]
    for nu in C.T_GRID:
        feasible = np.isfinite(cal.rho_t[nu])
        tag = "" if feasible else ", rho 0: one-year default rate SD above history"
        v.append((Settings(f"t copula nu={nu:g}{tag}", copula="t", nu=nu), None, "PLAN"))
    v += [
        (Settings("400 loans", n_loans=400), None, "PLAN"),
        (Settings("824 corporate names", n_corp=824), None, "PLAN"),
        (Settings("OC tests off", oc_on=False), None, "PLAN"),
    ]
    return v


def moodys_pool_diagnostic() -> pd.DataFrame:
    """Post-hoc: loan PDs from the NAIC 'Historical' 10-year vectors (Moody's cohorts 1970-2009)."""
    hist10 = {"BB+": 0.107, "BB": 0.134, "BB-": 0.267, "B+": 0.329, "B": 0.364, "B-": 0.455, "CCC/C": 0.558}
    orig = C.pool_buckets

    def patched(n_loans, nu):
        buckets, df = orig(n_loans, nu)
        out = []
        for b, (_, r) in zip(buckets, df.iterrows()):
            h = 1.0 - (1.0 - hist10[b.name]) ** (1.0 / C.HORIZON)
            out.append(C.Bucket(b.name, b.n_loans, float(C.latent_threshold(h, nu))))
            df.loc[_, "annual_pd"] = h
        return out, df

    C.pool_buckets = patched
    try:
        rows = []
        for s in (Settings("POST-HOC NAIC-like + Moody's-based loan PDs", rho=0.10, phi=0.0, n_corp=824,
                           corp_rec_const=0.48),
                  Settings("POST-HOC base + Moody's-based loan PDs")):
            res = run(s)
            m = metrics(res)
            m["pool_loss_mean"] = float(res.pool_loss.mean())
            rows.append(m)
        return pd.concat(rows)
    finally:
        C.pool_buckets = orig


def main() -> None:
    allm, alld = [], []
    for s, sizes, origin in variants():
        res = run(s)
        m = metrics(res)
        m["rho"], m["phi"], m["nu"], m["origin"] = res.rho, res.phi, res.nu, origin
        m["pool_loss_mean"] = float(res.pool_loss.mean())
        m["pool_loss_p995"] = float(np.quantile(res.pool_loss, 0.995))
        d = decisions(m, sizes)
        d["origin"] = origin
        allm.append(m)
        alld.append(d)
        print(f"{s.name:55s} " + " ".join(f"{r}:{x:6.2f}" for r, x in zip(d['rating'], d['tail_multiple'])))
    save(pd.concat(allm), "05_sensitivity_metrics.csv")
    save(pd.concat(alld), "05_sensitivity.csv")

    diag = moodys_pool_diagnostic()
    diag["origin"] = "POST-HOC (not in PLAN)"
    save(diag, "05_posthoc_moodys_pd_metrics.csv")
    cap = capital_factors().set_index("rating")
    rows = []
    for name, g in diag.groupby("variant", sort=False):
        g = g.set_index(["rating", "instrument"])
        for r in RATINGS:
            k, c = g.loc[(r, "Corporate")], g.loc[(r, "CLO")]
            rp = k["el"] + 0.5 * k["sd"]
            rows.append({"variant": name, "rating": r, "clo_el": c["el"], "clo_es": c["es"],
                         "clo_cte90_minus_rp": c["cte90"] - rp, "clo_naic_2026": cap.loc[r, "factor_new"],
                         "clo_ratio": (c["cte90"] - rp) / cap.loc[r, "factor_new"],
                         "corp_es": k["es"], "tail_multiple": c["es"] / k["es"],
                         "pool_loss_mean": c["pool_loss_mean"]})
    save(pd.DataFrame(rows), "05_posthoc_moodys_pd.csv")
    print(pd.DataFrame(rows).round(4).to_string())


if __name__ == "__main__":
    main()
