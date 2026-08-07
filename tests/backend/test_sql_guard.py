"""Adversarial test suite for the NL->SQL safety layer (AUDIT B1/B2).

Every payload in ADVERSARIAL must be rejected with SqlGuardError.
Every query in LEGITIMATE must pass and come back execution-ready.
The suite runs without a database: sql_guard is pure string analysis.
"""

import pytest

from app.agent.sql_guard import (
    ALLOWED_TABLES,
    DEFAULT_MAX_ROWS,
    SqlGuardError,
    guard_sql,
    strip_sql_comments,
    tables_in_from_join,
)


# ----------------------------------------------------------------------
# Adversarial payloads — all must raise SqlGuardError
# ----------------------------------------------------------------------
ADVERSARIAL = [
    # --- multi-statement / stacked semicolons (B2: the second statement executed) ---
    pytest.param(
        "SELECT b.full_name FROM batting_stats b "
        "JOIN player_profiles p ON p.player_id = b.player_id LIMIT 1; "
        "SET statement_timeout='999s'",
        id="b2-repro-select-then-set",
    ),
    pytest.param(
        "SELECT full_name FROM batting_stats; DROP TABLE batting_stats",
        id="select-then-drop",
    ),
    pytest.param(
        "SELECT full_name FROM batting_stats;; SELECT 1",
        id="stacked-semicolons",
    ),
    pytest.param(
        "SELECT full_name FROM batting_stats LIMIT 1; "
        "COPY batting_stats TO PROGRAM 'rm -rf /'",
        id="select-then-copy-to-program",
    ),
    pytest.param(
        "SELECT full_name FROM batting_stats LIMIT 1; DELETE FROM batting_stats",
        id="select-then-delete",
    ),
    # --- comment-hidden keywords ---
    pytest.param(
        "SEL/**/ECT * FROM batting_stats",
        id="comment-split-select",
    ),
    pytest.param(
        "SELECT full_name FROM batting_stats /*; DROP TABLE x */; DELETE FROM batting_stats",
        id="block-comment-then-second-statement",
    ),
    pytest.param(
        "SELECT full_name FROM batting_stats -- harmless comment\n; DROP TABLE batting_stats",
        id="line-comment-then-second-statement",
    ),
    pytest.param(
        "/* leading comment */ DELETE FROM batting_stats",
        id="leading-comment-hides-delete",
    ),
    # --- non-allowlisted FROM / JOIN tables (B1: FROM was never checked) ---
    pytest.param(
        "SELECT * FROM users",
        id="forbidden-from-table",
    ),
    pytest.param(
        "SELECT * FROM secret_admin_table s "
        "JOIN player_profiles p ON p.player_id = s.player_id LIMIT 5",
        id="b1-repro-forbidden-from-allowed-join",
    ),
    pytest.param(
        "SELECT b.full_name FROM batting_stats b "
        "JOIN admin_users a ON a.player_id = b.player_id",
        id="forbidden-join-table",
    ),
    pytest.param(
        "SELECT * FROM batting_stats b, secret_table s "
        "WHERE s.player_id = b.player_id",
        id="forbidden-table-in-comma-from-list",
    ),
    pytest.param(
        "SELECT * FROM (SELECT * FROM batting_stats) x, secret_table s "
        "WHERE s.player_id = 1",
        id="forbidden-table-hidden-behind-derived-table",
    ),
    # --- pg_sleep DoS / system surfaces ---
    pytest.param(
        "SELECT pg_sleep(60)",
        id="pg-sleep-bare",
    ),
    pytest.param(
        "SELECT pg_sleep(60), full_name FROM batting_stats",
        id="pg-sleep-with-table",
    ),
    pytest.param(
        "SELECT table_name FROM information_schema.tables",
        id="information-schema",
    ),
    pytest.param(
        "SELECT * FROM pg_catalog.pg_tables",
        id="pg-catalog",
    ),
    # --- UNION smuggling ---
    pytest.param(
        "SELECT full_name FROM batting_stats "
        "UNION SELECT usename FROM pg_user",
        id="union-into-pg-user",
    ),
    pytest.param(
        "SELECT full_name FROM batting_stats "
        "UNION SELECT full_name FROM batting_stats",
        id="union-even-between-allowed-tables",
    ),
    # --- CTE smuggling ---
    pytest.param(
        "WITH x AS (SELECT * FROM batting_stats) DELETE FROM batting_stats",
        id="cte-smuggled-delete",
    ),
    pytest.param(
        "WITH x AS (SELECT 1) SELECT * FROM x",
        id="cte-not-leading-select",
    ),
    # --- write shapes ---
    pytest.param(
        "INSERT INTO batting_stats (player_id, year) VALUES (1, 2024)",
        id="insert",
    ),
    pytest.param(
        "SELECT * INTO evil_copy FROM batting_stats",
        id="select-into-creates-table",
    ),
    pytest.param(
        "UPDATE batting_stats SET home_run = 99",
        id="update",
    ),
    # --- quoting / escaping obfuscation ---
    pytest.param(
        'SELECT * FROM "batting_stats" WHERE year = 2024',
        id="double-quoted-identifier",
    ),
    pytest.param(
        "SELECT $$; DROP TABLE batting_stats; $$ FROM batting_stats",
        id="dollar-quoting",
    ),
    pytest.param(
        "SELECT '\\'; DROP TABLE batting_stats; --' FROM batting_stats",
        id="backslash-escape-trick",
    ),
    pytest.param(
        "SELECT 'unterminated FROM batting_stats",
        id="unterminated-string-literal",
    ),
    # --- join-alignment rules ---
    pytest.param(
        "SELECT * FROM batting_stats b "
        "JOIN player_profiles p ON p.team = b.team",
        id="join-without-player-id",
    ),
    pytest.param(
        "SELECT * FROM batting_stats b "
        "JOIN player_features f ON f.player_id = b.player_id",
        id="features-join-without-year",
    ),
    # --- degenerate inputs ---
    pytest.param("", id="empty-string"),
    pytest.param("   ;  ", id="whitespace-and-semicolon"),
    pytest.param("EXPLAIN ANALYZE SELECT * FROM batting_stats", id="explain-analyze"),
]


@pytest.mark.parametrize("payload", ADVERSARIAL)
def test_adversarial_payload_rejected(payload):
    with pytest.raises(SqlGuardError):
        guard_sql(payload)


def test_none_rejected():
    with pytest.raises(SqlGuardError):
        guard_sql(None)


# ----------------------------------------------------------------------
# Legitimate queries — all must pass
# ----------------------------------------------------------------------
LEGITIMATE = [
    pytest.param(
        "SELECT full_name AS name, home_run FROM batting_stats "
        "WHERE year = 2024 ORDER BY home_run DESC LIMIT 10;",
        id="single-table-leaderboard",
    ),
    pytest.param(
        "SELECT b.year AS year, b.slg_percent FROM batting_stats b "
        "WHERE b.full_name ILIKE '%judge%' AND b.year BETWEEN 2022 AND 2025 "
        "ORDER BY year ASC;",
        id="single-player-season-range",
    ),
    pytest.param(
        "SELECT b.full_name AS name, "
        "(b.on_base_percent + b.slg_percent) AS on_base_plus_slg, b.home_run "
        "FROM batting_stats b "
        "JOIN player_profiles p ON p.player_id = b.player_id "
        "WHERE b.year = 2024 AND p.bats = 'L' "
        "AND (b.on_base_percent + b.slg_percent) > 0.850 "
        "ORDER BY b.home_run DESC LIMIT 15;",
        id="join-profiles-with-filters",
    ),
    pytest.param(
        "SELECT p.primary_position AS pos, "
        "AVG(b.on_base_percent + b.slg_percent) AS on_base_plus_slg "
        "FROM batting_stats b "
        "JOIN player_profiles p ON p.player_id = b.player_id "
        "WHERE b.year = 2023 AND b.plate_appearances >= 300 "
        "AND p.primary_position IN ('3B','SS') "
        "GROUP BY p.primary_position ORDER BY on_base_plus_slg DESC;",
        id="aggregate-by-position",
    ),
    pytest.param(
        "SELECT b.year AS year, b.full_name AS name, f.woba_3yr "
        "FROM batting_stats b "
        "JOIN player_features f ON f.player_id = b.player_id AND f.year = b.year "
        "WHERE b.year BETWEEN 2019 AND 2021 "
        "AND b.full_name IN ('José Ramírez','Rafael Devers') "
        "ORDER BY year ASC;",
        id="features-join-aligned-on-year",
    ),
    pytest.param(
        "SELECT b.full_name, b.home_run FROM batting_stats b "
        "WHERE b.full_name ILIKE '%Grant%' LIMIT 5;",
        id="player-name-contains-denied-keyword",
    ),
]


@pytest.mark.parametrize("query", LEGITIMATE)
def test_legitimate_query_passes(query):
    result = guard_sql(query)
    assert result.lower().lstrip().startswith("select")
    assert result.rstrip().endswith(";")


# ----------------------------------------------------------------------
# LIMIT enforcement
# ----------------------------------------------------------------------
def test_missing_limit_gets_capped():
    result = guard_sql("SELECT full_name FROM batting_stats WHERE year = 2024")
    assert result.rstrip().endswith(f"LIMIT {DEFAULT_MAX_ROWS};")


def test_oversized_limit_is_reduced():
    result = guard_sql("SELECT full_name FROM batting_stats LIMIT 100000")
    assert f"LIMIT {DEFAULT_MAX_ROWS}" in result
    assert "100000" not in result


def test_reasonable_limit_is_preserved():
    result = guard_sql("SELECT full_name FROM batting_stats LIMIT 10")
    assert "LIMIT 10" in result


def test_subquery_limit_does_not_satisfy_outer_cap():
    result = guard_sql(
        "SELECT b.full_name FROM batting_stats b WHERE b.player_id IN "
        "(SELECT p.player_id FROM player_profiles p LIMIT 5)"
    )
    # the inner LIMIT 5 must not count as the outer statement's limit
    assert result.rstrip().endswith(f"LIMIT {DEFAULT_MAX_ROWS};")
    assert "LIMIT 5" in result  # inner limit untouched


def test_non_integer_limit_rejected():
    with pytest.raises(SqlGuardError):
        guard_sql("SELECT full_name FROM batting_stats LIMIT ALL")


# ----------------------------------------------------------------------
# B1 regression: FROM-table extraction
# ----------------------------------------------------------------------
def test_single_table_from_is_detected():
    assert tables_in_from_join(
        "SELECT full_name, home_run FROM batting_stats WHERE year = 2024 "
        "ORDER BY home_run DESC LIMIT 10;"
    ) == ["batting_stats"]


def test_from_and_join_tables_both_detected():
    assert tables_in_from_join(
        "SELECT * FROM secret_admin_table s "
        "JOIN player_profiles p ON p.player_id = s.player_id LIMIT 5"
    ) == ["secret_admin_table", "player_profiles"]


def test_comma_from_list_detected():
    assert tables_in_from_join(
        "SELECT * FROM batting_stats b, player_profiles p "
        "WHERE p.player_id = b.player_id"
    ) == ["batting_stats", "player_profiles"]


def test_derived_table_inner_tables_detected():
    assert tables_in_from_join(
        "SELECT * FROM (SELECT * FROM batting_stats) x, player_seasons s"
    ) == ["batting_stats", "player_seasons"]


# ----------------------------------------------------------------------
# Comment stripping (string-aware, Postgres semantics)
# ----------------------------------------------------------------------
def test_line_comments_are_stripped():
    # the old implementation compared one char against "--" and never
    # stripped line comments at all
    out = strip_sql_comments("SELECT 1 -- comment\nFROM batting_stats")
    assert "comment" not in out
    assert "FROM batting_stats" in out


def test_comment_inside_string_is_preserved():
    out = strip_sql_comments("SELECT '--not a comment' FROM batting_stats")
    assert "--not a comment" in out


def test_block_comment_becomes_token_separator():
    # 'SEL/**/ECT' must not fuse into SELECT (Postgres treats comments as
    # token separators)
    out = strip_sql_comments("SEL/**/ECT 1")
    assert "SELECT" not in out


# ----------------------------------------------------------------------
# Read-only URL derivation (requires sqlalchemy; skipped if absent)
# ----------------------------------------------------------------------
def test_readonly_url_swaps_credentials_only():
    pytest.importorskip("sqlalchemy")
    from app.db.database import _derive_readonly_url, READONLY_ROLE

    url = _derive_readonly_url()
    # accept either the derived URL or an explicit READONLY_DATABASE_URL
    import os
    if not os.getenv("READONLY_DATABASE_URL"):
        from sqlalchemy.engine import make_url
        main = make_url(os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg2://user:password@db:5432/baseball_db",
        ))
        derived = make_url(str(url)) if isinstance(url, str) else url
        assert derived.username == READONLY_ROLE
        assert derived.host == main.host
        assert derived.database == main.database


def test_allowed_tables_frozen():
    assert isinstance(ALLOWED_TABLES, frozenset)
    assert "batting_stats" in ALLOWED_TABLES
