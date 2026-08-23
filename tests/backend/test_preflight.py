# Unit tests for the /api/prompt preflight (backend/app/api/preflight.py):
# clarify decisions, gating, coverage and gap sentences. sqlite + stubbed
# StatsAPI — no network.
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent import entities
from app.api.preflight import (
    clarify_payload,
    coverage_note,
    gap_sentences,
    run_preflight,
)
from app.api.schemas import PlayerHint, PromptHints
from app.db import directory

BATTING = [
    (683011, "Anthony Volpe", 2023, 541, 21),
    (683011, "Anthony Volpe", 2024, 601, 12),
    (592450, "Aaron Judge", 2016, 84, 4),
    (592450, "Aaron Judge", 2017, 542, 52),
    (571970, "Max Muncy", 2015, 400, 20),
    (691777, "Max Muncy", 2025, 300, 10),
]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    pd.DataFrame(
        [{"player_id": p, "full_name": n, "year": y, "ab": ab, "home_run": hr}
         for (p, n, y, ab, hr) in BATTING]
    ).to_sql("batting_stats", engine, index=False)
    # No player_profiles / chadwick tables: preflight must degrade cleanly.
    entities.invalidate_catalog()
    monkeypatch.setattr(entities, "statsapi_search", lambda q: [])
    monkeypatch.setattr(directory, "fetch_people", lambda ids: {})
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    entities.invalidate_catalog()


def test_names_alone_pass_the_gate(db):
    pf = run_preflight(db, "volpe vs judge rookie season")
    assert pf.gate_ok
    assert pf.rookie


def test_gibberish_still_fails_the_gate(db):
    pf = run_preflight(db, "what is the weather in tokyo")
    assert not pf.gate_ok


def test_rookie_compare_without_stats_asks_stat_question(db):
    pf = run_preflight(db, "volpe vs judge rookie season")
    kinds = [q["kind"] for q in pf.questions]
    assert kinds == ["stat"]
    payload = clarify_payload(pf)
    assert payload["chart_type"] == "clarify"
    assert payload["clarification"][0]["multi"] is True


def test_stat_present_means_no_question(db):
    pf = run_preflight(db, "compare volpe and judge home runs in their rookie seasons")
    assert pf.questions == []
    assert pf.stats[0] == "home_run"
    assert len(pf.ok_players) == 2


def test_ambiguous_name_asks_player_question(db):
    pf = run_preflight(db, "muncy vs judge home runs")
    q = [q for q in pf.questions if q["kind"] == "player"][0]
    assert q["mention"] == "muncy"
    ids = {o["value"]["player_id"] for o in q["options"]}
    assert ids == {571970, 691777}


def test_player_hint_suppresses_question(db):
    hints = PromptHints(players=[PlayerHint(mention="muncy", player_id=691777,
                                            name="Max Muncy")])
    pf = run_preflight(db, "muncy vs judge home runs", hints=hints)
    assert [q for q in pf.questions if q["kind"] == "player"] == []
    assert {m.resolved.player_id for m in pf.ok_players} == {691777, 592450}


def test_stat_hints_replace_extraction(db):
    hints = PromptHints(stats=["batting_avg", "home_run"])
    pf = run_preflight(db, "volpe vs judge rookie season", hints=hints)
    assert pf.questions == []
    assert pf.stats == ["batting_avg", "home_run"]


def test_no_data_hint_produces_specific_gap_sentence(db):
    hints = PromptHints(players=[PlayerHint(
        mention="lombard jr", statsapi_id=806146, name="George Lombard Jr.",
        debut="2026-08-04", team="New York Yankees")])
    pf = run_preflight(db, "volpe vs lombard jr rookie season", hints=hints)
    notes = gap_sentences(pf)
    assert len(notes) == 1
    assert "George Lombard Jr." in notes[0]
    assert "2026-08-04" in notes[0] and "Yankees" in notes[0]
    assert "2023–2025" in notes[0] or "2015" in notes[0]


def test_coverage_note_for_future_year(db):
    pf = run_preflight(db, "top home run hitters in 2030")
    note = coverage_note(pf)
    assert note is not None and "2030" in note
