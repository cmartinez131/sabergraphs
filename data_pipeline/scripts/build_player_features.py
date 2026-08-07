# data_pipeline/scripts/build_player_features.py
import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text

# Run from repo root:
#   python data_pipeline/scripts/build_player_features.py

HOST_DATABASE_URL = os.environ.get("DATABASE_URL")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))

START_YEAR = 2015
END_YEAR   = 2025
ROLL_YEARS = 3
MIN_PA_LAST_SEASON = 150

# core stat columns used as features
FEATURE_STATS = [
    "on_base_plus_slg",  # OPS
    "woba",
    "on_base_percent",
    "slg_percent",
    "batting_avg",
    "isolated_power",
    "k_percent",
    "bb_percent",
    "barrel_batted_rate",
    "sprint_speed",
]

PROFILE_COLS = [
    "bats","throws","primary_position","height_in","weight_lb","current_age"  # from player_profiles
]

def build_player_features():
    engine = create_engine(HOST_DATABASE_URL)

    # batting (2015–2025)
    cols = ["player_id","full_name","year","player_age","plate_appearances"] + FEATURE_STATS
    sql = text("""
        SELECT """ + ",".join(cols) + """
        FROM batting_stats
        WHERE year BETWEEN :y0 AND :y1
    """)
    bat = pd.read_sql(sql, engine, params={"y0": START_YEAR, "y1": END_YEAR})
    for c in FEATURE_STATS + ["player_age","plate_appearances","year"]:
        if c in bat.columns:
            bat[c] = pd.to_numeric(bat[c], errors="coerce")

    # 3-yr trailing means by player/year (including current year)
    bat = bat.sort_values(["player_id","year"])
    def trailing_means(group):
        g = group.copy()
        for s in FEATURE_STATS:
            g[s + "_3yr"] = g[s].rolling(ROLL_YEARS, min_periods=1).mean()
        return g
    bat_roll = bat.groupby("player_id", as_index=False).apply(trailing_means).reset_index(drop=True)

    # filter by PA in last (current) season row to avoid ultra-small samples
    bat_roll = bat_roll[bat_roll["plate_appearances"].fillna(0) >= MIN_PA_LAST_SEASON]

    # latest per player-year row is the row itself; keep compact set
    keep_cols = ["player_id","full_name","year","player_age","plate_appearances"] \
                + [s+"_3yr" for s in FEATURE_STATS] \
                + FEATURE_STATS
    bat_feat = bat_roll[keep_cols].dropna(subset=["player_id","year"]).copy()

    # join basic profile info (one row per player_id)
    prof_sql = text("SELECT * FROM player_profiles")
    prof = pd.read_sql(prof_sql, engine)
    # normalize minimal dtypes
    for c in ["height_in","weight_lb","current_age"]:
        if c in prof.columns:
            prof[c] = pd.to_numeric(prof[c], errors="coerce")
    prof = prof[["player_id","bats","throws","primary_position","height_in","weight_lb","current_age"]]

    df = bat_feat.merge(prof, on="player_id", how="left")

    # simple categorical cleaning
    for c in ["bats","throws","primary_position"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str)

    # final ordering
    df = df.sort_values(["player_id","year"]).reset_index(drop=True)

    # write
    df.to_sql("player_features", engine, if_exists="replace", index=False)
    print(f"> wrote player_features with {len(df)} rows and {df.shape[1]} columns.")

if __name__ == "__main__":
    build_player_features()
