from datetime import date

import pytest

from data_pipeline.ingest.chunks import chunk_key, date_chunks, season_chunks, season_window


def test_chunks_cover_every_day_exactly_once():
    start, end = date(2024, 2, 20), date(2024, 11, 10)
    chunks = date_chunks(start, end, 7)
    days = []
    for s, e in chunks:
        assert s <= e
        d = s
        while d <= e:
            days.append(d)
            d = date.fromordinal(d.toordinal() + 1)
    expected = (end - start).days + 1
    assert len(days) == expected
    assert len(set(days)) == expected  # no overlap
    assert days[0] == start and days[-1] == end


def test_last_chunk_is_short_when_range_does_not_divide():
    chunks = date_chunks(date(2024, 6, 3), date(2024, 6, 12), 7)
    assert chunks == [
        (date(2024, 6, 3), date(2024, 6, 9)),
        (date(2024, 6, 10), date(2024, 6, 12)),
    ]


def test_single_day_range():
    assert date_chunks(date(2024, 6, 3), date(2024, 6, 3), 7) == [
        (date(2024, 6, 3), date(2024, 6, 3))
    ]


def test_invalid_ranges_raise():
    with pytest.raises(ValueError):
        date_chunks(date(2024, 6, 3), date(2024, 6, 2), 7)
    with pytest.raises(ValueError):
        date_chunks(date(2024, 6, 3), date(2024, 6, 9), 0)


def test_chunk_key_format():
    assert chunk_key(date(2024, 6, 3), date(2024, 6, 9)) == "2024-06-03..2024-06-09"


def test_season_window():
    assert season_window(2023, "02-20", "11-10") == (date(2023, 2, 20), date(2023, 11, 10))


def test_season_chunks_skips_future_and_clamps_current():
    today = date(2024, 6, 15)
    chunks = season_chunks([2023, 2024, 2025], 7, "02-20", "11-10", today=today)
    seasons = {s for s, _, _ in chunks}
    assert seasons == {2023, 2024}  # 2025 entirely in the future
    assert max(e for _, _, e in chunks) <= today  # 2024 clamped to today
    # 2023 fully enumerated
    assert max(e for s, _, e in chunks if s == 2023) == date(2023, 11, 10)


def test_season_chunks_ordered_oldest_first():
    chunks = season_chunks([2022, 2021], 7, "02-20", "11-10", today=date(2023, 1, 1))
    starts = [s for _, s, _ in chunks]
    assert starts == sorted(starts)
