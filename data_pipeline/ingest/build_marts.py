# data_pipeline/ingest/build_marts.py
"""Mart refresh: aggregate staging views into the API-facing tables.

Pure INSERT ... SELECT ... ON CONFLICT — rerunning after any backfill
(partial or full) recomputes affected batter-seasons idempotently.

Metric definitions (from stg_pitches, regular season only):
  swings     description in the swing set (incl. foul/bunt variants)
  whiffs     swinging_strike + swinging_strike_blocked
  zone       Savant zone 1-9 (NULL zones count as out-of-zone for chase)
  BBE        description = 'hit_into_play'
  hard hit   launch_speed >= 95 among measured BBE
  barrel     launch_speed_angle = 6 among measured BBE
  fast swing bat_speed >= 75 among measured swings (bat tracking, 2024+)
"""
import logging

from sqlalchemy import text

logger = logging.getLogger("ingest.marts")

_PITCH_SEASON_COLS = (
    "full_name, pitches, swings, whiffs, whiff_rate, zone_rate, chase_rate, "
    "contact_rate, batted_balls, avg_exit_velo, max_exit_velo, hard_hit_rate, "
    "barrel_rate, avg_launch_angle, measured_swings, avg_bat_speed, "
    "avg_swing_length, fast_swing_rate"
)

MART_PITCH_SEASON_SQL = f"""
INSERT INTO mart_batter_pitch_season (
  batter_mlbam, season, {_PITCH_SEASON_COLS}
)
SELECT
  s.batter_mlbam,
  s.season,
  MAX(c.full_name) AS full_name,
  COUNT(*) AS pitches,
  COUNT(*) FILTER (WHERE s.is_swing) AS swings,
  COUNT(*) FILTER (WHERE s.is_whiff) AS whiffs,
  COUNT(*) FILTER (WHERE s.is_whiff)::float
    / NULLIF(COUNT(*) FILTER (WHERE s.is_swing), 0) AS whiff_rate,
  COUNT(*) FILTER (WHERE s.in_zone)::float / NULLIF(COUNT(*), 0) AS zone_rate,
  COUNT(*) FILTER (WHERE s.is_swing AND NOT s.in_zone)::float
    / NULLIF(COUNT(*) FILTER (WHERE NOT s.in_zone), 0) AS chase_rate,
  (COUNT(*) FILTER (WHERE s.is_swing) - COUNT(*) FILTER (WHERE s.is_whiff))::float
    / NULLIF(COUNT(*) FILTER (WHERE s.is_swing), 0) AS contact_rate,
  COUNT(*) FILTER (WHERE s.is_bbe) AS batted_balls,
  AVG(s.launch_speed) FILTER (WHERE s.is_bbe) AS avg_exit_velo,
  MAX(s.launch_speed) FILTER (WHERE s.is_bbe) AS max_exit_velo,
  COUNT(*) FILTER (WHERE s.is_bbe AND s.launch_speed >= 95)::float
    / NULLIF(COUNT(*) FILTER (WHERE s.is_bbe AND s.launch_speed IS NOT NULL), 0) AS hard_hit_rate,
  COUNT(*) FILTER (WHERE s.launch_speed_angle = 6)::float
    / NULLIF(COUNT(*) FILTER (WHERE s.is_bbe AND s.launch_speed_angle IS NOT NULL), 0) AS barrel_rate,
  AVG(s.launch_angle) FILTER (WHERE s.is_bbe) AS avg_launch_angle,
  COUNT(s.bat_speed) AS measured_swings,
  AVG(s.bat_speed) AS avg_bat_speed,
  AVG(s.swing_length) AS avg_swing_length,
  COUNT(*) FILTER (WHERE s.bat_speed >= 75)::float
    / NULLIF(COUNT(s.bat_speed), 0) AS fast_swing_rate
FROM (
  SELECT
    p.*,
    p.description IN ('hit_into_play','foul','swinging_strike','swinging_strike_blocked',
                      'foul_tip','foul_bunt','missed_bunt','bunt_foul_tip') AS is_swing,
    p.description IN ('swinging_strike','swinging_strike_blocked') AS is_whiff,
    COALESCE(p.zone BETWEEN 1 AND 9, false) AS in_zone,
    p.description = 'hit_into_play' AS is_bbe
  FROM stg_pitches p
) s
LEFT JOIN stg_players c ON c.batter_mlbam = s.batter_mlbam
GROUP BY s.batter_mlbam, s.season
ON CONFLICT (batter_mlbam, season) DO UPDATE SET
  {", ".join(f"{c} = EXCLUDED.{c}" for c in _PITCH_SEASON_COLS.replace(" ", "").split(","))}
"""

_BT_COLS = (
    "full_name, competitive_swings, avg_bat_speed, fast_swing_rate, "
    "avg_swing_length, squared_up_rate, blast_rate, swords, whiff_rate, "
    "contact, whiffs, batted_ball_events, batter_run_value"
)

MART_BAT_TRACKING_SQL = f"""
INSERT INTO mart_bat_tracking_season (
  batter_mlbam, season, {_BT_COLS}
)
SELECT
  b.batter_mlbam,
  b.season,
  COALESCE(c.full_name, b.name) AS full_name,
  b.swings_competitive,
  b.avg_bat_speed,
  b.hard_swing_rate,       -- Savant's "hard swing rate" = share of swings >= 75mph
  b.swing_length,
  b.squared_up_per_swing,
  b.blast_per_swing,
  b.swords,
  b.whiff_per_swing,
  b.contact,
  b.whiffs,
  b.batted_ball_events,
  b.batter_run_value
FROM stg_bat_tracking b
LEFT JOIN stg_players c ON c.batter_mlbam = b.batter_mlbam
ON CONFLICT (batter_mlbam, season) DO UPDATE SET
  {", ".join(f"{c} = EXCLUDED.{c}" for c in _BT_COLS.replace(" ", "").split(","))}
"""


def build_marts(engine):
    with engine.begin() as conn:
        conn.execute(text(MART_PITCH_SEASON_SQL))
        conn.execute(text(MART_BAT_TRACKING_SQL))
    with engine.connect() as conn:
        counts = {
            t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()  # noqa: S608 — fixed identifiers
            for t in ("mart_batter_pitch_season", "mart_bat_tracking_season")
        }
    for t, n in counts.items():
        logger.info("mart refreshed: %s = %d rows", t, n)
    return counts
