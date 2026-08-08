# Leakage tests for the max_year cutoff in the KNN-aging projection
# (backend/app/toolkit/aging.py).
#
# Gold test: projecting from a full 2015-2025 database with max_year=2020
# must produce EXACTLY the same output as projecting from a physically
# truncated database that only contains seasons <= 2020. If any query path
# missed the cutoff, the extra 2021-2025 rows would change the league curve,
# the comparable pool, or the comparables' future paths, and the outputs
# would diverge.
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine

from app.toolkit.aging import project_stat_aging_knn

N_PLAYERS = 40
YEARS = list(range(2015, 2026))
CUTOFF = 2020


def synthetic_frames(seed=42):
    rng = np.random.default_rng(seed)
    rows = []
    for pid in range(1, N_PLAYERS + 1):
        debut_age = int(rng.integers(21, 27))
        base_woba = float(rng.normal(0.320, 0.030))
        for i, year in enumerate(YEARS):
            age = debut_age + i
            # mild aging shape + noise; big post-cutoff shift so leakage
            # would visibly move the projection
            aging = -0.002 * abs(age - 27)
            shift = 0.080 if year > CUTOFF else 0.0
            woba = base_woba + aging + shift + float(rng.normal(0, 0.010))
            pa = int(rng.integers(150, 650))
            rows.append({
                "player_id": pid,
                "full_name": f"Player {pid}",
                "year": year,
                "player_age": age,
                "plate_appearances": pa,
                "batting_avg": round(woba * 0.8, 3),
                "on_base_percent": round(woba + 0.02, 3),
                "slg_percent": round(woba * 1.3, 3),
                "isolated_power": round(woba * 0.5, 3),
                "k_percent": 22.0,
                "bb_percent": 8.0,
                "sprint_speed": 27.0,
                "home_run": int(rng.integers(5, 40)),
                "woba": round(woba, 3),
            })
    batting = pd.DataFrame(rows)
    profiles = pd.DataFrame([
        {
            "player_id": pid,
            "height_in": 73,
            "weight_lb": 200,
            "bats": "R" if pid % 2 else "L",
            "throws": "R",
            "primary_position": ["1B", "2B", "SS", "CF"][pid % 4],
            "primary_position_name": "x",
            "is_active": True,
        }
        for pid in range(1, N_PLAYERS + 1)
    ])
    return batting, profiles


@pytest.fixture(scope="module")
def engines(tmp_path_factory):
    batting, profiles = synthetic_frames()
    base = tmp_path_factory.mktemp("aging")

    full = create_engine(f"sqlite:///{base}/full.db")
    batting.to_sql("batting_stats", full, index=False)
    profiles.to_sql("player_profiles", full, index=False)

    truncated = create_engine(f"sqlite:///{base}/truncated.db")
    batting[batting["year"] <= CUTOFF].to_sql("batting_stats", truncated, index=False)
    profiles.to_sql("player_profiles", truncated, index=False)
    return full, truncated


def project(engine, pid, max_year, horizon=2):
    return project_stat_aging_knn(
        db=None, db_engine=engine, player_id=pid, stat="woba",
        horizon=horizon, lookback=3, k=10, min_pa=100, max_year=max_year,
    )


def series_points(series):
    return {
        s["id"]: [(pt["x"], round(float(pt["y"]), 10)) for pt in s["data"]]
        for s in series
    }


def test_cutoff_equals_physically_truncated_db(engines):
    full, truncated = engines
    for pid in (1, 7, 23):
        s_cut, m_cut = project(full, pid, max_year=CUTOFF)
        s_trunc, m_trunc = project(truncated, pid, max_year=None)
        assert series_points(s_cut) == series_points(s_trunc), (
            f"player {pid}: max_year={CUTOFF} on the full DB differs from a "
            f"DB physically truncated at {CUTOFF} — a query is leaking "
            "post-cutoff seasons"
        )
        assert m_cut["baseline_year"] == m_trunc["baseline_year"] <= CUTOFF


def test_cutoff_baseline_never_after_max_year(engines):
    full, _ = engines
    _, meta = project(full, 3, max_year=CUTOFF)
    assert meta["baseline_year"] <= CUTOFF
    assert meta["max_year"] == CUTOFF


def test_default_uses_all_seasons(engines):
    full, _ = engines
    _, meta = project(full, 3, max_year=None)
    assert meta["baseline_year"] == max(YEARS)
    assert "max_year" not in meta


def test_low_pa_player_uses_fallback_base_without_crashing(engines):
    # Regression: a target player absent from the candidate pool (all their
    # seasons below the min_pa filter) goes through the fallback base-row
    # path, which used to KeyError on the missing feature columns.
    full, _ = engines
    batting, _profiles = synthetic_frames()
    low = batting[batting["player_id"] == 1].copy()
    low["player_id"] = 999
    low["plate_appearances"] = 40  # below min_pa=100 in every season
    low.to_sql("batting_stats", full, index=False, if_exists="append")

    series, meta = project(full, 999, max_year=CUTOFF)
    assert meta.get("warnings") is None
    assert series and series[0]["data"], "fallback path should still project"


def test_projection_actually_differs_with_and_without_cutoff(engines):
    # Sanity: the synthetic +0.080 post-2020 shift is large enough that an
    # uncapped projection must differ from the capped one — otherwise the
    # equivalence test above could pass vacuously.
    full, _ = engines
    s_cut, _ = project(full, 5, max_year=CUTOFF)
    s_all, _ = project(full, 5, max_year=None)
    assert series_points(s_cut) != series_points(s_all)
