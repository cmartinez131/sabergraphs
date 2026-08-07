# data_pipeline/ingest/quality.py
"""Per-chunk data-quality gates. Fail loudly: a QualityError marks the chunk
failed and is reported at the end of the run — never silently skipped."""
import logging

logger = logging.getLogger("ingest.quality")


class QualityError(Exception):
    """A chunk violated a hard data-quality gate."""


def check_chunk(df, key_cols, max_duplicate_key_rate=0.005, context=""):
    """Validate a fetched frame against the natural key.

    Returns (clean_df, report). Raises QualityError on:
      - a natural-key column missing from the frame
      - any NULL in a natural-key column
      - in-frame duplicate natural keys above max_duplicate_key_rate
    Small duplicate counts are dropped (keeping the last occurrence) and logged.
    """
    report = {"context": context, "rows_in": int(len(df))}

    missing = [c for c in key_cols if c not in df.columns]
    if missing:
        raise QualityError(f"{context}: key columns missing from fetch: {missing}")

    if len(df) == 0:
        report.update(rows_out=0, dupes_dropped=0)
        return df, report

    null_keys = int(df[list(key_cols)].isna().any(axis=1).sum())
    if null_keys:
        raise QualityError(f"{context}: {null_keys} rows with NULL natural-key values")

    dup_mask = df.duplicated(subset=list(key_cols), keep="last")
    dupes = int(dup_mask.sum())
    dup_rate = dupes / len(df)
    if dup_rate > max_duplicate_key_rate:
        raise QualityError(
            f"{context}: duplicate-key rate {dup_rate:.4f} exceeds {max_duplicate_key_rate}"
            f" ({dupes}/{len(df)} rows)"
        )
    if dupes:
        logger.warning("%s: dropping %d in-frame duplicate key rows (keeping last)", context, dupes)
        df = df[~dup_mask]

    report.update(rows_out=int(len(df)), dupes_dropped=dupes)
    return df, report
