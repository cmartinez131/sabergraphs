# Unit tests for the season-holdout backtest harness
# (backend/app/toolkit/backtest.py). Runs on synthetic panels; the cheap
# systems (naive/trailing/marcel) need no database or engine.
import numpy as np
import pandas as pd
import pytest

from app.toolkit.backtest import (
    BUCKET_EARLY,
    BUCKET_ROOKIE,
    BUCKET_VETERAN,
    _eligible_for_season,
    run_season_holdout,
    summarize_records,
)


def make_panel(rows):
    df = pd.DataFrame(rows, columns=["player_id", "year", "age", "pa", "woba"])
    df["full_name"] = "P" + df["player_id"].astype(str)
    return df


def steady_panel(pid, first_year, last_year, value, pa=500, start_age=25):
    return [
        (pid, y, start_age + (y - first_year), pa, value)
        for y in range(first_year, last_year + 1)
    ]


class TestEligibility:
    def test_min_pa_filters_target_season(self):
        rows = steady_panel(1, 2020, 2023, 0.300)
        rows += steady_panel(2, 2020, 2022, 0.300)
        rows.append((2, 2023, 28, 150, 0.300))  # below min_pa in target year
        panel = make_panel(rows)
        ids, _, _ = _eligible_for_season(panel, "woba", 2023, min_pa=200, window=3)
        assert ids == [1]

    def test_requires_history_in_window(self):
        rows = steady_panel(1, 2020, 2023, 0.300)
        rows += [(2, 2018, 24, 500, 0.300), (2, 2023, 29, 500, 0.300)]  # 4-yr gap
        panel = make_panel(rows)
        ids, _, _ = _eligible_for_season(panel, "woba", 2023, min_pa=200, window=3)
        assert ids == [1]

    def test_buckets_by_prior_observed_seasons(self):
        rows = steady_panel(1, 2022, 2023, 0.300)   # 1 prior season
        rows += steady_panel(2, 2021, 2023, 0.300)  # 2 prior
        rows += steady_panel(3, 2018, 2023, 0.300)  # 5 prior
        panel = make_panel(rows)
        _, buckets, _ = _eligible_for_season(panel, "woba", 2023, min_pa=200, window=3)
        assert buckets[1] == BUCKET_ROOKIE
        assert buckets[2] == BUCKET_EARLY
        assert buckets[3] == BUCKET_VETERAN


class TestHarness:
    def test_naive_metrics_exact(self):
        # Player 1: 2022=0.300 -> 2023 actual 0.340 (naive error 0.040)
        # Player 2: 2022=0.320 -> 2023 actual 0.300 (naive error -0.020)
        rows = [
            (1, 2022, 27, 500, 0.300), (1, 2023, 28, 500, 0.340),
            (2, 2022, 27, 500, 0.320), (2, 2023, 28, 500, 0.300),
        ]
        panel = make_panel(rows)
        _, results = run_season_holdout(
            panel=panel, stats=("woba",), target_seasons=(2023,),
            fold_start=2023, systems=("naive",),
        )
        row = results["per_season"][0]
        assert row["system"] == "naive" and row["season"] == 2023 and row["n"] == 2
        assert row["mae"] == pytest.approx((0.040 + 0.020) / 2)
        assert row["rmse"] == pytest.approx(np.sqrt((0.040**2 + 0.020**2) / 2))

    def test_trailing_uses_last_three_seasons(self):
        rows = [
            (1, 2019, 24, 500, 0.900),  # outside trailing-3 window
            (1, 2020, 25, 500, 0.300),
            (1, 2021, 26, 500, 0.330),
            (1, 2022, 27, 500, 0.360),
            (1, 2023, 28, 500, 0.330),
        ]
        panel = make_panel(rows)
        records, _ = run_season_holdout(
            panel=panel, stats=("woba",), target_seasons=(2023,),
            fold_start=2023, systems=("trailing",),
        )
        pred = records.loc[records["system"] == "trailing", "pred"].iloc[0]
        assert pred == pytest.approx((0.300 + 0.330 + 0.360) / 3)

    def test_no_leakage_from_evaluation_seasons(self):
        # Poisoning seasons >= the fold must not change any prediction for it.
        base = (
            steady_panel(1, 2019, 2023, 0.310)
            + steady_panel(2, 2019, 2023, 0.290)
            + steady_panel(3, 2019, 2023, 0.330)
        )
        clean_records, _ = run_season_holdout(
            panel=make_panel(base), stats=("woba",), target_seasons=(2022,),
            fold_start=2022, systems=("naive", "trailing", "marcel"),
        )
        poisoned = [
            (pid, y, age, pa, 0.999 if y >= 2022 else v)
            for (pid, y, age, pa, v) in base
        ]
        poisoned_records, _ = run_season_holdout(
            panel=make_panel(poisoned), stats=("woba",), target_seasons=(2022,),
            fold_start=2022, systems=("naive", "trailing", "marcel"),
        )
        merged = clean_records.merge(
            poisoned_records, on=["system", "stat", "season", "player_id"],
            suffixes=("_clean", "_poisoned"),
        )
        assert len(merged) == len(clean_records)
        assert np.allclose(merged["pred_clean"], merged["pred_poisoned"])

    def test_player_limit_caps_population(self):
        rows = []
        for pid in range(1, 8):
            rows += steady_panel(pid, 2021, 2023, 0.300)
        records, _ = run_season_holdout(
            panel=make_panel(rows), stats=("woba",), target_seasons=(2023,),
            fold_start=2023, systems=("naive",), player_limit=3,
        )
        assert records["player_id"].nunique() == 3

    def test_knn_requires_engine(self):
        panel = make_panel(steady_panel(1, 2021, 2023, 0.300))
        with pytest.raises(ValueError, match="engine"):
            run_season_holdout(panel=panel, stats=("woba",), systems=("knn",))


class TestCalibration:
    def _records(self, fit_errors, eval_errors):
        """Build records where fit folds (2021) carry `fit_errors` residuals
        and the eval fold (2022) carries `eval_errors`."""
        rows = []
        for i, e in enumerate(fit_errors):
            rows.append({"system": "naive", "stat": "woba", "season": 2021,
                         "player_id": i, "actual": 0.300 + e, "pred": 0.300,
                         "band_lo": None, "band_hi": None, "bucket": BUCKET_VETERAN})
        for i, e in enumerate(eval_errors):
            rows.append({"system": "naive", "stat": "woba", "season": 2022,
                         "player_id": 1000 + i, "actual": 0.300 + e, "pred": 0.300,
                         "band_lo": None, "band_hi": None, "bucket": BUCKET_VETERAN})
        return pd.DataFrame(rows)

    def test_out_of_sample_coverage_math(self):
        # Fit residuals uniform on [-0.05, 0.05] -> p10/p90 = [-0.04, 0.04].
        fit = list(np.linspace(-0.05, 0.05, 101))
        # Eval: 8 inside the band, 2 outside -> coverage 0.8
        ev = [0.0] * 8 + [0.30, -0.30]
        res = summarize_records(self._records(fit, ev), target_seasons=[2022])
        cal = res["calibration"][0]
        assert cal["coverage"] == pytest.approx(0.8)
        assert cal["n_eval"] == 10

    def test_calibration_skipped_without_enough_fit_folds(self):
        res = summarize_records(
            self._records([0.01] * 5, [0.0] * 10), target_seasons=[2022]
        )
        assert res["calibration"] == []  # < 30 fit residuals -> no band

    def test_knn_native_band_coverage(self):
        rows = []
        for i in range(10):
            inside = i < 7  # 7 of 10 inside the band
            rows.append({"system": "knn", "stat": "woba", "season": 2022,
                         "player_id": i, "actual": 0.300,
                         "pred": 0.300,
                         "band_lo": 0.250 if inside else 0.350,
                         "band_hi": 0.350 if inside else 0.400,
                         "bucket": BUCKET_VETERAN})
        res = summarize_records(pd.DataFrame(rows), target_seasons=[2022])
        assert res["knn_native_band"][0]["coverage"] == pytest.approx(0.7)

    def test_summary_shapes(self):
        panel = make_panel(
            steady_panel(1, 2018, 2023, 0.310) + steady_panel(2, 2018, 2023, 0.290)
        )
        _, results = run_season_holdout(
            panel=panel, stats=("woba",), target_seasons=(2022, 2023),
            fold_start=2020, systems=("naive", "marcel"),
        )
        systems = {r["system"] for r in results["per_season"]}
        seasons = {r["season"] for r in results["per_season"]}
        assert systems == {"naive", "marcel"}
        assert seasons == {2022, 2023}       # fold 2020-21 feed bands only
        assert results["overall"]
        assert results["per_bucket"]
        assert results["config"]["nominal_band"] == 0.80
