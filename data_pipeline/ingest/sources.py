# data_pipeline/ingest/sources.py
"""Fetchers for the three upstream sources.

pybaseball is imported lazily so the unit-test/CI environment (which tests
chunking, watermarks, upserts and quality gates only) does not need it.

Bat-tracking note: the released pybaseball (2.2.7) does not yet expose the
bat-tracking leaderboard, so we hit Savant's stable CSV endpoint directly —
the same data `statcast_batter_bat_tracking` wraps on master.
"""
import io
import logging
import time

import pandas as pd

logger = logging.getLogger("ingest.sources")

BAT_TRACKING_URL = (
    "https://baseballsavant.mlb.com/leaderboard/bat-tracking"
    "?type=batter&minSwings={min_swings}&seasonStart={season}&seasonEnd={season}&csv=true"
)


def fetch_statcast(start, end) -> pd.DataFrame:
    """Pitch-level statcast for [start, end] inclusive dates."""
    from pybaseball import cache, statcast

    cache.enable()  # disk cache makes post-crash refetches near-instant
    df = statcast(start_dt=start.isoformat(), end_dt=end.isoformat(), verbose=False)
    return df if df is not None else pd.DataFrame()


def fetch_bat_tracking(season: int, min_swings: int = 1) -> pd.DataFrame:
    import requests

    url = BAT_TRACKING_URL.format(season=season, min_swings=min_swings)
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df = df.rename(columns={"id": "batter_mlbam"})
    df["season"] = int(season)
    return df


def fetch_chadwick() -> pd.DataFrame:
    """Chadwick register rows that carry a real MLBAM id (the crosswalk we need).

    pybaseball encodes "no MLBAM id" as the sentinel -1 (mostly historical
    umpires/officials with only Retrosheet ids), so filter to positive ids.
    """
    from pybaseball import cache, chadwick_register

    cache.enable()
    df = chadwick_register()
    return df[df["key_mlbam"].notna() & (df["key_mlbam"] > 0)].copy()


def with_retries(fn, max_attempts=3, backoffs=(10, 30), label=""):
    """Run fn(); on failure sleep through backoffs and retry. Raises the last error."""
    last = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — deliberately broad: network layer
            last = e
            if attempt == max_attempts:
                break
            delay = backoffs[min(attempt - 1, len(backoffs) - 1)]
            logger.warning("%s attempt %d/%d failed (%s); retrying in %ss",
                           label, attempt, max_attempts, e, delay)
            time.sleep(delay)
    raise last
