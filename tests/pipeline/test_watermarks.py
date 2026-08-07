import pytest
from sqlalchemy import create_engine

from data_pipeline.ingest import models
from data_pipeline.ingest.watermarks import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    get_watermark,
    mark_completed,
    mark_failed,
    mark_in_progress,
    pending_keys,
    status_summary,
)

SRC = "statcast_pitches"


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    models.ingest_watermarks.create(eng)
    return eng


def test_lifecycle_and_attempt_counter(engine):
    wm = models.ingest_watermarks
    with engine.begin() as conn:
        assert mark_in_progress(conn, wm, SRC, "w1") == 1
        assert get_watermark(conn, wm, SRC, "w1")["status"] == STATUS_IN_PROGRESS

        mark_completed(conn, wm, SRC, "w1", row_count=123)
        row = get_watermark(conn, wm, SRC, "w1")
        assert row["status"] == STATUS_COMPLETED
        assert row["row_count"] == 123

        # a new claim on the same chunk bumps the attempt counter
        assert mark_in_progress(conn, wm, SRC, "w1") == 2


def test_failed_records_error(engine):
    wm = models.ingest_watermarks
    with engine.begin() as conn:
        mark_in_progress(conn, wm, SRC, "w1")
        mark_failed(conn, wm, SRC, "w1", "boom")
        row = get_watermark(conn, wm, SRC, "w1")
        assert row["status"] == STATUS_FAILED
        assert row["error"] == "boom"


def test_pending_keys_resume_semantics(engine):
    """completed chunks are skipped; failed/in_progress/unseen are retried, in order."""
    wm = models.ingest_watermarks
    keys = ["w1", "w2", "w3", "w4"]
    with engine.begin() as conn:
        mark_in_progress(conn, wm, SRC, "w1")
        mark_completed(conn, wm, SRC, "w1", 10)      # done -> skip
        mark_in_progress(conn, wm, SRC, "w2")        # crashed mid-chunk -> redo
        mark_in_progress(conn, wm, SRC, "w3")
        mark_failed(conn, wm, SRC, "w3", "rate limited")  # failed -> redo
        # w4 never attempted -> do
        assert pending_keys(conn, wm, SRC, keys) == ["w2", "w3", "w4"]


def test_pending_keys_isolated_per_source(engine):
    wm = models.ingest_watermarks
    with engine.begin() as conn:
        mark_completed(conn, wm, "other_source", "w1", 5)
        assert pending_keys(conn, wm, SRC, ["w1"]) == ["w1"]


def test_status_summary_counts_completed_rows(engine):
    wm = models.ingest_watermarks
    with engine.begin() as conn:
        mark_completed(conn, wm, SRC, "w1", 10)
        mark_completed(conn, wm, SRC, "w2", 32)
        mark_failed(conn, wm, SRC, "w3", "x")
        s = status_summary(conn, wm, SRC)
        assert s["chunks"] == {STATUS_COMPLETED: 2, STATUS_FAILED: 1}
        assert s["completed_row_count"] == 42
