# backend/app/api/backtest.py
#
# Rolling-origin backtests for simple next-season forecasts.
# Returns summary error metrics and a small bar chart so you can visualize MAE/RMSE
# alongside p10–p90 coverage of an empirical residual band.
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
import numpy as np

from ..db.database import get_db
from ..db.models import BattingStats
from ..toolkit.stats import (
    resolve_stat_column,
    col_exists,
    label_map_for,
    stat_label,
    latest_year,
)
from .schemas import make_chart_response

router = APIRouter(prefix="/api", tags=["backtest"])


def parse_payload(p):
    if not isinstance(p, dict):
        raise HTTPException(400, "Body must be a JSON object.")

    stat = p.get("stat")
    if not isinstance(stat, str) or not stat.strip():
        raise HTTPException(400, "Provide 'stat' (e.g., 'woba', 'on_base_plus_slg', 'home_run').")

    start_year = p.get("start_year")
    end_year = p.get("end_year")
    lookback = p.get("lookback", 3)
    method = (p.get("method") or "baseline").lower()  # 'baseline' (mean) or 'linear'
    min_pa = p.get("min_pa")  # apply to target year only if provided

    try:
        if start_year is not None:
            start_year = int(start_year)
        if end_year is not None:
            end_year = int(end_year)
        lookback = int(lookback)
        if min_pa is not None:
            min_pa = int(min_pa)
    except Exception:
        raise HTTPException(400, "start_year/end_year/lookback/min_pa must be integers if provided.")

    if not start_year or not end_year:
        raise HTTPException(400, "Provide both 'start_year' and 'end_year' (inclusive).")
    if end_year <= start_year:
        raise HTTPException(400, "'end_year' must be greater than 'start_year'.")
    if lookback < 1:
        raise HTTPException(400, "'lookback' must be >= 1.")
    if method not in ("baseline", "linear"):
        raise HTTPException(400, "Unsupported method. Use 'baseline' or 'linear'.")

    return {
        "stat": stat.strip(),
        "start_year": start_year,
        "end_year": end_year,
        "lookback": lookback,
        "method": method,
        "min_pa": min_pa,
    }


def run_backtest(db, stat, start_year, end_year, lookback, method, min_pa):
    col = resolve_stat_column(db, stat)
    pa_col = resolve_stat_column(db, "plate_appearances") if col_exists(db, "plate_appearances") else None

    # We need history up to each origin year, so pull from (start_year - lookback + 1) through end_year
    fetch_start = start_year - lookback + 1
    fetch_end = end_year

    qcols = [BattingStats.player_id, BattingStats.year, col.label("v")]
    if pa_col is not None:
        qcols.append(pa_col.label("pa"))

    rows = (
        db.query(*qcols)
        .filter(BattingStats.year.between(fetch_start, fetch_end))
        .all()
    )

    # Organize by player -> {year: value}, and PA if available
    by_player = {}
    by_player_pa = {}

    for row in rows:
        pid = row[0]
        y = int(row[1])
        v = row[2]
        if pid not in by_player:
            by_player[pid] = {}
        by_player[pid][y] = None if v is None else float(v)

        if pa_col is not None:
            pa = row[3] if len(row) > 3 else None
            if pid not in by_player_pa:
                by_player_pa[pid] = {}
            by_player_pa[pid][y] = None if pa is None else int(pa)

    # Rolling-origin: predict y+1 using the last `lookback` seasons up to y
    preds = []
    actuals = []
    folds = 0

    for pid, series in by_player.items():
        years_available = sorted(series.keys())
        if not years_available:
            continue

        for origin in range(start_year, end_year):
            target = origin + 1
            # ensure target actual exists
            if target not in series or series[target] is None:
                continue

            # optional playing-time filter on the TARGET year only
            if min_pa is not None and pa_col is not None:
                target_pa = by_player_pa.get(pid, {}).get(target)
                if target_pa is None or target_pa < min_pa:
                    continue

            # collect history window
            hist_years = [y for y in range(origin - lookback + 1, origin + 1)]
            hist_vals = [(y, series.get(y)) for y in hist_years if series.get(y) is not None]

            if method == "linear":
                # need at least 2 points for a slope; otherwise fallback to mean
                if len(hist_vals) >= 2:
                    xs = np.array([y for y, _ in hist_vals], dtype=float)
                    ys = np.array([v for _, v in hist_vals], dtype=float)
                    a, b = np.polyfit(xs, ys, 1)  # y = a*x + b
                    pred = float(a * target + b)
                elif len(hist_vals) >= 1:
                    pred = float(np.mean([v for _, v in hist_vals]))
                else:
                    continue
            else:
                # baseline mean of available window
                if len(hist_vals) >= 1:
                    pred = float(np.mean([v for _, v in hist_vals]))
                else:
                    continue

            preds.append(pred)
            actuals.append(series[target])
            folds += 1

    if not preds:
        latest = latest_year(db)
        raise HTTPException(
            400,
            "No eligible rows for backtest in the requested window. "
            "Check min_pa, lookback, and that data exists through {}.".format(latest),
        )

    preds = np.array(preds, dtype=float)
    actuals = np.array(actuals, dtype=float)
    errors = preds - actuals
    abs_err = np.abs(errors)

    mae = float(np.mean(abs_err))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    bias = float(np.mean(errors))

    # Empirical residual band (p10–p90) and coverage
    p10 = float(np.percentile(errors, 10))
    p90 = float(np.percentile(errors, 90))
    covered = np.logical_and(errors >= p10, errors <= p90).sum()
    coverage = float(covered) / float(len(errors))

    metrics = {
        "n_predictions": int(len(errors)),
        "mae": mae,
        "rmse": rmse,
        "bias": bias,
        "residual_p10": p10,
        "residual_p90": p90,
        "coverage_10_90": coverage,
        "lookback": int(lookback),
        "method": method,
        "window": {"start_year": int(start_year), "end_year": int(end_year)},
        "stat": stat,
    }

    # Small bar chart so you can visualize quickly in the UI
    series = [
        {
            "id": "Absolute error",
            "data": [
                {"x": "MAE", "y": mae},
                {"x": "RMSE", "y": rmse},
            ],
        },
        {
            "id": "Coverage (%)",
            "data": [
                {"x": "p10–p90", "y": 100.0 * coverage},
            ],
        },
    ]

    meta = {
        "title": "Backtest — {} ({}–{}, lookback {}, method {})".format(
            stat_label(stat), start_year, end_year, lookback, method
        ),
        "label_map": {
            stat: stat_label(stat),
            "MAE": "MAE",
            "RMSE": "RMSE",
            "p10–p90": "p10–p90",
            "Coverage (%)": "Coverage (%)",
            "Absolute error": "Absolute error",
        },
        "metrics": metrics,
    }

    narration = (
        "Backtest over {n} predictions. MAE {mae:.3f}, RMSE {rmse:.3f}, bias {bias:.3f}. "
        "Empirical residual band p10–p90 = [{p10:.3f}, {p90:.3f}] with {cov:.1f}% coverage."
    ).format(
        n=metrics["n_predictions"],
        mae=mae,
        rmse=rmse,
        bias=bias,
        p10=p10,
        p90=p90,
        cov=100.0 * coverage,
    )

    return series, meta, narration


@router.post("/backtest")
async def backtest_endpoint(request: Request, db=Depends(get_db)):
    payload = await request.json()
    args = parse_payload(payload)
    try:
        series, meta, narration = run_backtest(
            db=db,
            stat=args["stat"],
            start_year=args["start_year"],
            end_year=args["end_year"],
            lookback=args["lookback"],
            method=args["method"],
            min_pa=args["min_pa"],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

    return make_chart_response(
        chart_type="bar",
        series=series,
        narration=narration,
        meta=meta,
    )
