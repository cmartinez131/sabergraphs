# Pitcher-awareness tests: guard allowlist, entity catalog merge, pitching
# stat chips, and the batting-only rookie scope. sqlite + stubs, no network.
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent import entities
from app.agent.sql_guard import SqlGuardError, guard_sql
from app.api.preflight import run_preflight
from app.db import directory

KERSHAW, SKENES, VOLPE, OHTANI = 477132, 694973, 683011, 660271

PITCHING = [
    (KERSHAW, "Clayton Kershaw", 2015, 2.13),
    (KERSHAW, "Clayton Kershaw", 2016, 1.69),
    (SKENES, "Paul Skenes", 2024, 1.96),
    (SKENES, "Paul Skenes", 2025, 2.10),
    (OHTANI, "Shohei Ohtani", 2023, 3.14),
]

BATTING = [
    (VOLPE, "Anthony Volpe", 2023, 541, 21),
    (KERSHAW, "Clayton Kershaw", 2015, 50, 0),   # NL-era pitcher batting rows
    (OHTANI, "Shohei Ohtani", 2023, 497, 44),    # real batting volume: two-way
    (OHTANI, "Shohei Ohtani", 2024, 636, 54),
]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    pd.DataFrame(
        [{"player_id": p, "full_name": n, "year": y, "ab": ab, "home_run": hr}
         for (p, n, y, ab, hr) in BATTING]
    ).to_sql("batting_stats", engine, index=False)
    pd.DataFrame(
        [{"player_id": p, "full_name": n, "year": y, "p_era": era,
          "p_win": 10, "p_formatted_ip": 150.0}
         for (p, n, y, era) in PITCHING]
    ).to_sql("pitching_stats", engine, index=False)
    entities.invalidate_catalog()
    monkeypatch.setattr(entities, "statsapi_search", lambda q: [])
    monkeypatch.setattr(directory, "fetch_people", lambda ids: {})
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    entities.invalidate_catalog()


# ----------------------- guard -----------------------
def test_pitching_stats_is_allowlisted():
    out = guard_sql(
        "SELECT full_name, p_era FROM pitching_stats "
        "WHERE year = 2024 AND p_formatted_ip >= 150 ORDER BY p_era ASC LIMIT 10"
    )
    assert "pitching_stats" in out


def test_raw_tables_still_rejected_after_expansion():
    with pytest.raises(SqlGuardError):
        guard_sql("SELECT * FROM raw_statcast_pitches LIMIT 5")


# ----------------------- entity catalog -----------------------
def test_pitcher_only_player_resolves(db):
    cat = entities.build_catalog(db)
    ms = entities.resolve_mentions("skenes era by season", cat,
                                   search_fn=lambda q: [])
    assert ms[0].status == "ok"
    c = ms[0].resolved
    assert c.has_pitching and not c.has_batting
    assert "pitching 2024–2025" in c.describe()


def test_two_way_rows_merge_onto_one_candidate(db):
    cat = entities.build_catalog(db)
    c = cat["by_id"][KERSHAW]
    assert c.has_batting and c.has_pitching
    assert "batting 2015" in c.describe() and "pitching 2015–2016" in c.describe()


# ----------------------- role classification -----------------------
def test_nl_era_pitcher_batting_rows_classify_as_pitcher(db):
    # Kershaw: 50 AB of NL-era batting + pitching seasons -> pitcher.
    cat = entities.build_catalog(db)
    assert cat["by_id"][KERSHAW].role == "pitcher"
    assert cat["by_id"][SKENES].role == "pitcher"
    assert cat["by_id"][VOLPE].role == "batter"
    assert cat["by_id"][OHTANI].role == "two_way"   # 566 avg AB + pitching


def test_statsapi_position_overrides_heuristic():
    c = entities.Candidate(name="X", player_id=1, has_batting=True,
                           has_pitching=True, career_ab=3730, bat_seasons=8)
    assert c.role == "two_way"           # Ohtani-shaped by the heuristic
    c.position = "P"
    assert c.role == "pitcher"           # directory says otherwise
    c.position = "TWP"
    assert c.role == "two_way"


# ----------------------- preflight -----------------------
def test_all_pitcher_pair_gets_pitching_stat_chips(db):
    # THE screenshot bug: Kershaw (has batting rows) vs a pitcher must NOT
    # offer Home Runs — both classify as pitchers -> pitching chips.
    pf = run_preflight(db, "skenes vs kershaw rookie season")
    q = [q for q in pf.questions if q["kind"] == "stat"][0]
    stats = {o["value"]["stat"] for o in q["options"]}
    assert "p_era" in stats and "home_run" not in stats
    assert any(o.get("recommended") and o["value"]["stat"] == "p_era"
               for o in q["options"])


def _stat_q(pf):
    return [q for q in pf.questions if q["kind"] == "stat"][0]


def test_disjoint_batter_pitcher_pair_offers_both_groups(db):
    # Volpe (batter) vs Skenes (pitcher): no shared surface -> both groups,
    # sectioned, nothing pre-selected — the ambiguity is the user's call.
    q = _stat_q(run_preflight(db, "volpe vs skenes rookie season"))
    stats = {o["value"]["stat"] for o in q["options"]}
    groups = {o.get("group") for o in q["options"]}
    assert "home_run" in stats and "p_era" in stats
    assert groups == {"Batting", "Pitching"}
    assert not any(o.get("recommended") for o in q["options"])


def test_two_way_with_batter_takes_batting_surface(db):
    # Ohtani vs Volpe: the shared surface is batting.
    q = _stat_q(run_preflight(db, "ohtani vs volpe rookie season"))
    stats = {o["value"]["stat"] for o in q["options"]}
    assert "home_run" in stats and "p_era" not in stats


def test_two_way_with_pitcher_takes_pitching_surface(db):
    # Ohtani vs Skenes: the shared surface is pitching.
    q = _stat_q(run_preflight(db, "ohtani vs skenes rookie season"))
    stats = {o["value"]["stat"] for o in q["options"]}
    assert "p_era" in stats and "home_run" not in stats


def test_two_way_alone_offers_both_groups(db):
    q = _stat_q(run_preflight(db, "compare ohtani rookie season"))
    groups = {o.get("group") for o in q["options"]}
    assert groups == {"Batting", "Pitching"}


def test_era_extracted_as_pitching_stat(db):
    pf = run_preflight(db, "skenes vs kershaw era in 2025")
    assert "p_era" in pf.stats
    assert pf.questions == []


# ----------------------- directory cache -----------------------
def test_directory_enriches_and_caches(db):
    calls = []

    def fake_fetch(ids):
        calls.append(sorted(ids))
        return {pid: {"full_name": "Paul Skenes", "position": "P",
                      "team": "Pittsburgh Pirates", "bats": "R",
                      "throws": "R", "active": True,
                      "mlb_debut": "2024-05-11"} for pid in ids}

    c = entities.Candidate(name="Paul Skenes", player_id=SKENES,
                           has_pitching=True)
    directory.enrich_candidates(db, [c], fetch_fn=fake_fetch)
    assert c.position == "P" and c.team == "Pittsburgh Pirates"
    assert calls == [[SKENES]]

    # Second call: served from the persistent cache, no fetch.
    c2 = entities.Candidate(name="Paul Skenes", player_id=SKENES,
                            has_pitching=True)
    directory.enrich_candidates(db, [c2], fetch_fn=fake_fetch)
    assert c2.team == "Pittsburgh Pirates"
    assert calls == [[SKENES]]


def test_directory_failure_is_silent(db):
    def broken_fetch(ids):
        raise RuntimeError("network down")

    c = entities.Candidate(name="Paul Skenes", player_id=999999,
                           has_pitching=True)
    directory.enrich_candidates(db, [c], fetch_fn=broken_fetch)  # no raise
    assert c.team is None


# ----------------------- clarified deterministic compare -----------------------
def test_clarified_compare_single_stat_single_year(db):
    from app.api.prompt import _clarified_compare
    players = [{"name": "Clayton Kershaw", "player_id": KERSHAW, "role": "pitcher"},
               {"name": "Paul Skenes", "player_id": SKENES, "role": "pitcher"}]
    res = _clarified_compare(db, players, ["p_era"], [2025], execute_db=db)
    assert res is None or res["ai_source"] == "deterministic"
    # Kershaw has no 2025 row in this fixture; Skenes does.
    assert res is not None
    data = {p["x"]: p["y"] for p in res["series"][0]["data"]}
    assert data == {"Paul Skenes": 2.10}
    assert any("No ERA for Clayton Kershaw in 2025" in w
               for w in res["meta"].get("warnings", []))


def test_clarified_compare_multi_stat_renders_facets(db):
    from app.api.prompt import _clarified_compare
    players = [{"name": "Clayton Kershaw", "player_id": KERSHAW, "role": "pitcher"}]
    res = _clarified_compare(db, players, ["p_era", "p_win"], [2015], execute_db=db)
    assert res["chart_type"] == "facet"
    assert [f["title"] for f in res["facets"]] == ["ERA", "Wins"]
    assert res["facets"][0]["series"][0]["data"] == [
        {"x": "Clayton Kershaw", "y": 2.13}]


def test_clarified_compare_year_range_is_line(db):
    from app.api.prompt import _clarified_compare
    players = [{"name": "Clayton Kershaw", "player_id": KERSHAW, "role": "pitcher"}]
    res = _clarified_compare(db, players, ["p_era"], [2015, 2016], execute_db=db)
    assert res["chart_type"] == "line"
    pts = {s["id"]: s["data"] for s in res["series"]}["Clayton Kershaw"]
    assert pts == [{"x": 2015, "y": 2.13}, {"x": 2016, "y": 1.69}]


def test_clarified_compare_shared_column_uses_role_context(db):
    from app.api.prompt import _clarified_compare
    # home_run exists in BOTH tables; an all-batter comparison must read
    # batting_stats (Volpe 21 HR), not the pitching table.
    players = [{"name": "Anthony Volpe", "player_id": VOLPE, "role": "batter"}]
    res = _clarified_compare(db, players, ["home_run"], [2023], execute_db=db)
    assert res["series"][0]["data"] == [{"x": "Anthony Volpe", "y": 21.0}]
