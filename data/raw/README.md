# Inputs

Every external number the model uses from public sources (NAIC, FRED, SEC filings and public industry papers), each with its source in the file itself. Nothing here is estimated; values were copied from the documents named, and the numbering below matches the README's source list. The S&P and Moody's research tables are kept outside the repository, in `data/licensed` (see the README there).

| File | What | Source |
|---|---|---|
| `naic_rbc_factors.csv` | Life C-1 pre-tax factors by designation: 2021 corporate and 2026 CLO; rating to designation map | [1], [2], [4] |
| `naic_rbc_other.csv` | Thin-tranche surcharge and threshold, residual factor, CLO portfolio adjustment, NAIC calibration settings (VaR96, 10 years, EL + 0.5 SD, 3.47%, rho 10%) | [2], [3], [9], [10] |
| `naic_cmb_2008_default_vectors.csv` | NAIC "2008" 10-year cumulative default vectors by Moody's rating | [12] |
| `clo_collateral_ratings.csv` | CLO collateral rating mix (Moody's notches) and S&P equivalents | [16], [4] |
| `clo_structure_and_economics.csv` | Tranche sizes and spreads, OC triggers, pool spread, fees, reinvestment, SOFR | [10], [17], [18], [19] |
| `clo_historical_performance.csv` | S&P CLO 1.0 / 2.0 default counts, Moody's 2007-2017 CLO cohort, NAIC YE2019 stress results | [21], [20], [13] |
| `fred_sofr90.csv` | 90-day average SOFR, Sep-Nov 2026 | [19] |
