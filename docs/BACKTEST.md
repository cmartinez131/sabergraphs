# Backtest — Next-Season Forecast Systems

Generated 2026-08-08 by `python -m app.toolkit.backtest_report`.
Numbers are reported exactly as measured; nothing is filtered or reframed.

## Design

Season-holdout evaluation: every system is trained only on seasons ≤ N−1 and
scored on season N, for N ∈ {2022, 2023, 2024, 2025}. The KNN-aging system runs with a
hard `max_year = N−1` cutoff threaded through all of its queries (league
curve, comparable selection, and the comparables' future paths), so no
system sees the evaluation period.

**Systems**

| System | Definition |
|---|---|
| Naive repeat | Repeat the player's most recent observed season |
| Trailing mean (3yr) | Unweighted mean of the last 3 observed seasons (the app's existing baseline) |
| KNN-aging | League aging-curve ratios blended with KNN-comparable ratio paths (the app's existing `aging_knn` method) |
| Marcel | 5/4/3 recency weighting, 1200 PA league-average ballast, age adjustment around 29 (+0.6%/yr below, −0.3%/yr above), projected PA = 0.5·PA(t−1) + 0.1·PA(t−2) + 200 |

**Eligibility (identical for all systems):** target-season PA ≥ 200 with the
stat observed, plus at least one observed season in the 3-year window
before the target. Experience buckets count seasons observed in the data
before the target season (rookie = 1, 2–3, veteran = 4+). True rookies with
zero MLB history cannot be projected by any of these systems and are
excluded by construction.

**Honest caveats**

- The panel starts in 2015, so experience counts are left-truncated: a
  ten-year veteran in 2022 counts at most 7 prior seasons. Bucket labels
  describe *observed* seasons, not service time.
- 2020 is the 60-game COVID season; it participates in trailing windows and
  Marcel weights at face value.
- League averages are computed from the players present in the Savant
  batting CSV (roughly the 50+ PA population), not all MLB hitters.
- Marcel weights (5/4/3), ballast (1200 PA), and the age slopes are the
  classic published constants — nothing here was tuned on the test seasons.
- Home-run errors are in HR per season (counting stat, so playing-time
  error dominates); wOBA errors are in absolute wOBA points.

## wOBA

### RMSE by season — wOBA

| System | 2022 | 2023 | 2024 | 2025 | Overall |
|---|---|---|---|---|---|
| Naive repeat | 0.0503 | 0.0462 | 0.0528 | 0.0433 | 0.0484 |
| Trailing mean (3yr) | 0.0463 | 0.0433 | 0.0479 | 0.0440 | 0.0455 |
| Marcel | 0.0350 | 0.0313 | 0.0357 | 0.0321 | 0.0336 |
| KNN-aging | 0.0513 | 0.0493 | 0.0537 | 0.0446 | 0.0499 |

### MAE by season — wOBA

| System | 2022 | 2023 | 2024 | 2025 | Overall |
|---|---|---|---|---|---|
| Naive repeat | 0.0378 | 0.0342 | 0.0384 | 0.0320 | 0.0356 |
| Trailing mean (3yr) | 0.0363 | 0.0324 | 0.0352 | 0.0319 | 0.0340 |
| Marcel | 0.0280 | 0.0251 | 0.0283 | 0.0256 | 0.0268 |
| KNN-aging | 0.0376 | 0.0364 | 0.0398 | 0.0332 | 0.0368 |

### Eligible predictions per season — wOBA

| System | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| Naive repeat | 324 | 332 | 348 | 320 |
| Trailing mean (3yr) | 324 | 332 | 348 | 320 |
| Marcel | 324 | 332 | 348 | 320 |
| KNN-aging | 324 | 332 | 348 | 320 |

### By experience bucket (pooled 2022–2025) — wOBA

| System | rookie (1 prior season) — RMSE / MAE / n | 2-3 prior seasons — RMSE / MAE / n | veteran (4+ prior seasons) — RMSE / MAE / n |
|---|---|---|---|
| Naive repeat | 0.0705 / 0.0507 / 170 | 0.0471 / 0.0367 / 354 | 0.0428 / 0.0320 / 800 |
| Trailing mean (3yr) | 0.0705 / 0.0507 / 170 | 0.0470 / 0.0360 / 354 | 0.0373 / 0.0295 / 800 |
| Marcel | 0.0365 / 0.0294 / 170 | 0.0335 / 0.0273 / 354 | 0.0330 / 0.0260 / 800 |
| KNN-aging | 0.0696 / 0.0508 / 170 | 0.0511 / 0.0393 / 354 | 0.0441 / 0.0327 / 800 |

## Home runs

### RMSE by season — Home runs

| System | 2022 | 2023 | 2024 | 2025 | Overall |
|---|---|---|---|---|---|
| Naive repeat | 9.25 | 8.98 | 8.69 | 9.01 | 8.98 |
| Trailing mean (3yr) | 7.87 | 8.86 | 8.13 | 8.91 | 8.45 |
| Marcel | 7.33 | 7.37 | 7.03 | 7.89 | 7.40 |
| KNN-aging | 11.67 | 10.29 | 11.16 | 10.69 | 10.97 |

### MAE by season — Home runs

| System | 2022 | 2023 | 2024 | 2025 | Overall |
|---|---|---|---|---|---|
| Naive repeat | 6.84 | 6.74 | 6.64 | 6.75 | 6.74 |
| Trailing mean (3yr) | 5.94 | 6.57 | 6.28 | 6.58 | 6.34 |
| Marcel | 5.66 | 5.66 | 5.40 | 5.85 | 5.64 |
| KNN-aging | 8.17 | 7.75 | 7.87 | 7.92 | 7.93 |

### Eligible predictions per season — Home runs

| System | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| Naive repeat | 324 | 332 | 348 | 320 |
| Trailing mean (3yr) | 324 | 332 | 348 | 320 |
| Marcel | 324 | 332 | 348 | 320 |
| KNN-aging | 324 | 332 | 348 | 320 |

### By experience bucket (pooled 2022–2025) — Home runs

| System | rookie (1 prior season) — RMSE / MAE / n | 2-3 prior seasons — RMSE / MAE / n | veteran (4+ prior seasons) — RMSE / MAE / n |
|---|---|---|---|
| Naive repeat | 9.90 / 7.82 / 170 | 8.45 / 6.37 / 354 | 9.01 / 6.67 / 800 |
| Trailing mean (3yr) | 9.90 / 7.82 / 170 | 9.17 / 6.87 / 354 | 7.75 / 5.79 / 800 |
| Marcel | 7.35 / 5.45 / 170 | 7.16 / 5.40 / 354 | 7.52 / 5.78 / 800 |
| KNN-aging | 10.22 / 8.08 / 170 | 11.55 / 8.22 / 354 | 10.85 / 7.76 / 800 |

## Calibration — 80% bands

Nominal coverage is 80%: an actual outcome should land inside the band
80% of the time. Residual bands are fit only on folds strictly before the
evaluated season (folds back to 2018), then applied to that season —
fully out-of-sample. The KNN row labeled "model's own output" scores the
p10–p90 band the production endpoint actually returns.

| System | Stat | Band | Empirical coverage | n |
|---|---|---|---|---|
| KNN-aging | Home runs | out-of-sample residual p10–p90 | 85.6% | 1324 |
| KNN-aging | wOBA | out-of-sample residual p10–p90 | 83.0% | 1324 |
| Marcel | Home runs | out-of-sample residual p10–p90 | 84.5% | 1324 |
| Marcel | wOBA | out-of-sample residual p10–p90 | 81.4% | 1324 |
| Naive repeat | Home runs | out-of-sample residual p10–p90 | 88.2% | 1324 |
| Naive repeat | wOBA | out-of-sample residual p10–p90 | 82.8% | 1324 |
| Trailing mean (3yr) | Home runs | out-of-sample residual p10–p90 | 84.7% | 1324 |
| Trailing mean (3yr) | wOBA | out-of-sample residual p10–p90 | 79.5% | 1324 |
| KNN-aging | Home runs | model's own p10–p90 output | 48.7% | 1324 |
| KNN-aging | wOBA | model's own p10–p90 output | 47.1% | 1324 |

