# data_pipeline/ingest/chunks.py
"""Date-window chunking for the statcast backfill. Pure functions; unit-tested."""
from datetime import date, timedelta


def season_window(season: int, season_start: str = "02-20", season_end: str = "11-10"):
    """Inclusive (start, end) dates for one season's fetch window."""
    sm, sd = (int(p) for p in season_start.split("-"))
    em, ed = (int(p) for p in season_end.split("-"))
    return date(season, sm, sd), date(season, em, ed)


def date_chunks(start: date, end: date, chunk_days: int = 7):
    """Split [start, end] (inclusive) into consecutive windows of chunk_days.

    Windows are non-overlapping and cover every day exactly once; the last
    window is shorter when the range doesn't divide evenly.
    """
    if end < start:
        raise ValueError(f"end {end} before start {start}")
    if chunk_days < 1:
        raise ValueError("chunk_days must be >= 1")
    out = []
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=chunk_days - 1), end)
        out.append((cur, stop))
        cur = stop + timedelta(days=1)
    return out


def chunk_key(start: date, end: date) -> str:
    return f"{start.isoformat()}..{end.isoformat()}"


def season_chunks(seasons, chunk_days=7, season_start="02-20", season_end="11-10", today=None):
    """All (season, start, end) chunks for the configured seasons, oldest first.

    Windows that lie entirely in the future (relative to `today`) are skipped;
    a window straddling `today` is clamped so reruns can extend it later.
    """
    out = []
    for season in sorted(seasons):
        w_start, w_end = season_window(season, season_start, season_end)
        if today is not None:
            if w_start > today:
                continue
            w_end = min(w_end, today)
        for c_start, c_end in date_chunks(w_start, w_end, chunk_days):
            out.append((season, c_start, c_end))
    return out
