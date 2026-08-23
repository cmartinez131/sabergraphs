# Unit tests for the entity resolver (backend/app/agent/entities.py) —
# pure catalog dicts + injectable search, no database or network.
from app.agent import entities
from app.agent.common import STAT_ALIASES
from app.agent.entities import Candidate, resolve_mentions


def make_catalog(cands):
    """Mirror build_catalog()'s index shape over hand-built candidates."""
    by_full, by_last = {}, {}
    for c in cands:
        norm = entities.normalize(c.name)
        by_full.setdefault(norm, []).append(c)
        last = entities._last_name_token(norm)
        if last:
            by_last.setdefault(last, []).append(c)
    stat_tokens = set()
    for canon, phrases in STAT_ALIASES.items():
        for phrase in list(phrases) + [canon.replace("_", " ")]:
            for tok in entities.normalize(phrase).split():
                stat_tokens.add(tok)
    return {
        "by_full": by_full,
        "by_last": by_last,
        "stat_tokens": frozenset(stat_tokens),
        "stop": frozenset(entities._BASE_STOP | stat_tokens),
    }


VOLPE = Candidate(name="Anthony Volpe", player_id=683011, statsapi_id=683011,
                  first_year=2023, last_year=2025, position="SS")
JUDGE = Candidate(name="Aaron Judge", player_id=592450, statsapi_id=592450,
                  first_year=2016, last_year=2025, position="RF")
MUNCY_LAD = Candidate(name="Max Muncy", player_id=571970, statsapi_id=571970,
                      first_year=2015, last_year=2025, position="3B")
MUNCY_ATH = Candidate(name="Max Muncy", player_id=691777, statsapi_id=691777,
                      first_year=2025, last_year=2025)
LOMBARD_SR = Candidate(name="George Lombard", statsapi_id=136601,
                       played_first=1998, played_last=2006, source="chadwick")
LOMBARDOZZI = Candidate(name="Steve Lombardozzi Jr.", player_id=543459,
                        statsapi_id=543459, first_year=2015, last_year=2015)
WITT = Candidate(name="Bobby Witt Jr.", player_id=677951, statsapi_id=677951,
                 first_year=2022, last_year=2025, position="SS")
YOUNG = Candidate(name="Jacob Young", player_id=696285, statsapi_id=696285,
                  first_year=2023, last_year=2025, position="CF")

CATALOG = make_catalog([VOLPE, JUDGE, MUNCY_LAD, MUNCY_ATH, LOMBARD_SR,
                        LOMBARDOZZI, WITT, YOUNG])

LOMBARD_JR_API = Candidate(name="George Lombard Jr.", statsapi_id=806146,
                           position="SS", team="New York Yankees",
                           debut="2026-08-04", source="statsapi")


def no_search(_query):
    return []


def api_with_lombards(_query):
    return [LOMBARD_JR_API, LOMBARD_SR,
            Candidate(name="Steve Lombardozzi Jr.", statsapi_id=543459,
                      source="statsapi")]


def test_two_full_names_resolve_ok():
    ms = resolve_mentions("compare Anthony Volpe and Aaron Judge home runs",
                          CATALOG, search_fn=no_search)
    assert [m.status for m in ms] == ["ok", "ok"]
    assert ms[0].resolved.player_id == 683011
    assert ms[1].resolved.player_id == 592450


def test_lone_surnames_resolve_with_separator_context():
    ms = resolve_mentions("volpe vs judge home runs", CATALOG, search_fn=no_search)
    assert [m.resolved.name for m in ms] == ["Anthony Volpe", "Aaron Judge"]


def test_duplicate_name_is_ambiguous():
    ms = resolve_mentions("muncy vs judge home runs", CATALOG, search_fn=no_search)
    assert ms[0].status == "ambiguous"
    assert {c.player_id for c in ms[0].candidates} == {571970, 691777}


def test_suffix_filters_to_statsapi_prospect():
    # "lombard jr" must NOT resolve to the father (no Jr.) and must NOT
    # substring-match Lombardozzi; the StatsAPI fallback finds the prospect.
    ms = resolve_mentions("volpe vs lombard jr rookie season", CATALOG,
                          search_fn=api_with_lombards)
    lombard = [m for m in ms if "lombard" in m.text][0]
    assert lombard.status == "no_data"
    assert lombard.resolved.statsapi_id == 806146
    assert lombard.resolved.team == "New York Yankees"


def test_bare_lombard_is_ambiguous_father_vs_son():
    ms = resolve_mentions("volpe vs lombard rookie season", CATALOG,
                          search_fn=api_with_lombards)
    lombard = [m for m in ms if m.text == "lombard"][0]
    assert lombard.status == "ambiguous"
    names = {c.name for c in lombard.candidates}
    assert names == {"George Lombard", "George Lombard Jr."}  # no Lombardozzi


def test_surname_word_in_prose_is_not_a_mention():
    ms = resolve_mentions("top young players by ops in 2024", CATALOG,
                          search_fn=no_search)
    assert ms == []


def test_flagship_query_has_no_spurious_mentions():
    ms = resolve_mentions(
        "fastest average bat speed in 2025, minimum 100 competitive swings",
        CATALOG, search_fn=no_search)
    assert ms == []


def test_suffix_kept_on_local_match():
    ms = resolve_mentions("witt jr sprint speed 2024", CATALOG, search_fn=no_search)
    assert ms[0].status == "ok" and ms[0].resolved.player_id == 677951


def test_unknown_name_next_to_separator_reports_unknown():
    ms = resolve_mentions("compare zorbulon and judge home runs", CATALOG,
                          search_fn=no_search)
    zorb = [m for m in ms if m.text == "zorbulon"][0]
    assert zorb.status == "unknown"


def test_hint_pins_ambiguous_mention():
    ms = resolve_mentions(
        "muncy vs judge home runs", CATALOG,
        hints=[{"mention": "muncy", "player_id": 691777, "name": "Max Muncy"}],
        search_fn=no_search)
    assert ms[0].status == "ok" and ms[0].resolved.player_id == 691777


def test_hint_pins_no_data_person_with_details():
    ms = resolve_mentions(
        "volpe vs lombard jr rookie season", CATALOG,
        hints=[{"mention": "lombard jr", "statsapi_id": 806146,
                "name": "George Lombard Jr.", "debut": "2026-08-04",
                "team": "New York Yankees"}],
        search_fn=no_search)
    lombard = [m for m in ms if "lombard" in m.text][0]
    assert lombard.status == "no_data"
    assert lombard.resolved.debut == "2026-08-04"
