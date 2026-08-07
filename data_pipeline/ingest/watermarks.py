# data_pipeline/ingest/watermarks.py
"""Chunk-progress bookkeeping for resumable backfills.

Protocol per chunk:
  1. mark_in_progress() in its own transaction — a crash leaves visible evidence
     of where the run died.
  2. Fetch + quality-check the chunk.
  3. Upsert the rows AND mark_completed() in the SAME transaction — the
     completion marker is atomic with the data, so a chunk is either fully
     loaded and marked, or will be redone on rerun (upserts make redo safe).

pending: not yet attempted / crashed (in_progress) / failed — everything
except completed. Reruns process exactly those.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from .upsert import upsert_rows

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def _now():
    return datetime.now(timezone.utc)


def get_watermark(conn, table, source: str, chunk_key: str):
    row = conn.execute(
        select(table).where(table.c.source == source, table.c.chunk_key == chunk_key)
    ).mappings().first()
    return dict(row) if row else None


def completed_keys(conn, table, source: str) -> set[str]:
    rows = conn.execute(
        select(table.c.chunk_key).where(
            table.c.source == source, table.c.status == STATUS_COMPLETED
        )
    ).scalars()
    return set(rows)


def pending_keys(conn, table, source: str, all_keys: list[str]) -> list[str]:
    """Keys still needing work, preserving the order of all_keys."""
    done = completed_keys(conn, table, source)
    return [k for k in all_keys if k not in done]


def mark_in_progress(conn, table, source: str, chunk_key: str):
    existing = get_watermark(conn, table, source, chunk_key)
    attempt = (existing.get("attempt") or 0) + 1 if existing else 1
    upsert_rows(
        conn,
        table,
        [{
            "source": source,
            "chunk_key": chunk_key,
            "status": STATUS_IN_PROGRESS,
            "attempt": attempt,
            "row_count": existing.get("row_count") if existing else None,
            "error": None,
            "started_at": _now(),
            "completed_at": None,
        }],
        conflict_cols=["source", "chunk_key"],
    )
    return attempt


def mark_completed(conn, table, source: str, chunk_key: str, row_count: int):
    existing = get_watermark(conn, table, source, chunk_key)
    upsert_rows(
        conn,
        table,
        [{
            "source": source,
            "chunk_key": chunk_key,
            "status": STATUS_COMPLETED,
            "attempt": existing.get("attempt") if existing else 1,
            "row_count": int(row_count),
            "error": None,
            "started_at": existing.get("started_at") if existing else _now(),
            "completed_at": _now(),
        }],
        conflict_cols=["source", "chunk_key"],
    )


def mark_failed(conn, table, source: str, chunk_key: str, error: str):
    existing = get_watermark(conn, table, source, chunk_key)
    upsert_rows(
        conn,
        table,
        [{
            "source": source,
            "chunk_key": chunk_key,
            "status": STATUS_FAILED,
            "attempt": existing.get("attempt") if existing else 1,
            "row_count": existing.get("row_count") if existing else None,
            "error": str(error)[:2000],
            "started_at": existing.get("started_at") if existing else _now(),
            "completed_at": None,
        }],
        conflict_cols=["source", "chunk_key"],
    )


def status_summary(conn, table, source: str | None = None):
    stmt = select(table)
    if source:
        stmt = stmt.where(table.c.source == source)
    rows = [dict(r) for r in conn.execute(stmt).mappings()]
    by_status: dict[str, int] = {}
    total_rows = 0
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        if r["status"] == STATUS_COMPLETED and r["row_count"]:
            total_rows += r["row_count"]
    return {"chunks": by_status, "completed_row_count": total_rows, "entries": rows}
