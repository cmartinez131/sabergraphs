# Unit tests for the bat-tracking toolkit (backend/app/toolkit/battracking.py)
# against sqlite fixtures — no Postgres needed.
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.toolkit.battracking import (
    bat_speed_profile,
    bat_speed_vs_production,
    blast_leaderboard,
    latest_tracking_season,
)

# player_id, name, season, swings, bat_speed, blast, squared_up, whiff, woba
FIXTURE = [
    (1, "Fast Fred",    2025, 500, 78.0, 0.20, 0.30, 0.25, 0.400),
    (2, "Mid Mike",     2025, 400, 72.0, 0.15, 0.25, 0.22, 0.330),
    (3, "Slow Sam",     2025, 300, 66.0, 0.10, 0.20, 0.20, 0.300),
    (4, "Tiny Tim",     2025,  20, 80.0, 0.25, 0.35, 0.30, 0.280),  # under min swings
    (5, "Last Yr Lou",  2024, 350, 70.0, 0.12, 0.22, 0.21, 0.310),
]


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    base = tmp_path_factory.mktemp("battracking")
    engine = create_engine(f"sqlite:///{base}/t.db")

    mart = pd.DataFrame(
        [
            {
                "batter_mlbam": pid, "season": season, "full_name": name,
                "competitive_swings": swings, "avg_bat_speed": speed,
                "fast_swing_rate": 0.30, "avg_swing_length": 7.2,
                "squared_up_rate": squared, "blast_rate": blast,
                "swords": 3, "whiff_rate": whiff, "contact": 300,
                "whiffs": 80, "batted_ball_events": 200,
                "batter_run_value": 5.0,
            }
            for (pid, name, season, swings, speed, blast, squared, whiff, _w) in FIXTURE
        ]
    )
    mart.to_sql("mart_bat_tracking_season", engine, index=False)

    batting = pd.DataFrame(
        [
            {
                "player_id": pid, "year": season, "full_name": name,
                "plate_appearances": 500, "player_age": 27, "home_run": 20,
                "batting_avg": 0.270, "woba": woba,
                "barrel_batted_rate": 10.0, "sprint_speed": 27.0,
            }
            for (pid, name, season, _s, _sp, _b, _sq, _w, woba) in FIXTURE
        ]
    )
    batting.to_sql("batting_stats", engine, index=False)

    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_latest_tracking_season(db):
    assert latest_tracking_season(db) == 2025


class TestBlastLeaderboard:
    def test_orders_and_qualifies(self, db):
        res = blast_leaderboard(db, season=2025, stat="blast_rate", min_swings=100)
        assert res["chart_type"] == "bar"
        names = [p["x"] for p in res["series"][0]["data"]]
        # Tiny Tim (20 swings) excluded despite the top blast rate
        assert names == ["Fast Fred", "Mid Mike", "Slow Sam"]
        assert res["meta"]["qualifier"] == {"column": "competitive_swings", "min": 100}

    def test_ascending_order_and_limit(self, db):
        res = blast_leaderboard(
            db, season=2025, stat="avg_bat_speed", min_swings=100,
            order="asc", limit=2,
        )
        names = [p["x"] for p in res["series"][0]["data"]]
        assert names == ["Slow Sam", "Mid Mike"]

    def test_defaults_to_latest_season(self, db):
        res = blast_leaderboard(db, min_swings=100)
        assert res["meta"]["season"] == 2025

    def test_unknown_stat_rejected(self, db):
        with pytest.raises(ValueError, match="Unknown bat-tracking stat"):
            blast_leaderboard(db, season=2025, stat="pg_sleep")


class TestBatSpeedProfile:
    def test_percentiles_and_league_median(self, db):
        res = bat_speed_profile(db, player="Fast Fred", season=2025, min_swings=100)
        assert res["chart_type"] == "radar"
        by_stat = {row["stat"]: row for row in res["series"]}
        # Fast Fred has the top bat speed of the 3 qualified -> 100th pctile
        assert by_stat["avg_bat_speed"]["Fast Fred"] == pytest.approx(100.0)
        # Every spoke carries the league-median anchor at 50
        assert all(row["League median"] == 50.0 for row in res["series"])
        # Contact spoke = percentile of (1 - whiff): Fred has the WORST
        # contact of the qualified three -> lowest percentile
        assert by_stat["contact_rate_tracking"]["Fast Fred"] == pytest.approx(100 / 3)
        assert res["meta"]["qualified_pool"] == 3

    def test_player_by_id(self, db):
        res = bat_speed_profile(db, player=3, season=2025, min_swings=100)
        assert any("Slow Sam" in row for row in res["series"])

    def test_missing_player_warns(self, db):
        res = bat_speed_profile(db, player="Nobody", season=2025)
        assert res["meta"]["warnings"] == ["player_not_found"]
        assert res["series"] == []


class TestBatSpeedVsProduction:
    def test_binned_means_and_correlation(self, db):
        res = bat_speed_vs_production(
            db, season=2025, production_stat="woba", min_swings=100, bin_width=1.0
        )
        assert res["chart_type"] == "line"
        pts = {p["x"]: p for p in res["series"][0]["data"]}
        # One qualified player per 1-mph bin: bin means are the raw wobas
        assert pts[78.5]["y"] == pytest.approx(0.400)
        assert pts[72.5]["y"] == pytest.approx(0.330)
        assert pts[66.5]["y"] == pytest.approx(0.300)
        assert all(p["n"] == 1 for p in pts.values())
        # Speeds and woba are monotonically aligned -> strong positive r
        assert res["meta"]["pearson_r"] > 0.95
        assert res["meta"]["players"] == 3

    def test_too_few_players_warns(self, db):
        res = bat_speed_vs_production(db, season=2024, min_swings=100)
        assert res["meta"]["warnings"] == ["not_enough_players"]
