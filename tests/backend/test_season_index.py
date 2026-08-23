# Unit tests for the player_season_index view (backend/app/db/season_index.py)
# against sqlite — the SAME SQL that runs in production Postgres.
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from app.db.season_index import ensure_player_season_index

JUDGE, VOLPE, COFFEE, VET, NOCHAD = 1, 2, 3, 4, 5

BATTING = [
    # player_id, year, ab   — the Judge shape: 84 AB cup of coffee, then a
    # full season still inside rookie eligibility (career AB <= 130).
    (JUDGE, 2016, 84), (JUDGE, 2017, 542), (JUDGE, 2018, 600),
    # Volpe shape: full rookie year immediately.
    (VOLPE, 2023, 541), (VOLPE, 2024, 601),
    # Multi-sip coffee: eligibility survives two small seasons.
    (COFFEE, 2019, 10), (COFFEE, 2020, 25), (COFFEE, 2021, 400),
    # Veteran first observed at the panel edge; Chadwick says debut 2010.
    (VET, 2015, 550), (VET, 2016, 540),
    # Panel-edge player with NO Chadwick row: conservatively censored.
    (NOCHAD, 2015, 300), (NOCHAD, 2016, 450),
]

CHADWICK = [
    (JUDGE, "Aaron", "Judge", 2016, 2025),
    (VOLPE, "Anthony", "Volpe", 2023, 2026),
    (COFFEE, "Cup", "Coffee", 2019, 2021),
    (VET, "Old", "Vet", 2010, 2016),
    # NOCHAD deliberately absent
]


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    base = tmp_path_factory.mktemp("season_index")
    eng = create_engine(f"sqlite:///{base}/t.db")
    pd.DataFrame(BATTING, columns=["player_id", "year", "ab"]).to_sql(
        "batting_stats", eng, index=False)
    pd.DataFrame(CHADWICK, columns=[
        "key_mlbam", "name_first", "name_last",
        "mlb_played_first", "mlb_played_last"]).to_sql(
        "raw_chadwick_people", eng, index=False)
    assert ensure_player_season_index(eng)
    return eng


def rows_for(engine, pid):
    with engine.connect() as conn:
        rs = conn.execute(text(
            "SELECT year, season_number, prior_ab, rookie_season_year, "
            "rookie_pre_panel, is_rookie_season "
            "FROM player_season_index WHERE player_id = :p ORDER BY year"
        ), {"p": pid}).mappings().all()
    return [dict(r) for r in rs]


def test_judge_shape_rookie_is_second_season(engine):
    rows = rows_for(engine, JUDGE)
    assert [r["season_number"] for r in rows] == [1, 2, 3]
    assert [r["prior_ab"] for r in rows] == [0, 84, 626]
    # 84 career AB entering 2017 -> still rookie-eligible -> rookie = 2017
    assert [r["is_rookie_season"] for r in rows] == [0, 1, 0]
    assert rows[0]["rookie_season_year"] == 2017


def test_full_first_season_is_rookie(engine):
    rows = rows_for(engine, VOLPE)
    assert [r["is_rookie_season"] for r in rows] == [1, 0]


def test_multiple_cups_of_coffee(engine):
    rows = rows_for(engine, COFFEE)
    # prior AB entering 2021 is 35 <= 130 -> rookie season is 2021
    assert rows[-1]["is_rookie_season"] == 1
    assert [r["is_rookie_season"] for r in rows] == [0, 0, 1]


def test_pre_panel_debut_is_censored_via_chadwick(engine):
    rows = rows_for(engine, VET)
    assert all(r["rookie_pre_panel"] == 1 for r in rows)
    assert all(r["is_rookie_season"] == 0 for r in rows)


def test_panel_edge_without_chadwick_is_censored(engine):
    rows = rows_for(engine, NOCHAD)
    assert all(r["rookie_pre_panel"] == 1 for r in rows)
    assert all(r["is_rookie_season"] == 0 for r in rows)


def test_post_edge_players_are_not_censored(engine):
    for pid in (JUDGE, VOLPE, COFFEE):
        assert all(r["rookie_pre_panel"] == 0 for r in rows_for(engine, pid))
