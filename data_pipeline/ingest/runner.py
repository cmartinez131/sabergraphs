# data_pipeline/ingest/runner.py
"""Orchestration: chunk planning -> watermark claim -> fetch -> quality gate ->
transactional upsert+complete. This is the resumable core of the pipeline."""
import logging
import time
from datetime import date

import numpy as np
import pandas as pd

from . import models, sources
from .chunks import chunk_key, date_chunks, season_chunks
from .quality import QualityError, check_chunk
from .upsert import upsert_rows
from .watermarks import (
    mark_completed,
    mark_failed,
    mark_in_progress,
    pending_keys,
    status_summary,
)

logger = logging.getLogger("ingest.runner")

SOURCE_STATCAST = "statcast_pitches"
SOURCE_BAT_TRACKING = "bat_tracking"
SOURCE_CHADWICK = "chadwick"


def _native(v):
    if v is None:
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def frame_to_rows(df: pd.DataFrame, table, context: str = ""):
    """Restrict a fetched frame to the table's landing schema; log drift.

    - Fetched columns not in the manifest are logged (schema drift), not
      silently dropped without a trace.
    - Manifest columns missing from the fetch land as NULL.
    - Pandas NA/NaT and numpy scalars are converted to Python natives.
    """
    manifest = [c.name for c in table.columns]
    drift = [c for c in df.columns if c not in manifest and "deprecated" not in c]
    if drift:
        logger.warning("%s: schema drift — fetched columns not in manifest: %s", context, drift)

    # reindex: keep manifest order, add manifest columns missing from the fetch as NULL
    sub = df[[c for c in manifest if c in df.columns]].reindex(columns=manifest)
    if "game_date" in sub.columns:
        sub["game_date"] = pd.to_datetime(sub["game_date"]).dt.date
    sub = sub.astype(object).where(pd.notna(sub), None)
    return [{k: _native(v) for k, v in rec.items()} for rec in sub.to_dict("records")]


def _process_chunk(engine, source, key, fetch_fn, table, key_cols, quality_cfg, context):
    """One chunk through the full protocol. Returns rows landed. Raises on failure."""
    with engine.begin() as conn:
        attempt = mark_in_progress(conn, models.ingest_watermarks, source, key)
    logger.info("%s: chunk %s (attempt %d)", source, key, attempt)

    try:
        df = fetch_fn()
        rows_fetched = len(df)
        if rows_fetched:
            df, report = check_chunk(
                df, key_cols,
                max_duplicate_key_rate=quality_cfg.max_duplicate_key_rate,
                context=context,
            )
            rows = frame_to_rows(df, table, context=context)
        else:
            logger.info("%s: chunk %s returned 0 rows (off-season window?)", source, key)
            rows = []

        # Data + completion marker in ONE transaction: a chunk is either fully
        # landed and marked completed, or will be redone (safely) on rerun.
        with engine.begin() as conn:
            landed = upsert_rows(conn, table, rows, conflict_cols=list(key_cols))
            mark_completed(conn, models.ingest_watermarks, source, key, landed)
        logger.info("%s: chunk %s completed — %d rows upserted", source, key, landed)
        return landed
    except (QualityError, Exception) as e:
        with engine.begin() as conn:
            mark_failed(conn, models.ingest_watermarks, source, key, repr(e))
        raise


def run_statcast(engine, cfg, start=None, end=None, seasons=None):
    """Backfill pitch-level statcast. Skips completed chunks; retries the rest.

    Returns (completed, failed) chunk-key lists. Never raises on individual
    chunk failure — failures are reported so an overnight run maximizes
    coverage and the rerun mops up.
    """
    sc = cfg.statcast
    if start and end:
        windows = [(s, e) for s, e in date_chunks(start, end, sc.chunk_days)]
    else:
        windows = [(s, e) for _, s, e in season_chunks(
            seasons or sc.seasons, sc.chunk_days, sc.season_start, sc.season_end,
            today=date.today(),
        )]

    all_keys = {chunk_key(s, e): (s, e) for s, e in windows}
    with engine.connect() as conn:
        todo = pending_keys(conn, models.ingest_watermarks, SOURCE_STATCAST, list(all_keys))
    logger.info("statcast: %d chunks total, %d already completed, %d to process",
                len(all_keys), len(all_keys) - len(todo), len(todo))

    completed, failed = [], []
    for i, key in enumerate(todo):
        s, e = all_keys[key]
        try:
            _process_chunk(
                engine, SOURCE_STATCAST, key,
                fetch_fn=lambda s=s, e=e: sources.with_retries(
                    lambda: sources.fetch_statcast(s, e),
                    sc.max_attempts, sc.retry_backoff_seconds, label=f"statcast {key}",
                ),
                table=models.raw_statcast_pitches,
                key_cols=models.STATCAST_NATURAL_KEY,
                quality_cfg=cfg.quality,
                context=f"statcast {key}",
            )
            completed.append(key)
        except Exception as e:  # noqa: BLE001 — chunk isolation is the point
            logger.error("statcast: chunk %s FAILED: %s", key, e)
            failed.append(key)
        if i < len(todo) - 1:
            time.sleep(sc.delay_seconds)  # be polite to Savant
    return completed, failed


def run_bat_tracking(engine, cfg):
    bt = cfg.bat_tracking
    completed, failed = [], []
    for season in bt.seasons:
        key = str(season)
        try:
            _process_chunk(
                engine, SOURCE_BAT_TRACKING, key,
                fetch_fn=lambda season=season: sources.with_retries(
                    lambda: sources.fetch_bat_tracking(season, bt.min_swings),
                    cfg.statcast.max_attempts, cfg.statcast.retry_backoff_seconds,
                    label=f"bat_tracking {season}",
                ),
                table=models.raw_bat_tracking,
                key_cols=("season", "batter_mlbam"),
                quality_cfg=cfg.quality,
                context=f"bat_tracking {season}",
            )
            completed.append(key)
        except Exception as e:  # noqa: BLE001
            logger.error("bat_tracking: season %s FAILED: %s", key, e)
            failed.append(key)
        time.sleep(cfg.statcast.delay_seconds)
    return completed, failed


def run_chadwick(engine, cfg, refresh=False):
    key = "full"
    if not refresh:
        with engine.connect() as conn:
            if not pending_keys(conn, models.ingest_watermarks, SOURCE_CHADWICK, [key]):
                logger.info("chadwick: already loaded (use --refresh to force)")
                return [], []
    try:
        _process_chunk(
            engine, SOURCE_CHADWICK, key,
            fetch_fn=lambda: sources.with_retries(
                sources.fetch_chadwick,
                cfg.statcast.max_attempts, cfg.statcast.retry_backoff_seconds,
                label="chadwick",
            ),
            table=models.raw_chadwick_people,
            key_cols=("key_mlbam",),
            quality_cfg=cfg.quality,
            context="chadwick",
        )
        return [key], []
    except Exception as e:  # noqa: BLE001
        logger.error("chadwick: FAILED: %s", e)
        return [], [key]


def get_status(engine, source=None):
    with engine.connect() as conn:
        return status_summary(conn, models.ingest_watermarks, source)
