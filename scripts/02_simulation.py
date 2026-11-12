"""Step 2: 100,000 scenarios, Gaussian (base) and t copula; losses, capital, decisions."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clo.context import (RATINGS, Settings, capital_factors, metrics, run, save, t_headline_nu)

MATERIAL_ES = 0.001        # PLAN section 4: 0.10% of par
BAND = 1.5


def classify_tr(tr: float) -> str:
    if not np.isfinite(tr):
        return "n/a"
    if tr >= BAND:
        return "CLO tail materially worse"
    if tr <= 1 / BAND:
        return "CLO tail materially better"
    return "comparable"


def classify_rc(rc: float) -> str:
    if rc == np.inf:
        return "more capital per unit of tail than corporates (no CLO tail)"
    if not np.isfinite(rc):
        return "n/a"
    if rc < 1 / BAND:
        return "still under-capitalised"
    if rc > BAND:
        return "more capital per unit of tail than corporates"
    return "aligned"


def decisions(m: pd.DataFrame, cap: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in RATINGS:
        c = m[(m["rating"] == r) & (m["instrument"] == "CLO")].iloc[0]
        k = m[(m["rating"] == r) & (m["instrument"] == "Corporate")].iloc[0]
        f = cap[cap["rating"] == r].iloc[0]
        both_small = c["es"] < MATERIAL_ES and k["es"] < MATERIAL_ES
        one_small = (c["es"] < MATERIAL_ES) != (k["es"] < MATERIAL_ES)
        tiny = 1e-9                      # ES of exactly zero up to rounding: no tail at all
        tr = (0.0 if c["es"] <= tiny else c["es"] / k["es"]) if k["es"] > tiny else np.inf
        elm = c["el"] / k["el"] if k["el"] > tiny else np.inf
        cov_clo_old = f["factor_old"] / c["es"] if c["es"] > tiny else np.inf
        cov_clo_new = f["factor_new"] / c["es"] if c["es"] > tiny else np.inf
        cov_corp = f["factor_old"] / k["es"] if k["es"] > tiny else np.inf
        rc = cov_clo_new / cov_corp
        rows.append({
            "variant": m["variant"].iloc[0], "rating": r, "designation": f["designation"],
            "el_clo": c["el"], "el_corp": k["el"], "el_multiple": elm,
            "es_clo": c["es"], "es_corp": k["es"], "tail_multiple": tr,
            "var_clo": c["var"], "var_corp": k["var"],
            "factor_old": f["factor_old"], "factor_new": f["factor_new"],
            "coverage_corp": cov_corp, "coverage_clo_old": cov_clo_old, "coverage_clo_new": cov_clo_new,
            "relative_coverage_old": 1 / tr if tr > tiny else np.inf, "relative_coverage_new": rc,
            "flag": "both ES below 0.10%" if both_small else ("one ES below 0.10%" if one_small else ""),
            "tail_class": "no material tail at 99.5%" if both_small else classify_tr(tr),
            "cliff_shape": bool(tr > elm) if not both_small else None,
            "old_regime": ("n/a" if both_small else
                           ("under-capitalised CLO tail" if tr >= BAND else "not under-capitalised")),
            "new_regime": "n/a" if both_small else classify_rc(rc),
        })
    return pd.DataFrame(rows)


def exceedance(res, grid: np.ndarray) -> pd.DataFrame:
    rows = []
    for r in RATINGS:
        for kind, loss in (("CLO", res.clo_loss[r]), ("Corporate", res.corp_loss[r])):
            s = np.sort(loss)
            n = len(s)
            for x in grid:
                rows.append({"variant": res.settings.name, "rating": r, "instrument": kind, "loss": x,
                             "p_exceed": float((n - np.searchsorted(s, x, side="right")) / n)})
    return pd.DataFrame(rows)


def main() -> None:
    cap = capital_factors()
    save(cap, "02_capital_factors.csv")
    nu = t_headline_nu()
    allm, alld, allx, pools = [], [], [], []
    grid = np.unique(np.concatenate([np.linspace(0, 0.2, 81), np.linspace(0.2, 1.0, 81)]))
    for s in (Settings("base"), Settings(f"t copula nu={nu:g}", copula="t", nu=nu)):
        res = run(s)
        m = metrics(res, ci=True)
        m["rho"], m["phi"], m["nu"] = res.rho, res.phi, res.nu
        allm.append(m)
        alld.append(decisions(m, cap))
        allx.append(exceedance(res, grid))
        pools.append({"variant": s.name, "rho": res.rho, "phi": res.phi, "nu": res.nu,
                      "pool_default_mean": float(res.pool_default.mean()),
                      "pool_default_p995": float(np.quantile(res.pool_default, 0.995)),
                      "pool_loss_mean": float(res.pool_loss.mean()),
                      "pool_loss_p96": float(np.quantile(res.pool_loss, 0.96)),
                      "pool_loss_p995": float(np.quantile(res.pool_loss, 0.995)),
                      "loan_recovery_default_weighted": res.loan_rec_weighted,
                      "bond_recovery_default_weighted": res.bond_rec_weighted,
                      **{f"oc_fail_share_{t.name}": float((res.oc_fail_any[:, k] > 0).mean())
                         for k, t in enumerate(res.structure.tranches)},
                      "conservation_error": res.conservation_error})
        if s.name == "base":
            # tranche loss against pool loss: the cliff, on the base scenarios
            bins = np.linspace(0, 0.30, 31)
            idx = np.digitize(res.pool_loss, bins)
            cl = []
            for i in range(1, len(bins)):
                sel = idx == i
                if sel.sum() < 20:
                    continue
                row = {"pool_loss_lo": bins[i - 1], "pool_loss_hi": bins[i], "n": int(sel.sum())}
                for r in RATINGS:
                    row[f"clo_{r}"] = float(res.clo_loss[r][sel].mean())
                    row[f"corp_{r}"] = float(res.corp_loss[r][sel].mean())
                cl.append(row)
            save(pd.DataFrame(cl), "02_loss_vs_pool_loss.csv")
        print(alld[-1][["variant", "rating", "el_clo", "el_corp", "es_clo", "es_corp", "tail_multiple",
                        "relative_coverage_new", "tail_class", "new_regime"]].round(4).to_string())
    save(pd.concat(allm), "02_loss_metrics.csv")
    save(pd.concat(alld), "02_decisions.csv")
    save(pd.concat(allx), "02_exceedance.csv")
    save(pd.DataFrame(pools), "02_pool_stats.csv")


if __name__ == "__main__":
    main()
