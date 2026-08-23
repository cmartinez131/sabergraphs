# backend/app/db/season_index.py
"""player_season_index — a derived VIEW that turns "rookie season" and
"career season N" from LLM guesswork into database columns.

Why a view: the NL->SQL planner can only reference relations, and the season
alignment must come from the data — before this existed, the planner picked
"Judge's rookie year" from the model's world knowledge, which violates the
core invariant (the LLM never generates data) and silently fails for
non-famous players.

Columns (grain: player_id x year, mirroring batting_stats):
    season_number       1..N rank of this year among the player's observed years
    prior_ab            career AB accumulated BEFORE this season (observed panel)
    first_observed_year first year the player appears in batting_stats
    rookie_season_year  the player's rookie season under the rule below (or NULL)
    rookie_pre_panel    1 = the player's true rookie season predates the panel
                        (debuted before the data starts) — rookie unknown here
    is_rookie_season    1 on exactly the rookie-season row; always 0 when
                        rookie_pre_panel = 1

Rookie rule: the LAST observed season entered with career AB <= 130 — an
approximation of MLB Rule 5.10(b) rookie eligibility (the 45-days-on-roster
criterion is not modeled; hitters only). Judge is the canonical case: 84 AB
in 2016 means he entered 2017 still rookie-eligible, so his rookie season is
2017 (52 HR), not his 4-HR 2016 cup of coffee.

Censoring: the panel starts in 2015, so a player first observed in 2015 may
have debuted earlier. raw_chadwick_people.mlb_played_first (Chadwick
register) detects that; when Chadwick is absent (CSV-only installs that
skipped the pipeline) every 2015 first-observation is conservatively marked
pre-panel.

The view is provisioned idempotently at backend startup (same pattern as the
read-only role and history tables), and the SQL is portable Postgres/SQLite
so the exact production definition is unit-tested against SQLite fixtures.
"""
import logging

from sqlalchemy import inspect as sa_inspect, text

logger = logging.getLogger("app.season_index")

VIEW_NAME = "player_season_index"

# Censoring clause variants: with and without the Chadwick register.
_CENSOR_WITH_CHADWICK = """
            CASE
                WHEN c.mlb_played_first IS NOT NULL
                     AND c.mlb_played_first < obs.first_observed_year THEN 1
                WHEN c.key_mlbam IS NULL
                     AND obs.first_observed_year <= (SELECT MIN(year) FROM batting_stats) THEN 1
                ELSE 0
            END AS rookie_pre_panel
        FROM obs
        LEFT JOIN raw_chadwick_people c ON c.key_mlbam = obs.player_id
"""

_CENSOR_WITHOUT_CHADWICK = """
            CASE
                WHEN obs.first_observed_year <= (SELECT MIN(year) FROM batting_stats) THEN 1
                ELSE 0
            END AS rookie_pre_panel
        FROM obs
"""


def view_select_sql(with_chadwick=True):
    """The SELECT body of the view. Portable: window functions + CTEs only."""
    censor = _CENSOR_WITH_CHADWICK if with_chadwick else _CENSOR_WITHOUT_CHADWICK
    return f"""
    WITH obs AS (
        SELECT
            player_id,
            year,
            COALESCE(ab, 0) AS ab,
            ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY year) AS season_number,
            COALESCE(SUM(COALESCE(ab, 0)) OVER (
                PARTITION BY player_id ORDER BY year
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ), 0) AS prior_ab,
            MIN(year) OVER (PARTITION BY player_id) AS first_observed_year
        FROM batting_stats
    ),
    cens AS (
        SELECT
            obs.player_id, obs.year, obs.season_number, obs.prior_ab,
            obs.first_observed_year,
{censor}
    ),
    flagged AS (
        SELECT
            cens.*,
            MAX(CASE WHEN prior_ab <= 130 THEN year END)
                OVER (PARTITION BY player_id) AS rookie_season_year
        FROM cens
    )
    SELECT
        player_id,
        year,
        season_number,
        prior_ab,
        first_observed_year,
        rookie_season_year,
        rookie_pre_panel,
        CASE WHEN rookie_pre_panel = 0 AND year = rookie_season_year
             THEN 1 ELSE 0 END AS is_rookie_season
    FROM flagged
    """


def ensure_player_season_index(engine):
    """Idempotently (re)create the view on `engine`. Safe on Postgres and
    SQLite; picks the Chadwick-aware variant when the register is loaded."""
    inspector = sa_inspect(engine)
    tables = set(inspector.get_table_names())
    if "batting_stats" not in tables:
        logger.warning("%s not created: batting_stats missing", VIEW_NAME)
        return False
    body = view_select_sql(with_chadwick="raw_chadwick_people" in tables)
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.execute(text(f"DROP VIEW IF EXISTS {VIEW_NAME}"))
            conn.execute(text(f"CREATE VIEW {VIEW_NAME} AS {body}"))
        else:
            conn.execute(text(f"CREATE OR REPLACE VIEW {VIEW_NAME} AS {body}"))
    return True
