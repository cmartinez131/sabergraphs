# Unit tests for career-aligned comparisons (backend/app/toolkit/aligned.py)
# against sqlite fixtures + the real player_season_index view.
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.season_index import ensure_player_season_index
from app.toolkit.aligned import compare_first_n_seasons, compare_rookie_seasons

JUDGE, VOLPE, VET = 1, 2, 3

BATTING = [
    # player_id, name, year, ab, hr, avg
    (JUDGE, "Judge Test", 2016, 84, 4, 0.179),
    (JUDGE, "Judge Test", 2017, 542, 52, 0.284),
    (JUDGE, "Judge Test", 2018, 413, 27, 0.278),
    (VOLPE, "Volpe Test", 2023, 541, 21, 0.209),
    (VOLPE, "Volpe Test", 2024, 601, 12, 0.243),
    (VET, "Old Vet", 2015, 550, 30, 0.301),   # Chadwick debut 2010 -> censored
    (VET, "Old Vet", 2016, 540, 28, 0.295),
]

CHADWICK = [
    (JUDGE, "Judge", "Test", 2016, 2025),
    (VOLPE, "Volpe", "Test", 2023, 2026),
    (VET, "Old", "Vet", 2010, 2016),
]


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    base = tmp_path_factory.mktemp("aligned")
    engine = create_engine(f"sqlite:///{base}/t.db")
    pd.DataFrame(
        [{"player_id": p, "full_name": n, "year": y, "ab": ab,
          "home_run": hr, "batting_avg": avg, "plate_appearances": ab + 60}
         for (p, n, y, ab, hr, avg) in BATTING]
    ).to_sql("batting_stats", engine, index=False)
    pd.DataFrame(CHADWICK, columns=[
        "key_mlbam", "name_first", "name_last",
        "mlb_played_first", "mlb_played_last"]).to_sql(
        "raw_chadwick_people", engine, index=False)
    assert ensure_player_season_index(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_rookie_compare_labels_each_players_own_year(db):
    res = compare_rookie_seasons(db, [JUDGE, VOLPE], ["home_run"])
    assert res["chart_type"] == "bar"
    data = {p["x"]: p["y"] for p in res["series"][0]["data"]}
    # Judge's rookie season is 2017 (52 HR), NOT his 2016 cup of coffee.
    assert data == {"Judge Test (2017)": 52.0, "Volpe Test (2023)": 21.0}
    assert res["meta"]["player_years"] == {"Judge Test": 2017, "Volpe Test": 2023}
    assert "Judge Test (2017)" in res["narration"]


def test_rookie_compare_multi_stat_renders_facets(db):
    # 21 HR and a .209 average cannot share one axis — one facet per stat.
    res = compare_rookie_seasons(db, [JUDGE, VOLPE], ["home_run", "batting_avg"])
    assert res["chart_type"] == "facet"
    assert [f["title"] for f in res["facets"]] == ["Home Runs", "Batting Average"]
    avg = {p["x"]: p["y"] for p in res["facets"][1]["series"][0]["data"]}
    assert avg["Volpe Test (2023)"] == pytest.approx(0.209)
    assert all(f["chart_type"] == "bar" for f in res["facets"])


def test_rookie_compare_censored_player_is_explained_not_plotted(db):
    res = compare_rookie_seasons(db, [JUDGE, VET], ["home_run"])
    xs = [p["x"] for p in res["series"][0]["data"]]
    assert xs == ["Judge Test (2017)"]
    assert any("debuted before" in w for w in res["meta"]["warnings"])
    assert "Old Vet" in res["narration"]


def test_rookie_compare_notes_are_appended(db):
    res = compare_rookie_seasons(db, [VOLPE], ["home_run"],
                                 notes=["No data for George Lombard Jr."])
    assert "George Lombard Jr." in res["narration"]


def test_first_n_seasons_aligns_on_career_season_number(db):
    res = compare_first_n_seasons(db, [JUDGE, VOLPE], "home_run", n=2)
    assert res["chart_type"] == "line"
    by_id = {s["id"]: s["data"] for s in res["series"]}
    judge = by_id["Judge Test (2016–)"]
    volpe = by_id["Volpe Test (2023–)"]
    assert [p["x"] for p in judge] == [1, 2] and judge[1]["y"] == 52.0
    assert [p["x"] for p in volpe] == [1, 2] and volpe[0]["y"] == 21.0
    assert res["meta"]["season_years"]["Judge Test"] == {1: 2016, 2: 2017}


def test_first_n_skips_censored_players(db):
    res = compare_first_n_seasons(db, [VOLPE, VET], "home_run", n=2)
    assert [s["id"] for s in res["series"]] == ["Volpe Test (2023–)"]
    assert any("career season numbers unknown" in w
               for w in res["meta"]["warnings"])
