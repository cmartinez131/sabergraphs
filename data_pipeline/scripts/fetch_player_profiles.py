# data_pipeline/scripts/fetch_player_profiles.py
import os
import sys
import time
import json

import requests
import pandas as pd
from sqlalchemy import create_engine, text

# --------------------------------------
# DB connection (match load_csv.py)
# --------------------------------------

# Run from root with: 
# python data_pipeline/scripts/fetch_player_profiles.py

"""
This will:
    - read distinct player_id values from batting_stats where year ∈ [2015, 2025]
    - fetch MLB profiles
    - write player_profiles and player_seasons tables
    - save data_pipeline/data/player_profiles.csv
"""

HOST_DATABASE_URL = os.environ.get("DATABASE_URL")

# (Optional) allow importing backend later if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))

# --------------------------------------
# Config
# --------------------------------------
START_YEAR = 2015
END_YEAR = 2025
SLEEP_MS = 60  # polite delay per API call

BASE_URL = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "sabermetric-ai/1.0 (+https://example.com)"}


def get_json(url, params=None, timeout=20):
    r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()


def parse_height_to_inches(h):
    """Convert strings like 6' 2\" to inches."""
    if not h or not isinstance(h, str):
        return None
    s = h.replace(" ", "").replace('"', "")
    if "'" in s:
        try:
            ft, rest = s.split("'", 1)
            ft = int(ft.strip())
            ins = "".join(ch for ch in rest if ch.isdigit())
            ins = int(ins) if ins else 0
            return 12 * ft + ins
        except Exception:
            return None
    return None


def extract_player_profile(person_obj):
    def g(obj, *keys, default=None):
        cur = obj
        for k in keys:
            if cur is None or not isinstance(cur, dict):
                return default
            cur = cur.get(k)
        return cur if cur is not None else default

    pid = g(person_obj, "id")
    full_name = g(person_obj, "fullName")
    birth_date = g(person_obj, "birthDate")
    age = g(person_obj, "currentAge")
    height_str = g(person_obj, "height")
    height_in = parse_height_to_inches(height_str)
    weight_lb = g(person_obj, "weight")
    mlb_debut = g(person_obj, "mlbDebutDate")
    active = bool(g(person_obj, "active", default=False))

    bats = g(person_obj, "batSide", "code") or g(person_obj, "batSide", "description")
    throws = g(person_obj, "pitchHand", "code") or g(person_obj, "pitchHand", "description")

    pos_abbr = g(person_obj, "primaryPosition", "abbreviation") or g(person_obj, "primaryPosition", "code")
    pos_name = g(person_obj, "primaryPosition", "name")

    return {
        "player_id": int(pid) if pid is not None else None,
        "full_name": full_name,
        "birth_date": birth_date,
        "current_age": int(age) if isinstance(age, (int, float)) else None,
        "height_in": int(height_in) if height_in is not None else None,
        "weight_lb": int(weight_lb) if isinstance(weight_lb, (int, float)) else None,
        "mlb_debut": mlb_debut,
        "bats": str(bats).upper()[:1] if isinstance(bats, str) else None,      # R/L/S
        "throws": str(throws).upper()[:1] if isinstance(throws, str) else None, # R/L
        "primary_position": pos_abbr or pos_name,
        "primary_position_name": pos_name,
        "is_active": active,
        "raw_height": height_str,
    }


def fetch_player_profile(player_id):
    try:
        data = get_json(f"{BASE_URL}/people/{player_id}")
        people = data.get("people") or []
        if not people:
            return None
        return extract_player_profile(people[0])
    except Exception as e:
        print(f"      ✗ profile failed for {player_id}: {e}")
        return None


def distinct_player_ids_from_batting(engine, y0, y1):
    sql = text(
        """
        SELECT DISTINCT player_id
        FROM batting_stats
        WHERE year BETWEEN :y0 AND :y1
          AND player_id IS NOT NULL
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"y0": int(y0), "y1": int(y1)}).fetchall()
    return [int(r[0]) for r in rows if r and r[0] is not None]


def build_player_profiles(engine, player_ids, sleep_ms=SLEEP_MS):
    rows = []
    total = len(player_ids)
    start_ts = time.time()
    for i, pid in enumerate(player_ids, start=1):
        print(f"    → fetching {i}/{total}: player_id={pid}")
        prof = fetch_player_profile(pid)
        if prof and prof.get("player_id") is not None:
            rows.append(prof)

        if sleep_ms and sleep_ms > 0:
            time.sleep(float(sleep_ms) / 1000.0)

        if i % 200 == 0 or i == total:
            elapsed = time.time() - start_ts
            print(f"      • fetched {i}/{total} in {elapsed:0.1f}s")

    if not rows:
        raise RuntimeError("No player profiles fetched.")
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["player_id"], keep="first")
    df = df.sort_values(["full_name", "player_id"]).reset_index(drop=True)
    return df


def write_profiles_csv(df):
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    out_dir = os.path.abspath(out_dir)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "player_profiles.csv")
    df.to_csv(out_path, index=False)
    print(f"> wrote CSV: {out_path}")


def write_profiles_to_db(engine, df):
    print(f"> writing {len(df)} profiles to table 'player_profiles'…")
    df.to_sql("player_profiles", engine, if_exists="replace", index=False)
    print("> player_profiles table written.")


def build_player_seasons_table(engine, y0, y1):
    print("> building player_seasons from batting_stats…")
    sql = text(
        """
        SELECT DISTINCT
            player_id,
            full_name,
            year,
            player_age
        FROM batting_stats
        WHERE year BETWEEN :y0 AND :y1
        ORDER BY player_id, year
        """
    )
    df = pd.read_sql(sql, engine, params={"y0": int(y0), "y1": int(y1)})
    df.to_sql("player_seasons", engine, if_exists="replace", index=False)
    print(f"> player_seasons written with {len(df)} rows.")


def main():
    print(f"Connecting to DB: {HOST_DATABASE_URL}")
    try:
        engine = create_engine(HOST_DATABASE_URL)
        with engine.connect() as _:
            pass
        print("Connection successful!")
    except Exception as e:
        print(f"Error connecting to the database: {e}")
        print("Please ensure Postgres is running (e.g., 'docker compose up -d db') and credentials are correct.")
        return

    print(f"> collecting distinct player_ids from batting_stats for {START_YEAR}–{END_YEAR}…")
    pids = distinct_player_ids_from_batting(engine, START_YEAR, END_YEAR)
    if not pids:
        print("No player_ids found in batting_stats for the requested window.")
        return
    print(f"  found {len(pids)} players.")

    profiles_df = build_player_profiles(engine, pids, sleep_ms=SLEEP_MS)
    write_profiles_csv(profiles_df)
    write_profiles_to_db(engine, profiles_df)

    build_player_seasons_table(engine, START_YEAR, END_YEAR)

    meta = {"columns": list(profiles_df.columns), "count": int(len(profiles_df))}
    meta_path = os.path.join(os.path.dirname(__file__), "..", "data", "player_profiles_meta.json")
    meta_path = os.path.abspath(meta_path)
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"> wrote meta: {meta_path}")

    print("All done.")


if __name__ == "__main__":
    main()
