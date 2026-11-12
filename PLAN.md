# PLAN: Insurer CLO holdings, credit risk vs. capital charges

Written 11 November 2026, before any simulation was run. The research question, method, metrics,
decision rules, validation tests and sensitivity list below are fixed. Results that come out
differently from what I expect are reported as they are; nothing here is edited after the runs.
The SHA-256 of this file is recorded in `outputs/tables/00_plan_hash.csv` by the pipeline.

## 1. Question

Rated CLO tranches and corporate bonds with the same rating carried the same NAIC life RBC C-1
factor through year-end 2025 (the 2021 bond factors). For year-end 2026 the NAIC adopted
CLO-specific factors (proposal 2026-12-IRE MOD), lower than the corporate factors for AAA to A and
higher for BBB and below, plus an 11.77% surcharge on BSL tranches rated 2.C or below that are 4% of
the structure or thinner.

> Under the same rating, how much more (or less) does a CLO tranche lose than a same-rated
> corporate bond portfolio in a severe recession and at the 99.5th percentile, and how much tail
> loss does one unit of C-1 capital cover under (a) the 2021 corporate factors that applied to CLOs
> through YE2025 and (b) the 2026 CLO factors?

Expected shape of the answer (stated in advance, may be wrong): CLO 2.0 tranches have a very good
default record, so expected losses may be similar or lower than for corporates; the difference, if
any, should be in the tail, where a thin tranche goes from no loss to total loss over a narrow
range of pool losses.

## 2. Model (all inputs and their sources are in `data/raw`)

**Horizon and grid.** 10 years, annual steps, matching the 10-year horizon of both NAIC
calibrations. 100,000 scenarios, seed 20261111.

**Economic factor.** One systematic factor per year, Z_t, a stationary AR(1) with unit variance.
Every name's latent variable in year t is sqrt(rho) Z_t + sqrt(1 - rho) e_it (Gaussian copula) or
the same divided by sqrt(W_t / nu) (t copula, W_t ~ chi2(nu) shared by all names in the year).

- rho: method of moments on S&P's one-year default rate statistics for 'B' issuers, 1981-2020
  (weighted long-term average 3.34%, standard deviation 3.24%; S&P 2020 study Table 4): rho is the
  value at which the large-pool one-year default rate has that mean and standard deviation.
- phi (AR(1) persistence): lag-1 autocorrelation of Phi^-1(annual 'B' default rate), 1981-2020.
- t copula: nu = 5, with rho re-solved so the one-year default rate standard deviation is the same
  3.24%. The Gaussian copula is the base case; the t copula is reported alongside every headline.

**Loan pool.** 200 first-lien loans, equal par. Rating mix from LSEG Yield Book (May 2021, Moody's
scale) mapped to S&P notches: BB+ 3%, BB 5%, BB- 11%, B+ 14%, B 30%, B- 30%, CCC/C 7%. Each bucket
has a constant annual default probability h = 1 - (1 - P10)^(1/10), where P10 is S&P's 10-year
average cumulative default rate for that notch (2020 study, Table 26). The pool is managed: during
the 5-year reinvestment period recoveries are reinvested at par in the same rating mix and
defaulted names are replaced; afterwards loans repay linearly by year 10, with no voluntary
prepayment (the Academy's recommendation).

**Recovery.** Linked to the economy through the year's speculative-grade default rate DR_t (the
conditional default rate of a name with S&P's speculative-grade one-year average PD, 3.71%):
R = a + b DR_t, fitted by OLS on yearly Moody's trading-price recoveries (first-lien loans
1990-2009; senior unsecured bonds 1982-2009) against S&P's speculative-grade annual default rate,
clipped to [5%, 95%]. Loans use the loan line, corporate bonds the bond line.

**CLO.** Structure, spreads and pool spread from the Academy's October 2026 CLO report: AAA 64% /
AA 12% / A 6% / BBB 6% / BB 4% / equity 8%; SOFR + 130 / 140 / 160 / 260 / 500 bp; collateral
SOFR + 350 bp. SOFR = 3.81% (FRED 90-day average, 10 Nov 2026), constant. Senior fee 0.20%,
subordinated fee 0.30% of collateral (CIFC 10-K ranges). OC tests after AA (class A/B), A, BBB and
BB interest at 122.6% / 114.5% / 108.9% / 103.7% (a published deal example); a failing test diverts
interest to pay down notes from the top. Unpaid interest is capitalised. Annual waterfall as in
`src/clo/waterfall.py`.

**Corporate comparison.** For each rating (AAA, AA, A, BBB, BB) a buy-and-hold portfolio of 200
10-year bullet bonds of that rating, on the same factor paths and the same rho and phi. Yearly
default thresholds are solved so the portfolio reproduces S&P's average cumulative default curve
for that notch (Table 26) in every year 1-10. Coupon = SOFR + the spread of the same-rated CLO
tranche (only used for discounting).

**Loss.** For every instrument: 1 - PV(cash received) / initial par, discounted at its own coupon.
Zero if everything promised is paid (whatever the timing), otherwise the PV of what was missed.
Principal loss (unpaid original principal at year 10) is also reported for the NAIC comparison.

## 3. Metrics

Per CLO tranche and per same-rated corporate portfolio: expected loss (EL), probability of any loss,
probability of principal loss, 99.5% VaR, 99.5% ES (mean of the worst 0.5%), and NAIC's own
measures: VaR96 and CTE90. Bootstrap 90% intervals for ES.

Capital, pre-tax, per unit of par:
- Old regime: 2021 corporate factor of the designation (AAA 1.A, AA 1.C, A 1.F, BBB 2.B, BB 3.B),
  for both the CLO tranche and the corporate portfolio.
- New regime: 2026 CLO factor of the same designation, plus 11.77% where the tranche is rated 2.C
  or below and 4% thick or thinner (the base BB tranche qualifies; BBB at 2.B does not).

Coverage = capital / 99.5% ES.

## 4. Decision rules (fixed now)

- **Tail multiple** TR = ES99.5(CLO tranche) / ES99.5(corporate, same rating).
  TR >= 1.5: CLO tail materially worse. TR <= 1/1.5: materially better. In between: comparable.
- **Tail shape (cliff).** Holds for a rating if TR > EL multiple (EL CLO / EL corporate): the CLO
  loses relatively more in the tail than on average.
- **Old regime.** Same factor for both, so CLO coverage / corporate coverage = 1 / TR. The old
  regime under-capitalised the CLO tail for a rating if TR >= 1.5.
- **New regime.** RC = (F_new / ES_CLO) / (F_corp / ES_corp). 0.67 <= RC <= 1.5: aligned with the
  corporate standard. RC < 0.67: still under-capitalised. RC > 1.5: more capital per unit of tail
  than a same-rated corporate.
- **Materiality floor.** If the ES99.5 of both instruments is below 0.10% of par, the rating is
  reported as "no material tail at 99.5%" and no ratio is classified. If only one is below, the
  ratio is reported and flagged.
- **Robustness.** A classification is called robust if it is the same under the Gaussian and the
  t (nu = 5) copula, otherwise model-dependent.

## 5. Severe recession scenario (NAIC "Similar to 2008")

Deterministic: each loan bucket defaults on the NAIC Capital Markets Bureau "2008" 10-year
cumulative default vector for its Moody's rating (May 2020 update, Table 4), applied as fractional
defaults to the whole pool including reinvested loans, with the NAIC stepdown recovery of 40% on
loans. Corporates: the factor path is backed out from the NAIC B2 yearly marginal default rates
using the base rho, then applied to the corporate portfolios; corporate recovery = Moody's 2008
senior unsecured bond recovery, 33.8%. A second CLO line uses Moody's 2008 first-lien loan
recovery (61.7%) instead of 40% to separate the recovery assumption from the default path.

## 6. Validation (criteria fixed now)

- V1 Unit tests: Vasicek large-pool quantile against closed form and a hand-checked value; copula
  marginals (quadrature and name-level simulation); waterfall cash conservation, zero loss with no
  defaults, static tranche formula, seniority, OC diversion.
- V2 Corporate factors under NAIC-like settings (rho 10%, independent years, 824 names, recovery
  48% = Moody's Analytics LGD 52%): VaR96 - (EL + 0.5 SD) against the 2021 factors. Pass if within a
  factor of 2 for AA to BB.
- V3 CLO factors under NAIC-like settings (rho 10%, independent years): CTE90 minus the same-rated
  corporate risk premium, against the 2026 CLO factors (BB including the thin surcharge). Pass if
  within a factor of 2 for BBB and BB.
- V4 Severe recession scenario against the NAIC's own YE2019 stress results for scenario D
  (principal loss AAA 0%, AA 0%, A 0%, BBB 19%, BB 97%). Pass if AAA, AA and A < 1%, BBB in
  [5%, 40%] and BB >= 80%.
- V5 Historical record: base-model 10-year probability of principal loss per tranche against the
  Moody's 2007-2017 CLO cohort (Aaa-A 0%, Baa2 1%, Baa3 2%, Ba2 1%, Ba3 9%) and S&P's CLO 1.0 / 2.0
  lifetime default counts. Reported, not pass/fail; any rating where the model is below history is
  flagged as possibly too optimistic.
- V6 Recovery: default-weighted mean model recovery against Moody's 1982-2009 issuer-weighted
  averages (loans 65.6%, senior unsecured 36.6%). Reported.

## 7. Sensitivities (each changes one input from the base)

rho = 10% (NAIC); rho from the probit estimator; phi = 0 (independent years, as NAIC); NAIC-like
(rho 10% and phi = 0); loan recovery 10 points lower; corporate recovery 48%; BB tranche 3% and 5%
thick (equity absorbs the difference); BBB tranche 4% and 8% thick; t copula nu = 3, 5, 10, 30;
400 loans; 824 corporate names; OC tests switched off.

## 8. Known simplifications (stated now)

No rating migration of individual loans or CCC haircuts in the OC test; no manager trading gains
or losses; annual rather than monthly payments; reinvestment at par; constant SOFR; corporate
portfolios have a single rating and are not replaced on default; pre-tax losses compared with
pre-tax factors; the NAIC factors' tax, AVR and portfolio adjustments are not modelled.
