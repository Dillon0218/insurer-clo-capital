# Licensed inputs (kept on this computer, not in the repository)

These four tables come from S&P Global Ratings and Moody's research reports. The numbers are cited in the main README, but the tables themselves are not redistributed here. To rerun the pipeline, rebuild each file from the document named below and save it in this folder with exactly these columns. `scripts/run_all.py` stops with a list of what is missing if any file is absent. The tests run without them.

| File | Columns | Build it from |
|---|---|---|
| `sp_annual_default_rates_1981_2020.csv` | `year, AAA, AA, A, BBB, BB, B, CCC_C, investment_grade, speculative_grade, all_rated` (percent), 1981-2020 | S&P Global Ratings, *Default, Transition, and Recovery: 2020 Annual Global Corporate Default And Rating Transition Study* (7 April 2021), Table 3 (rating columns) and Table 1 (default rate columns) |
| `sp_one_year_default_stats_1981_2020.csv` | `statistic` (minimum, maximum, weighted_long_term_average, median, standard_deviation), `AAA, AA, A, BBB, BB, B, CCC_C` (percent) | same study, Table 4 |
| `sp_cumulative_default_1981_2020.csv` | long format: `table` ("Table 24 (by rating category)" or "Table 26 (by rating modifier)"), `rating`, `horizon_years`, `cum_default_pct` | same study, Tables 24 and 26, horizons 1-13 |
| `moodys_recovery_by_year_1982_2009.csv` | `year, first_lien_bank_loan_pct, sr_unsecured_bond_pct, subordinated_bond_pct` (percent of par, blank where not reported) | Moody's Investors Service, *Corporate Default and Recovery Rates, 1920-2009* (February 2010), Exhibit 21 (trading price about 30 days after default, issuer-weighted) |

`recovery_long_run.csv` (Moody's long-run recovery averages used as a check) is kept here for reference; the code does not read it.

The study pages and the copies read for this project are listed as sources [14] and [15] in the main README.
