import pandas as pd
import pytest

from data_pipeline.ingest.quality import QualityError, check_chunk

KEY = ["game_pk", "at_bat_number", "pitch_number"]


def _frame(rows):
    return pd.DataFrame(rows, columns=KEY + ["v"])


def test_clean_frame_passes():
    df = _frame([(1, 1, 1, "a"), (1, 1, 2, "b")])
    clean, report = check_chunk(df, KEY, context="t")
    assert len(clean) == 2
    assert report["dupes_dropped"] == 0


def test_missing_key_column_raises():
    df = pd.DataFrame({"game_pk": [1]})
    with pytest.raises(QualityError, match="key columns missing"):
        check_chunk(df, KEY)


def test_null_key_raises():
    df = _frame([(1, 1, None, "a")])
    with pytest.raises(QualityError, match="NULL natural-key"):
        check_chunk(df, KEY)


def test_small_duplicate_count_dropped_keeping_last():
    rows = [(1, 1, 1, "old"), (1, 1, 1, "new")] + [(1, 1, n, "x") for n in range(2, 400)]
    df = _frame(rows)
    clean, report = check_chunk(df, KEY, max_duplicate_key_rate=0.005)
    assert report["dupes_dropped"] == 1
    kept = clean[(clean.game_pk == 1) & (clean.at_bat_number == 1) & (clean.pitch_number == 1)]
    assert list(kept["v"]) == ["new"]


def test_high_duplicate_rate_fails():
    df = _frame([(1, 1, 1, "a"), (1, 1, 1, "b"), (1, 1, 2, "c")])
    with pytest.raises(QualityError, match="duplicate-key rate"):
        check_chunk(df, KEY, max_duplicate_key_rate=0.005)


def test_empty_frame_is_clean():
    df = _frame([])
    clean, report = check_chunk(df, KEY)
    assert len(clean) == 0 and report["rows_out"] == 0
