# backend/app/db/models.py
from sqlalchemy import Column, Integer, String, Float
from .database import Base

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