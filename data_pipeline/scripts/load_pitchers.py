# data_pipeline/scripts/load_pitchers.py
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.types import Integer, String
import os
import sys

# Connect from HOST machine (your Mac) — same pattern as your batter loader
HOST_DATABASE_URL = os.environ.get("DATABASE_URL")


# Allow importing backend models
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
from app.db.models import PitchingStats  # noqa: E402 — needs the sys.path line above

# New CSV path (2015–2025 pitchers)
CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', '2015_2025_pitchers.csv')

def load_data():
    try:
        print(f"Connecting to DB: {HOST_DATABASE_URL}")
        engine = create_engine(HOST_DATABASE_URL)
        engine.connect()
        print("Connection successful!")
    except Exception as e:
        print(f"Error connecting to the database: {e}")
        print("Please ensure the PostgreSQL container is running ('docker compose up -d db') "
              "and that your local port/creds match HOST_DATABASE_URL.")
        return

    print(f"Reading data from {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH)

    # Build full_name from "last_name, first_name" if present
    if "last_name, first_name" in df.columns:
        df[['last_name', 'first_name']] = df['last_name, first_name'].str.split(', ', expand=True, n=1)
        df['full_name'] = df['first_name'].fillna('') + ' ' + df['last_name'].fillna('')
        df.drop(columns=['last_name, first_name', 'last_name', 'first_name'], inplace=True, errors="ignore")

    # Standardize a few common pitcher column names (nonexistent keys are ignored)
    rename_map = {
        "ip": "innings_pitched",
        "k%": "k_percent",
        "bb%": "bb_percent",
    }
    df = df.rename(columns=rename_map)

    # Ensure required columns exist
    for needed in ["player_id", "year", "full_name"]:
        if needed not in df.columns:
            raise RuntimeError(f"CSV is missing required column: {needed}")

    # Coerce everything except known string cols to numeric where possible
    string_like = {"full_name"}
    for c in df.columns:
        if c not in string_like:
            df[c] = pd.to_numeric(df[c], errors="ignore")

    # Strongly type a few key columns (others inferred)
    dtype_map = {
        "player_id": Integer(),
        "year": Integer(),
        "full_name": String(128),
        # Examples if present in your CSV; safe to omit if unknown
        # "innings_pitched": Float(),
        # "era": Float(),
        # "fip": Float(),
        # "k_percent": Float(),
        # "bb_percent": Float(),
        # "saves": Integer(),
    }

    print(f"Loading {len(df)} records (replacing table '{PitchingStats.__tablename__}')...")
    df.to_sql(
        PitchingStats.__tablename__,
        engine,
        if_exists='replace',    # rebuilds table with ALL CSV columns
        index=False,
        dtype=dtype_map
    )

    print("Data loading complete!")

if __name__ == "__main__":
    load_data()
