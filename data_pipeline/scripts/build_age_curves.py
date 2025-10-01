# data_pipeline/scripts/build_age_curves.py
import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text

# Run from repo root:
#   python data_pipeline/scripts/build_age_curves.py

HOST_DATABASE_URL = os.environ.get("DATABASE_URL")

# Optional: import backend if you need helpers later
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))

START_YEAR = 2015
END_YEAR   = 2025
MIN_PA     = 200

# Stats we’ll support out of the box (add more as needed)
STATS = [
    "on_base_plus_slg",  # OPS
    "woba",
    "on_base_percent",
    "slg_percent",
    "batting_avg",
    "isolated_power",
    "home_run",
    "k_percent",
    "bb_percent",
    "barrel_batted_rate",
    "sprint_speed",
]

def build_age_curves():
    engine = create_engine(HOST_DATABASE_URL)

    # Pull only what we need
    cols = ["player_id","year","player_age","plate_appearances"] + STATS
    sql = text("""
        SELECT """ + ",".join(cols) + """
        FROM batting_stats
        WHERE year BETWEEN :y0 AND :y1
    """)
    df = pd.read_sql(sql, engine, params={"y0": START_YEAR, "y1": END_YEAR})

    # Ensure numerics
    for c in STATS + ["player_age","plate_appearances","year"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Filter by PA
    df = df[df["plate_appearances"].fillna(0) >= MIN_PA]
    df = df[df["player_age"].notna()]

    rows = []
    for stat in STATS:
        if stat not in df.columns:
            continue
        d = df[["player_age", stat]].dropna()
        if d.empty:
            continue
        g = d.groupby("player_age")[stat]
        tmp = g.agg(["mean","std","count"]).reset_index()
        tmp["stat"] = stat
        tmp["year_start"] = START_YEAR
        tmp["year_end"] = END_YEAR
        tmp["min_pa"] = MIN_PA
        rows.append(tmp)

    if not rows:
        raise RuntimeError("No curves computed; check columns and filters.")

    out = pd.concat(rows, axis=0, ignore_index=True)
    out = out.rename(columns={"player_age":"age","mean":"league_mean","std":"league_std","count":"n"})
    out = out[["stat","age","league_mean","league_std","n","year_start","year_end","min_pa"]]
    out.to_sql("league_age_curves", engine, if_exists="replace", index=False)
    print(f"> wrote league_age_curves with {len(out)} rows.")

if __name__ == "__main__":
    build_age_curves()
