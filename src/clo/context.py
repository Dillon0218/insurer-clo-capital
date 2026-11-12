"""Shared setup: inputs from data/raw, calibration, and one function that runs a variant.

Every variant reuses the same seeds (common random numbers), so differences between the
base case and a sensitivity come from the parameter that changed, not from new draws.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import risk
from .copula import calibrate_rho, conditional_pd, latent_threshold, rho_from_probit
from .corporate import corporate_losses
from .factor import FactorPaths, ar1_from_probit, cohort_thresholds, simulate_factor
from .waterfall import Bucket, CLOStructure, Tranche, run_waterfall

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"              # public sources, in the repository
LICENSED = ROOT / "data" / "licensed"    # S&P and Moody's research tables, local only
LICENSED_FILES = (
    "sp_annual_default_rates_1981_2020.csv",
    "sp_one_year_default_stats_1981_2020.csv",
    "sp_cumulative_default_1981_2020.csv",
    "moodys_recovery_by_year_1982_2009.csv",
)


def check_licensed() -> None:
    missing = [f for f in LICENSED_FILES if not (LICENSED / f).exists()]
    if missing:
        raise FileNotFoundError(
            "S&P / Moody's input tables are not in the repository. Build them from the documents "
            f"listed in data/licensed/README.md and save them in {LICENSED}. Missing: " + ", ".join(missing))
TABLES = ROOT / "outputs" / "tables"
FIGURES = ROOT / "outputs" / "figures"

SEED = 20261111
N_SCEN = 100_000
HORIZON = 10
Q = 0.995
RATINGS = ["AAA", "AA", "A", "BBB", "BB"]
T_GRID = (3.0, 5.0, 10.0, 30.0)   # PLAN section 7
NU_PLAN = 5.0                     # PLAN section 2; infeasible, see t_headline_nu()
REC_CLIP = (0.05, 0.95)


def save(df: pd.DataFrame, name: str) -> Path:
    TABLES.mkdir(parents=True, exist_ok=True)
    path = TABLES / name
    df.to_csv(path, index=False, float_format="%.10g")
    return path


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(TABLES / name)


def plan_hash() -> str:
    return hashlib.sha256((ROOT / "PLAN.md").read_bytes()).hexdigest()


# --------------------------------------------------------------------------- inputs

@dataclass(frozen=True)
class Inputs:
    annual_dr: pd.DataFrame          # S&P annual default rates by rating, 1981-2020, in %
    b_mean: float                    # S&P Table 4, B weighted long-term average (fraction)
    b_std: float                     # S&P Table 4, B standard deviation (fraction)
    sg_pd: float                     # S&P Table 24 speculative grade one-year average
    cum: pd.DataFrame                # S&P Table 26 cumulative by modifier, fraction, years 1-10
    pool_mix: pd.DataFrame           # S&P notch -> share
    recovery_years: pd.DataFrame     # Moody's yearly recoveries
    structure: pd.DataFrame
    factors: pd.DataFrame
    other: pd.DataFrame
    naic_2008: pd.DataFrame
    history: pd.DataFrame
    base_rate: float


@lru_cache(maxsize=1)
def inputs() -> Inputs:
    check_licensed()
    adr = pd.read_csv(LICENSED / "sp_annual_default_rates_1981_2020.csv")
    st4 = pd.read_csv(LICENSED / "sp_one_year_default_stats_1981_2020.csv").set_index("statistic")
    cum = pd.read_csv(LICENSED / "sp_cumulative_default_1981_2020.csv")
    t26 = cum[cum["table"].str.startswith("Table 26")]
    t24 = cum[cum["table"].str.startswith("Table 24")]
    cum10 = (t26[t26["horizon_years"] <= HORIZON]
             .pivot_table(index="rating", columns="horizon_years", values="cum_default_pct") / 100.0)
    sg = float(t24[(t24["rating"] == "Speculative grade") & (t24["horizon_years"] == 1)]["cum_default_pct"].iloc[0]) / 100
    mix = pd.read_csv(RAW / "clo_collateral_ratings.csv")
    mix = mix.groupby("sp_equivalent", sort=False)["share_pct"].sum().reset_index()
    rec = pd.read_csv(LICENSED / "moodys_recovery_by_year_1982_2009.csv")
    stc = pd.read_csv(RAW / "clo_structure_and_economics.csv")
    base = float(stc[stc["item"] == "base_rate_sofr_90d_avg"]["value"].iloc[0])
    return Inputs(
        annual_dr=adr, b_mean=float(st4.loc["weighted_long_term_average", "B"]) / 100,
        b_std=float(st4.loc["standard_deviation", "B"]) / 100, sg_pd=sg, cum=cum10,
        pool_mix=mix, recovery_years=rec, structure=stc,
        factors=pd.read_csv(RAW / "naic_rbc_factors.csv"),
        other=pd.read_csv(RAW / "naic_rbc_other.csv").set_index("item"),
        naic_2008=pd.read_csv(RAW / "naic_cmb_2008_default_vectors.csv"),
        history=pd.read_csv(RAW / "clo_historical_performance.csv"),
        base_rate=base)


# ---------------------------------------------------------------------- calibration

@dataclass(frozen=True)
class Calibration:
    rho_gauss: float
    rho_probit: float
    phi: float
    rho_t: dict
    rec_loan: tuple[float, float]       # (a, b): R = a + b * DR_SG
    rec_bond: tuple[float, float]
    rec_loan_r2: float
    rec_bond_r2: float


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    b, a = np.polyfit(x, y, 1)
    r2 = 1.0 - np.sum((y - (a + b * x)) ** 2) / np.sum((y - y.mean()) ** 2)
    return float(a), float(b), float(r2)


@lru_cache(maxsize=1)
def calibration() -> Calibration:
    inp = inputs()
    b_series = inp.annual_dr["B"].to_numpy() / 100.0
    rho_g = calibrate_rho(inp.b_mean, inp.b_std, None)
    rho_t = {}
    for nu in T_GRID:
        try:
            rho_t[nu] = calibrate_rho(inp.b_mean, inp.b_std, nu)
        except ValueError:      # the common mixing variable alone is already too volatile
            rho_t[nu] = float("nan")
    phi = ar1_from_probit(b_series)
    sg = inp.annual_dr.set_index("year")["speculative_grade"] / 100.0
    rec = inp.recovery_years.set_index("year")
    loan = rec["first_lien_bank_loan_pct"].dropna() / 100.0
    bond = rec["sr_unsecured_bond_pct"].dropna() / 100.0
    al, bl, r2l = _ols(sg.loc[loan.index].to_numpy(), loan.to_numpy())
    ab, bb, r2b = _ols(sg.loc[bond.index].to_numpy(), bond.to_numpy())
    return Calibration(rho_gauss=rho_g, rho_probit=rho_from_probit(b_series), phi=phi,
                       rho_t=rho_t, rec_loan=(al, bl), rec_bond=(ab, bb),
                       rec_loan_r2=r2l, rec_bond_r2=r2b)


def t_headline_nu() -> float:
    """Deviation from PLAN (recorded in the README): at nu = 5 the t copula's shared mixing
    variable alone gives a one-year 'B' default rate SD of 4.65% at rho = 0, above the 3.24%
    observed, so rho cannot be re-solved. Rule fixed before any tranche result was seen: use
    the smallest nu on the PLAN grid for which the volatility match is feasible."""
    cal = calibration()
    return min(nu for nu in T_GRID if np.isfinite(cal.rho_t[nu]))


# -------------------------------------------------------------------------- variants

@dataclass(frozen=True)
class Settings:
    name: str = "base"
    copula: str = "gaussian"            # or "t"
    nu: float | None = None
    rho: float | None = None            # None -> calibrated for the copula
    phi: float | None = None            # None -> calibrated
    n_loans: int = 200
    n_corp: int = 200
    loan_rec_shift: float = 0.0
    corp_rec_const: float | None = None
    tranche_sizes: tuple = ()           # overrides as ((name, size), ...); equity absorbs
    oc_on: bool = True
    n_scen: int = N_SCEN

    def resolved(self) -> tuple[float, float, float | None]:
        cal = calibration()
        nu = self.nu if self.copula == "t" else None
        if self.rho is not None:
            rho = self.rho
        elif nu is None:
            rho = cal.rho_gauss
        else:
            rho = cal.rho_t[float(nu)]
            if not np.isfinite(rho):
                rho = 1e-6          # infeasible nu: run at (almost) zero correlation, flagged
        
        phi = cal.phi if self.phi is None else self.phi
        return rho, phi, nu


def pool_buckets(n_loans: int, nu: float | None) -> tuple[list[Bucket], pd.DataFrame]:
    """Rating buckets with a constant annual PD from the S&P 10-year cumulative rate."""
    inp = inputs()
    mix = inp.pool_mix.copy()
    mix["n_loans"] = np.round(mix["share_pct"] / mix["share_pct"].sum() * n_loans).astype(int)
    rows, buckets = [], []
    for _, r in mix.iterrows():
        p10 = float(inp.cum.loc[r["sp_equivalent"], HORIZON])
        h = 1.0 - (1.0 - p10) ** (1.0 / HORIZON)
        buckets.append(Bucket(r["sp_equivalent"], int(r["n_loans"]), float(latent_threshold(h, nu))))
        rows.append({"rating": r["sp_equivalent"], "share_pct": r["share_pct"],
                     "n_loans": int(r["n_loans"]), "sp_cum_10y": p10, "annual_pd": h})
    return buckets, pd.DataFrame(rows)


def clo_structure(s: Settings, nu: float | None) -> CLOStructure:
    inp = inputs()
    st = inp.structure
    tr = st[st["group"] == "tranche"]
    size = {n: float(tr[(tr["item"] == n) & (tr["field"] == "size")]["value"].iloc[0]) for n in RATINGS}
    spread = {n: float(tr[(tr["item"] == n) & (tr["field"] == "spread")]["value"].iloc[0]) for n in RATINGS}
    size.update(dict(s.tranche_sizes))
    oc = st[st["group"] == "oc_trigger"]["value"].astype(float).tolist()   # AA, A, BBB, BB
    triggers = [None] + oc if s.oc_on else [None] * 5
    tranches = [Tranche(n, size[n], spread[n], trig) for n, trig in zip(RATINGS, triggers)]
    buckets, _ = pool_buckets(s.n_loans, nu)
    fees = st[st["group"] == "fees"].set_index("item")["value"]
    return CLOStructure(
        tranches=tranches, buckets=buckets, base_rate=inp.base_rate,
        loan_spread=float(st[st["field"] == "weighted_average_spread"]["value"].iloc[0]),
        senior_fee=float(fees["senior_management_fee"].split("-")[1]),     # 0.20%, top of range
        sub_fee=float(fees["subordinated_management_fee"].split("-")[0]),  # 0.30%, bottom of range
        reinvest_years=int(float(st[st["item"] == "reinvestment_period_years"]["value"].iloc[0])),
        amortization="linear", horizon=HORIZON)


def recovery_fns(s: Settings, dr_sg: np.ndarray):
    cal = calibration()
    al, bl = cal.rec_loan
    ab, bb = cal.rec_bond
    lo, hi = REC_CLIP
    loan = lambda t, p: np.clip(al + bl * dr_sg[:, t] + s.loan_rec_shift, lo, hi)
    if s.corp_rec_const is not None:
        bond = lambda t, p: np.full(dr_sg.shape[0], s.corp_rec_const)
    else:
        bond = lambda t, p: np.clip(ab + bb * dr_sg[:, t], lo, hi)
    return loan, bond


def factor_paths(s: Settings, nu: float | None, phi: float) -> FactorPaths:
    ss = np.random.SeedSequence(SEED)
    return simulate_factor(s.n_scen, HORIZON, phi, nu, np.random.default_rng(ss.spawn(1)[0]))


@lru_cache(maxsize=8)
def _calibration_paths(phi: float, nu: float | None) -> FactorPaths:
    """A separate, fixed sample of factor paths used only to solve cohort thresholds."""
    return simulate_factor(200_000, HORIZON, phi, nu, np.random.default_rng(SEED + 7))


@lru_cache(maxsize=64)
def corp_thresholds(rating: str, rho: float, phi: float, nu: float | None) -> np.ndarray:
    cum = inputs().cum.loc[rating, list(range(1, HORIZON + 1))].to_numpy()
    return cohort_thresholds(cum, _calibration_paths(phi, nu), rho)


@dataclass
class RunResult:
    settings: Settings
    rho: float
    phi: float
    nu: float | None
    clo_loss: dict = field(default_factory=dict)        # rating -> (n,) PV loss
    clo_ploss: dict = field(default_factory=dict)       # rating -> (n,) principal loss
    corp_loss: dict = field(default_factory=dict)
    corp_default: dict = field(default_factory=dict)
    pool_default: np.ndarray | None = None
    pool_loss: np.ndarray | None = None
    dr_sg: np.ndarray | None = None
    loan_rec_weighted: float = float("nan")
    bond_rec_weighted: float = float("nan")
    oc_fail_any: np.ndarray | None = None
    structure: CLOStructure | None = None
    conservation_error: float = float("nan")


def run(s: Settings) -> RunResult:
    rho, phi, nu = s.resolved()
    paths = factor_paths(s, nu, phi)
    inp = inputs()
    dr_sg = conditional_pd(latent_threshold(inp.sg_pd, nu), paths.z, paths.s, rho)
    loan_rec, bond_rec = recovery_fns(s, dr_sg)
    st = clo_structure(s, nu)
    ss = np.random.SeedSequence(SEED).spawn(3)
    wf = run_waterfall(st, paths, rho, loan_rec, np.random.default_rng(ss[1]))
    out = RunResult(settings=s, rho=rho, phi=phi, nu=nu, structure=st,
                    pool_default=wf.pool_default_frac, pool_loss=wf.pool_loss_frac, dr_sg=dr_sg,
                    oc_fail_any=wf.oc_fail_years, conservation_error=wf.conservation_error)
    for k, name in enumerate(wf.names):
        out.clo_loss[name] = wf.loss[:, k]
        out.clo_ploss[name] = wf.principal_loss[:, k]
    # default-weighted recovery actually applied to loans in the simulation
    out.loan_rec_weighted = 1.0 - float(wf.pool_loss_frac.sum() / max(wf.pool_default_frac.sum(), 1e-12))
    spreads = {t.name: t.spread for t in st.tranches}
    corp_rng = np.random.default_rng(ss[2])
    num, den = 0.0, 0.0
    for r in RATINGS:
        c = corp_thresholds(r, rho, phi, nu)
        res = corporate_losses(paths, rho, c, s.n_corp, inp.base_rate + spreads[r], bond_rec, corp_rng)
        out.corp_loss[r] = res["loss"]
        out.corp_default[r] = res["default_frac"]
    # default-weighted bond recovery (rate independent of the bond's rating)
    w = np.zeros(paths.n)
    for t in range(HORIZON):
        p = conditional_pd(latent_threshold(inp.sg_pd, nu), paths.z[:, t], paths.s[:, t], rho)
        num += float(np.sum(p * bond_rec(t, None)))
        den += float(np.sum(p))
    out.bond_rec_weighted = num / den
    return out


def metrics(res: RunResult, ci: bool = False) -> pd.DataFrame:
    rows = []
    for r in RATINGS:
        for kind, loss in (("CLO", res.clo_loss[r]), ("Corporate", res.corp_loss[r])):
            m = risk.summary(loss, Q)
            m.update({"rating": r, "instrument": kind, "sd": float(np.std(loss)),
                      "cte90": risk.es(loss, 0.90)})
            if kind == "CLO":
                pl = res.clo_ploss[r]
                m["p_principal_loss"] = float((pl > 1e-9).mean())
                m["el_principal"] = float(pl.mean())
            else:
                m["p_principal_loss"] = float((loss > 1e-9).mean())
                m["el_principal"] = float("nan")
            if ci:
                lo, hi = risk.bootstrap_ci(loss, lambda x: risk.es(x, Q), n_boot=400, seed=1)
                m["es_ci_lo"], m["es_ci_hi"] = lo, hi
            rows.append(m)
    df = pd.DataFrame(rows)
    df.insert(0, "variant", res.settings.name)
    return df


def capital_factors(sizes: dict | None = None) -> pd.DataFrame:
    """Pre-tax C-1 factors per rating: old (2021 corporate) and new (2026 CLO + thin surcharge).

    Reads only the public NAIC and structure files, so it works without data/licensed.
    """
    factors = pd.read_csv(RAW / "naic_rbc_factors.csv")
    other = pd.read_csv(RAW / "naic_rbc_other.csv").set_index("item")
    f = factors.set_index("sp_rating")
    surcharge = float(other.loc["clo_thin_tranche_surcharge_2C_or_below_thickness_le_4pct_BSL", "value"])
    thin = float(other.loc["clo_thin_tranche_threshold_thickness", "value"])
    st = pd.read_csv(RAW / "clo_structure_and_economics.csv")
    tr = st[(st["group"] == "tranche") & (st["field"] == "size")].set_index("item")["value"].astype(float)
    sizes = {**tr.to_dict(), **(sizes or {})}
    order = list(factors["designation_category"])
    rows = []
    for r in RATINGS:
        cat = f.loc[r, "designation_category"]
        at_or_below_2c = order.index(cat) >= order.index("2.C")
        add = surcharge if (at_or_below_2c and sizes[r] <= thin + 1e-12) else 0.0
        rows.append({"rating": r, "designation": cat, "thickness": sizes[r],
                     "factor_old": float(f.loc[r, "corporate_factor_2021"]),
                     "factor_new_base": float(f.loc[r, "clo_factor_2026"]),
                     "thin_surcharge": add,
                     "factor_new": float(f.loc[r, "clo_factor_2026"]) + add})
    return pd.DataFrame(rows)


