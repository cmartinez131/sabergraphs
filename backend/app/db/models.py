# backend/app/db/models.py
from sqlalchemy import BigInteger, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base

from .database import Base

# The mart tables are created and migrated by the data pipeline's Alembic
# (data_pipeline/), NOT by the backend. They live on their own declarative
# base so init_history_tables()'s Base.metadata.create_all can never
# pre-create empty mart tables and collide with the pipeline migrations.
MartBase = declarative_base()

class BattingStats(Base):
    __tablename__ = 'batting_stats'

    # Composite primary key so SQLAlchemy is happy.
    # (The physical Postgres table created by pandas.to_sql won't enforce this,
    #  but SQLAlchemy still needs it to uniquely identify rows.)
    player_id = Column(Integer, primary_key=True, index=True)
    year      = Column(Integer, primary_key=True, index=True)

    # Helpful for display and joins/filters
    full_name = Column(String, index=True)

    # Common fields we reference often (others are accessed dynamically)
    plate_appearances  = Column(Integer)

    player_age         = Column(Integer)
    home_run           = Column(Integer)
    batting_avg        = Column(Float)
    woba               = Column(Float)
    barrel_batted_rate = Column(Float)
    sprint_speed       = Column(Float)


class MartBatTrackingSeason(MartBase):
    """Season-grain Statcast bat-tracking leaderboard (2024+), produced by
    data_pipeline/ingest/build_marts.py. Owned by Alembic — this mapping is
    read-only from the API's perspective."""
    __tablename__ = 'mart_bat_tracking_season'

    batter_mlbam = Column(BigInteger, primary_key=True)  # same id space as batting_stats.player_id
    season       = Column(Integer, primary_key=True)

    full_name          = Column(String)
    competitive_swings = Column(BigInteger)
    avg_bat_speed      = Column(Float)
    fast_swing_rate    = Column(Float)
    avg_swing_length   = Column(Float)
    squared_up_rate    = Column(Float)
    blast_rate         = Column(Float)
    swords             = Column(BigInteger)
    whiff_rate         = Column(Float)
    contact            = Column(BigInteger)
    whiffs             = Column(BigInteger)
    batted_ball_events = Column(BigInteger)
    batter_run_value   = Column(Float)


class MartBatterPitchSeason(MartBase):
    """Season-grain aggregates over raw pitch data (2021+), produced by
    data_pipeline/ingest/build_marts.py. Owned by Alembic."""
    __tablename__ = 'mart_batter_pitch_season'

    batter_mlbam = Column(BigInteger, primary_key=True)
    season       = Column(Integer, primary_key=True)

    full_name        = Column(String)
    pitches          = Column(BigInteger)
    swings           = Column(BigInteger)
    whiffs           = Column(BigInteger)
    whiff_rate       = Column(Float)
    zone_rate        = Column(Float)
    chase_rate       = Column(Float)
    contact_rate     = Column(Float)
    batted_balls     = Column(BigInteger)
    avg_exit_velo    = Column(Float)
    max_exit_velo    = Column(Float)
    hard_hit_rate    = Column(Float)
    barrel_rate      = Column(Float)
    avg_launch_angle = Column(Float)
    measured_swings  = Column(BigInteger)
    avg_bat_speed    = Column(Float)
    avg_swing_length = Column(Float)
    fast_swing_rate  = Column(Float)


class PitchingStats(Base):
    __tablename__ = 'pitching_stats'

    # Composite primary key for uniqueness across seasons
    player_id = Column(Integer, primary_key=True, index=True)
    year      = Column(Integer, primary_key=True, index=True)

    full_name       = Column(String, index=True)

    # Common pitcher fields (present only if your CSV has them; table will still
    # include any other CSV columns via pandas.to_sql)
    innings_pitched = Column(Float)
    era             = Column(Float)
    fip             = Column(Float)
    k_percent       = Column(Float)
    bb_percent      = Column(Float)
    saves           = Column(Integer)