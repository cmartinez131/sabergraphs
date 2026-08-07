import numpy as np
import pandas as pd

from data_pipeline.ingest import models
from data_pipeline.ingest.runner import frame_to_rows


def test_restricts_to_manifest_and_converts_na(caplog):
    df = pd.DataFrame({
        "game_pk": pd.array([1, 2], dtype="Int64"),
        "at_bat_number": pd.array([1, 1], dtype="Int64"),
        "pitch_number": pd.array([1, 2], dtype="Int64"),
        "bat_speed": pd.array([71.2, None], dtype="Float64"),
        "game_date": pd.to_datetime(["2024-06-04", "2024-06-04"]),
        "not_in_manifest_col": ["drift", "drift"],
    })
    with caplog.at_level("WARNING"):
        rows = frame_to_rows(df, models.raw_statcast_pitches, context="t")

    assert any("schema drift" in r.message for r in caplog.records)
    assert len(rows) == 2
    r0, r1 = rows
    assert "not_in_manifest_col" not in r0
    assert isinstance(r0["game_pk"], int) and not isinstance(r0["game_pk"], np.integer)
    assert isinstance(r0["bat_speed"], float)
    assert r1["bat_speed"] is None                       # pd.NA -> None
    assert str(r0["game_date"]) == "2024-06-04"          # datetime64 -> date
    assert r0["pitch_type"] is None                      # manifest col missing from fetch -> NULL
