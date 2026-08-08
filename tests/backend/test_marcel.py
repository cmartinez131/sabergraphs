# Unit tests for the classic-Marcel math (backend/app/toolkit/marcel.py).
# All tests run on hand-built pandas panels — no database required.
import pandas as pd
import pytest

from app.toolkit.marcel import (
    BALLAST_PA,
    age_multiplier,
    league_rates,
    marcel_project_all,
    stat_kind,
    weighted_league_rate,
)


def make_panel(rows):
    """rows: (player_id, year, age, pa, stat_value) -> panel with a 'woba'
    (or arbitrary named) stat column."""
    df = pd.DataFrame(rows, columns=["player_id", "year", "age", "pa", "woba"])
    df["full_name"] = "P" + df["player_id"].astype(str)
    return df


def test_stat_kind():
    assert stat_kind("woba") == "rate"
    assert stat_kind("home_run") == "counting"


def test_league_rate_is_pa_weighted():
    panel = make_panel([
        (1, 2023, 28, 600, 0.400),
        (2, 2023, 28, 200, 0.100),
    ])
    rates = league_rates(panel, "woba")
    # (0.400*600 + 0.100*200) / 800 = 0.325 — NOT the unweighted 0.250
    assert rates[2023] == pytest.approx(0.325)


def test_weighted_league_rate_uses_5_4_3_over_three_seasons():
    panel = make_panel([
        (1, 2023, 28, 100, 0.300),
        (1, 2022, 27, 100, 0.200),
        (1, 2021, 26, 100, 0.100),
        (1, 2020, 25, 100, 0.900),  # outside the 3-season window for 2024
    ])
    lg = weighted_league_rate(panel, "woba", 2024)
    expected = (5 * 0.300 * 100 + 4 * 0.200 * 100 + 3 * 0.100 * 100) / (12 * 100)
    assert lg == pytest.approx(expected)


def test_age_multiplier_shape():
    assert age_multiplier(29) == pytest.approx(1.0)
    assert age_multiplier(24) == pytest.approx(1.0 + 5 * 0.006)
    assert age_multiplier(34) == pytest.approx(1.0 - 5 * 0.003)
    assert age_multiplier(None) == 1.0
    assert age_multiplier(float("nan")) == 1.0


def test_weighted_rate_exact_with_zero_ballast():
    # Ballast off -> projection is exactly the 5/4/3 PA-weighted rate.
    # Ages chosen so age-at-target = 29 (multiplier 1).
    panel = make_panel([
        (1, 2023, 28, 400, 0.400),
        (1, 2022, 27, 500, 0.350),
        (1, 2021, 26, 600, 0.300),
    ])
    out = marcel_project_all(panel, "woba", 2024, ballast_pa=0.0)
    num = 5 * 0.400 * 400 + 4 * 0.350 * 500 + 3 * 0.300 * 600
    den = 5 * 400 + 4 * 500 + 3 * 600
    assert out.loc[1, "proj_rate"] == pytest.approx(num / den)
    assert out.loc[1, "proj_value"] == pytest.approx(num / den)  # rate stat
    assert out.loc[1, "n_seasons"] == 3


def test_ballast_regresses_small_samples_to_league_mean():
    # A 5-PA wonder hitting .900 regresses almost entirely to the league rate
    # set by a high-PA league population at .300.
    rows = [(pid, 2023, 28, 600, 0.300) for pid in range(2, 30)]
    rows.append((1, 2023, 28, 5, 0.900))
    panel = make_panel(rows)
    out = marcel_project_all(panel, "woba", 2024)
    lg = weighted_league_rate(panel, "woba", 2024)
    # weighted sample: w=5 on (0.900 * 5 PA); ballast dominates
    expected = (5 * 0.900 * 5 + 1200 * lg) / (5 * 5 + 1200)
    assert out.loc[1, "proj_rate"] == pytest.approx(expected)
    # and far from the observed 0.900
    assert out.loc[1, "proj_rate"] < 0.4


def test_projected_pa_formula():
    panel = make_panel([
        (1, 2023, 28, 600, 0.300),
        (1, 2022, 27, 400, 0.300),
        (1, 2021, 26, 700, 0.300),  # t-3 PA must NOT affect projected PA
    ])
    out = marcel_project_all(panel, "woba", 2024)
    assert out.loc[1, "proj_pa"] == pytest.approx(0.5 * 600 + 0.1 * 400 + 200)


def test_counting_stat_scaled_to_projected_pa():
    df = pd.DataFrame(
        [(1, 2023, 28, 600, 40), (1, 2022, 27, 600, 40), (1, 2021, 26, 600, 40)],
        columns=["player_id", "year", "age", "pa", "home_run"],
    )
    df["full_name"] = "Slugger"
    out = marcel_project_all(df, "home_run", 2024, ballast_pa=0.0)
    rate = 40.0 / 600.0
    proj_pa = 0.5 * 600 + 0.1 * 600 + 200
    assert out.loc[1, "proj_pa"] == pytest.approx(proj_pa)
    assert out.loc[1, "proj_value"] == pytest.approx(rate * proj_pa)


def test_age_adjustment_applied():
    young = make_panel([(1, 2023, 23, 600, 0.300)])   # target age 24
    old = make_panel([(1, 2023, 33, 600, 0.300)])     # target age 34
    py = marcel_project_all(young, "woba", 2024, ballast_pa=0.0)
    po = marcel_project_all(old, "woba", 2024, ballast_pa=0.0)
    assert py.loc[1, "age_mult"] == pytest.approx(1.0 + 5 * 0.006)
    assert po.loc[1, "age_mult"] == pytest.approx(1.0 - 5 * 0.003)
    assert py.loc[1, "proj_rate"] > po.loc[1, "proj_rate"]


def test_missing_seasons_contribute_nothing():
    # Only t-1 exists; with ballast off the projection equals that season.
    panel = make_panel([(1, 2023, 28, 500, 0.333)])
    out = marcel_project_all(panel, "woba", 2024, ballast_pa=0.0)
    assert out.loc[1, "proj_rate"] == pytest.approx(0.333)
    assert out.loc[1, "n_seasons"] == 1


def test_no_leakage_from_target_or_future_seasons():
    base = [
        (1, 2023, 28, 500, 0.320),
        (1, 2022, 27, 500, 0.310),
        (2, 2023, 28, 500, 0.290),
    ]
    clean = marcel_project_all(make_panel(base), "woba", 2024)
    poisoned_rows = base + [(1, 2024, 29, 500, 0.999), (1, 2025, 30, 500, 0.999)]
    poisoned = marcel_project_all(make_panel(poisoned_rows), "woba", 2024)
    pd.testing.assert_frame_equal(clean, poisoned)


def test_player_with_no_window_history_excluded():
    panel = make_panel([
        (1, 2023, 28, 500, 0.320),
        (2, 2019, 24, 500, 0.350),  # last seen 5 years before target
    ])
    out = marcel_project_all(panel, "woba", 2024)
    assert 1 in out.index
    assert 2 not in out.index


def test_default_ballast_constant():
    assert BALLAST_PA == 1200.0


def test_rate_clipped_at_zero():
    # Negative-capable synthetic stat pushed below zero by age decline still
    # clips at 0 (rates can't be negative).
    panel = make_panel([(1, 2023, 44, 600, 0.001)])
    rows = [(pid, 2023, 28, 600, 0.0) for pid in range(2, 20)]
    panel = pd.concat([panel, make_panel(rows)], ignore_index=True)
    out = marcel_project_all(panel, "woba", 2024)
    assert (out["proj_rate"] >= 0).all()
