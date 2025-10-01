# backend/app/api/schemas.py
from fastapi import HTTPException


def make_chart_response(chart_type, series, narration="", meta=None, facets=None):
    out = {
        "chart_type": chart_type,
        "series": series,
        "narration": narration,
    }
    if meta:
        out["meta"] = meta
    if facets is not None:
        out["facets"] = facets
    return out


def as_int_or_none(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except Exception:
        raise HTTPException(status_code=400, detail="Year values must be integers.")


def validate_compare_payload(payload):
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object.")

    player_ids = payload.get("player_ids")
    stat = payload.get("stat")

    if not isinstance(player_ids, list) or not player_ids:
        raise HTTPException(400, "player_ids must be a non-empty list.")
    try:
        player_ids = [int(x) for x in player_ids]
    except Exception:
        raise HTTPException(400, "player_ids must be integers.")

    if not isinstance(stat, str) or not stat:
        raise HTTPException(400, "stat is required (e.g., 'home_run', 'woba').")

    year = as_int_or_none(payload.get("year"))
    start_year = as_int_or_none(payload.get("start_year"))
    end_year = as_int_or_none(payload.get("end_year"))

    if year and (start_year or end_year):
        raise HTTPException(400, "Provide either 'year' OR 'start_year'+'end_year', not both.")
    if (start_year and not end_year) or (end_year and not start_year):
        raise HTTPException(400, "Provide both 'start_year' and 'end_year' for a range.")

    return {
        "player_ids": player_ids,
        "stat": stat,
        "year": year,
        "start_year": start_year,
        "end_year": end_year,
    }


def validate_predict_payload(payload):
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object.")

    try:
        player_id = int(payload.get("player_id"))
    except Exception:
        raise HTTPException(400, "player_id must be an integer.")

    stat = payload.get("stat")
    if not isinstance(stat, str) or not stat:
        raise HTTPException(400, "stat is required (e.g., 'woba').")

    years = payload.get("years", 3)
    try:
        years = int(years)
    except Exception:
        raise HTTPException(400, "years must be an integer.")

    horizon = payload.get("horizon", 1)
    try:
        horizon = int(horizon)
    except Exception:
        raise HTTPException(400, "horizon must be an integer.")
    if horizon < 1:
        raise HTTPException(400, "horizon must be >= 1.")

    # New knobs for ML
    method = payload.get("method", "baseline")  # "baseline", "ml", "ml_prob"
    lookback = int(payload.get("lookback", years))

    return {
        "player_id": player_id,
        "stat": stat,
        "years": years,
        "horizon": horizon,
        "method": method,
        "lookback": lookback,
    }


def as_list_str(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if str(s).strip()]
    if isinstance(v, list):
        return [str(s).strip() for s in v if str(s).strip()]
    raise HTTPException(400, "Expected a list or a comma-separated string.")


def validate_compare_multi_payload(payload):
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object.")

    players = payload.get("players") or payload.get("player_ids")
    if not isinstance(players, list) or not players:
        raise HTTPException(400, "'players' (names) or 'player_ids' (ints) is required (list).")

    stats = as_list_str(payload.get("stats"))
    if not stats:
        raise HTTPException(400, "'stats' is required (list or comma-separated).")

    year = as_int_or_none(payload.get("year"))
    start_year = as_int_or_none(payload.get("start_year"))
    end_year = as_int_or_none(payload.get("end_year"))

    if year and (start_year or end_year):
        raise HTTPException(400, "Provide either 'year' OR 'start_year'+'end_year', not both.")
    if (start_year and not end_year) or (end_year and not start_year):
        raise HTTPException(400, "Provide both 'start_year' and 'end_year' for a range.")

    mode = payload.get("mode", "players_by_stat")
    if mode not in ("players_by_stat", "stats_by_player"):
        raise HTTPException(400, "mode must be 'players_by_stat' or 'stats_by_player'.")

    layout = payload.get("layout", "grouped")
    if layout not in ("grouped", "stacked"):
        raise HTTPException(400, "layout must be 'grouped' or 'stacked'.")

    normalize = payload.get("normalize")
    window = payload.get("window")
    if window is not None:
        try:
            window = int(window)
        except Exception:
            raise HTTPException(400, "window must be an integer.")

    return {
        "players": players,
        "stats": stats,
        "year": year,
        "start_year": start_year,
        "end_year": end_year,
        "mode": mode,
        "layout": layout,
        "normalize": normalize,
        "window": window,
    }
