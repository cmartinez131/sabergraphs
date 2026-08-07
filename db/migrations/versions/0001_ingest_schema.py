"""ingestion schema: raw tables, staging views, marts, watermarks

Revision ID: 0001_ingest_schema
Revises:
Create Date: 2026-08-06

Creates the pitch-level ingestion schema:
  raw_statcast_pitches / raw_bat_tracking / raw_chadwick_people  (landed as-is)
  stg_pitches / stg_bat_tracking / stg_players                   (typed views)
  mart_batter_pitch_season / mart_bat_tracking_season            (API-facing)
  ingest_watermarks                                              (resume bookkeeping)

The statcast column list is a frozen snapshot of the Savant CSV schema at
authoring time (deprecated columns dropped) — the same manifest as
data_pipeline/ingest/models.py. New upstream columns are a new migration.
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_ingest_schema"
down_revision = None
branch_labels = None
depends_on = None

_TYPES = {"bigint": sa.BigInteger, "float": sa.Float, "text": sa.Text, "date": sa.Date}
STATCAST_NATURAL_KEY = ("game_pk", "at_bat_number", "pitch_number")

STATCAST_COLUMNS = [
    ("pitch_type", "text"),
    ("game_date", "date"),
    ("release_speed", "float"),
    ("release_pos_x", "float"),
    ("release_pos_z", "float"),
    ("player_name", "text"),
    ("batter", "bigint"),
    ("pitcher", "bigint"),
    ("events", "text"),
    ("description", "text"),
    ("spin_dir", "bigint"),
    ("zone", "bigint"),
    ("des", "text"),
    ("game_type", "text"),
    ("stand", "text"),
    ("p_throws", "text"),
    ("home_team", "text"),
    ("away_team", "text"),
    ("type", "text"),
    ("hit_location", "bigint"),
    ("bb_type", "text"),
    ("balls", "bigint"),
    ("strikes", "bigint"),
    ("game_year", "bigint"),
    ("pfx_x", "float"),
    ("pfx_z", "float"),
    ("plate_x", "float"),
    ("plate_z", "float"),
    ("on_3b", "bigint"),
    ("on_2b", "bigint"),
    ("on_1b", "bigint"),
    ("outs_when_up", "bigint"),
    ("inning", "bigint"),
    ("inning_topbot", "text"),
    ("hc_x", "float"),
    ("hc_y", "float"),
    ("umpire", "bigint"),
    ("sv_id", "bigint"),
    ("vx0", "float"),
    ("vy0", "float"),
    ("vz0", "float"),
    ("ax", "float"),
    ("ay", "float"),
    ("az", "float"),
    ("sz_top", "float"),
    ("sz_bot", "float"),
    ("hit_distance_sc", "bigint"),
    ("launch_speed", "float"),
    ("launch_angle", "bigint"),
    ("effective_speed", "float"),
    ("release_spin_rate", "bigint"),
    ("release_extension", "float"),
    ("game_pk", "bigint"),
    ("fielder_2", "bigint"),
    ("fielder_3", "bigint"),
    ("fielder_4", "bigint"),
    ("fielder_5", "bigint"),
    ("fielder_6", "bigint"),
    ("fielder_7", "bigint"),
    ("fielder_8", "bigint"),
    ("fielder_9", "bigint"),
    ("release_pos_y", "float"),
    ("estimated_ba_using_speedangle", "float"),
    ("estimated_woba_using_speedangle", "float"),
    ("woba_value", "float"),
    ("woba_denom", "bigint"),
    ("babip_value", "bigint"),
    ("iso_value", "bigint"),
    ("launch_speed_angle", "bigint"),
    ("at_bat_number", "bigint"),
    ("pitch_number", "bigint"),
    ("pitch_name", "text"),
    ("home_score", "bigint"),
    ("away_score", "bigint"),
    ("bat_score", "bigint"),
    ("fld_score", "bigint"),
    ("post_away_score", "bigint"),
    ("post_home_score", "bigint"),
    ("post_bat_score", "bigint"),
    ("post_fld_score", "bigint"),
    ("if_fielding_alignment", "text"),
    ("of_fielding_alignment", "text"),
    ("spin_axis", "bigint"),
    ("delta_home_win_exp", "float"),
    ("delta_run_exp", "float"),
    ("bat_speed", "float"),
    ("swing_length", "float"),
    ("miss_distance", "float"),
    ("estimated_slg_using_speedangle", "float"),
    ("delta_pitcher_run_exp", "float"),
    ("hyper_speed", "float"),
    ("home_score_diff", "bigint"),
    ("bat_score_diff", "bigint"),
    ("home_win_exp", "float"),
    ("bat_win_exp", "float"),
    ("age_pit_legacy", "bigint"),
    ("age_bat_legacy", "bigint"),
    ("age_pit", "bigint"),
    ("age_bat", "bigint"),
    ("n_thruorder_pitcher", "bigint"),
    ("n_priorpa_thisgame_player_at_bat", "bigint"),
    ("pitcher_days_since_prev_game", "bigint"),
    ("batter_days_since_prev_game", "bigint"),
    ("pitcher_days_until_next_game", "bigint"),
    ("batter_days_until_next_game", "bigint"),
    ("api_break_z_with_gravity", "float"),
    ("api_break_x_arm", "float"),
    ("api_break_x_batter_in", "float"),
    ("arm_angle", "float"),
    ("attack_angle", "float"),
    ("attack_direction", "float"),
    ("swing_path_tilt", "float"),
    ("intercept_ball_minus_batter_pos_x_inches", "float"),
    ("intercept_ball_minus_batter_pos_y_inches", "float"),
]


STG_PITCHES_VIEW = """
CREATE OR REPLACE VIEW stg_pitches AS
SELECT
  game_pk, at_bat_number, pitch_number,
  game_date,
  EXTRACT(YEAR FROM game_date)::int AS season,
  batter  AS batter_mlbam,
  pitcher AS pitcher_mlbam,
  stand, p_throws, home_team, away_team,
  inning, balls, strikes, outs_when_up,
  pitch_type, description, events, type,
  zone, plate_x, plate_z,
  launch_speed, launch_angle, launch_speed_angle,
  estimated_woba_using_speedangle, woba_value,
  bat_speed, swing_length,
  delta_run_exp
FROM raw_statcast_pitches
WHERE game_type = 'R'
"""

STG_BAT_TRACKING_VIEW = """
CREATE OR REPLACE VIEW stg_bat_tracking AS
SELECT season, batter_mlbam, name, swings_competitive, percent_swings_competitive,
       contact, avg_bat_speed, hard_swing_rate, squared_up_per_bat_contact,
       squared_up_per_swing, blast_per_bat_contact, blast_per_swing, swing_length,
       swords, batter_run_value, whiffs, whiff_per_swing, batted_ball_events,
       batted_ball_event_per_swing
FROM raw_bat_tracking
"""

STG_PLAYERS_VIEW = """
CREATE OR REPLACE VIEW stg_players AS
SELECT key_mlbam AS batter_mlbam,
       name_first || ' ' || name_last AS full_name,
       key_fangraphs, key_bbref, key_retro,
       mlb_played_first::int AS mlb_played_first,
       mlb_played_last::int  AS mlb_played_last
FROM raw_chadwick_people
"""


def upgrade() -> None:
    op.create_table(
        "raw_statcast_pitches",
        *[
            sa.Column(
                name,
                _TYPES[sql_type](),
                primary_key=name in STATCAST_NATURAL_KEY,
                nullable=name not in STATCAST_NATURAL_KEY,
            )
            for name, sql_type in STATCAST_COLUMNS
        ],
    )
    op.create_index("ix_raw_statcast_batter_date", "raw_statcast_pitches", ["batter", "game_date"])
    op.create_index("ix_raw_statcast_game_date", "raw_statcast_pitches", ["game_date"])

    op.create_table(
        "raw_bat_tracking",
        sa.Column("season", sa.Integer, primary_key=True),
        sa.Column("batter_mlbam", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.Text),
        sa.Column("swings_competitive", sa.BigInteger),
        sa.Column("percent_swings_competitive", sa.Float),
        sa.Column("contact", sa.BigInteger),
        sa.Column("avg_bat_speed", sa.Float),
        sa.Column("hard_swing_rate", sa.Float),
        sa.Column("squared_up_per_bat_contact", sa.Float),
        sa.Column("squared_up_per_swing", sa.Float),
        sa.Column("blast_per_bat_contact", sa.Float),
        sa.Column("blast_per_swing", sa.Float),
        sa.Column("swing_length", sa.Float),
        sa.Column("swords", sa.BigInteger),
        sa.Column("batter_run_value", sa.Float),
        sa.Column("whiffs", sa.BigInteger),
        sa.Column("whiff_per_swing", sa.Float),
        sa.Column("batted_ball_events", sa.BigInteger),
        sa.Column("batted_ball_event_per_swing", sa.Float),
    )

    op.create_table(
        "raw_chadwick_people",
        sa.Column("key_mlbam", sa.BigInteger, primary_key=True),
        sa.Column("name_first", sa.Text),
        sa.Column("name_last", sa.Text),
        sa.Column("key_retro", sa.Text),
        sa.Column("key_bbref", sa.Text),
        sa.Column("key_fangraphs", sa.BigInteger),
        sa.Column("mlb_played_first", sa.Float),
        sa.Column("mlb_played_last", sa.Float),
    )

    op.create_table(
        "ingest_watermarks",
        sa.Column("source", sa.Text, primary_key=True),
        sa.Column("chunk_key", sa.Text, primary_key=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("attempt", sa.Integer),
        sa.Column("row_count", sa.BigInteger),
        sa.Column("error", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "mart_batter_pitch_season",
        sa.Column("batter_mlbam", sa.BigInteger, primary_key=True),
        sa.Column("season", sa.Integer, primary_key=True),
        sa.Column("full_name", sa.Text),
        sa.Column("pitches", sa.BigInteger),
        sa.Column("swings", sa.BigInteger),
        sa.Column("whiffs", sa.BigInteger),
        sa.Column("whiff_rate", sa.Float),
        sa.Column("zone_rate", sa.Float),
        sa.Column("chase_rate", sa.Float),
        sa.Column("contact_rate", sa.Float),
        sa.Column("batted_balls", sa.BigInteger),
        sa.Column("avg_exit_velo", sa.Float),
        sa.Column("max_exit_velo", sa.Float),
        sa.Column("hard_hit_rate", sa.Float),
        sa.Column("barrel_rate", sa.Float),
        sa.Column("avg_launch_angle", sa.Float),
        sa.Column("measured_swings", sa.BigInteger),
        sa.Column("avg_bat_speed", sa.Float),
        sa.Column("avg_swing_length", sa.Float),
        sa.Column("fast_swing_rate", sa.Float),
    )

    op.create_table(
        "mart_bat_tracking_season",
        sa.Column("batter_mlbam", sa.BigInteger, primary_key=True),
        sa.Column("season", sa.Integer, primary_key=True),
        sa.Column("full_name", sa.Text),
        sa.Column("competitive_swings", sa.BigInteger),
        sa.Column("avg_bat_speed", sa.Float),
        sa.Column("fast_swing_rate", sa.Float),
        sa.Column("avg_swing_length", sa.Float),
        sa.Column("squared_up_rate", sa.Float),
        sa.Column("blast_rate", sa.Float),
        sa.Column("swords", sa.BigInteger),
        sa.Column("whiff_rate", sa.Float),
        sa.Column("contact", sa.BigInteger),
        sa.Column("whiffs", sa.BigInteger),
        sa.Column("batted_ball_events", sa.BigInteger),
        sa.Column("batter_run_value", sa.Float),
    )

    op.execute(STG_PITCHES_VIEW)
    op.execute(STG_BAT_TRACKING_VIEW)
    op.execute(STG_PLAYERS_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS stg_players")
    op.execute("DROP VIEW IF EXISTS stg_bat_tracking")
    op.execute("DROP VIEW IF EXISTS stg_pitches")
    op.drop_table("mart_bat_tracking_season")
    op.drop_table("mart_batter_pitch_season")
    op.drop_table("ingest_watermarks")
    op.drop_table("raw_chadwick_people")
    op.drop_table("raw_bat_tracking")
    op.drop_index("ix_raw_statcast_game_date", table_name="raw_statcast_pitches")
    op.drop_index("ix_raw_statcast_batter_date", table_name="raw_statcast_pitches")
    op.drop_table("raw_statcast_pitches")
