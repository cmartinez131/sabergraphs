# backend/app/toolkit/projections.py

import numpy as np
from ..db.models import BattingStats
from .ml import predict_next_stat, probability_above_average
from .stats import label_map_for, stat_label, resolve_stat_column


def predict_player_stat(db, player_id, stat, years=3):
    """
    Baseline single-value projection:
    average of the last `years` seasons for the given stat.
    """
    col = resolve_stat_column(db, stat)
    rows = (
        db.query(BattingStats.year, col.label("v"))
          .filter(BattingStats.player_id == player_id)
          .order_by(BattingStats.year.desc())
          .limit(int(years))
          .all()
    )
    vals = [r.v for r in rows if r.v is not None]
    if not vals:
        return None
    return float(np.mean(vals))


def predict_player_stat_series(db, player_id, stat, lookback_years=3, horizon=5):
    """
    Simple linear-trend forecast for the next `horizon` seasons using the
    last `lookback_years` of history. If fewer than 2 points are available,
    repeats the mean of the available window.
    """
    col = resolve_stat_column(db, stat)
    rows = (
        db.query(BattingStats.year, col.label("v"))
          .filter(BattingStats.player_id == player_id)
          .order_by(BattingStats.year.asc())
          .all()
    )
    pts = [(int(y), float(v)) for (y, v) in rows if v is not None]
    if not pts:
        return []

    years = sorted({y for (y, _) in pts})
    recent_years = years[-lookback_years:] if len(years) > lookback_years else years
    recent = [(y, v) for (y, v) in pts if y in recent_years]

    if len(recent) >= 2:
        x = np.array([p[0] for p in recent], dtype=float)
        y = np.array([p[1] for p in recent], dtype=float)
        a, b = np.polyfit(x, y, 1)  # y = a*x + b
        last_year = max(recent_years)
        forecast = []
        for i in range(1, int(horizon) + 1):
            fy = last_year + i
            fv = float(a * fy + b)
            forecast.append((fy, fv))
        return forecast
    else:
        mean_val = float(np.mean([v for (_, v) in recent]))
        last_year = max(recent_years)
        return [(last_year + i, mean_val) for i in range(1, int(horizon) + 1)]


# -------------------- ML wrappers --------------------
# Note: These call into toolkit/ml.py which currently resolves columns via
# getattr(BattingStats, stat). If you plan to use method="ml" or "ml_prob" with
# stats that exist in the DB but are not defined as ORM attributes, update
# models.py to use the same resolver or add a reflection fallback there too.

def predict_player_stat_ml(db, player_id, stat, lookback=3):
    out = predict_next_stat(db, player_id, stat, lookback=lookback, train_if_missing=True)
    if out is None:
        return {
            "chart_type": "bar",
            "series": [{"id": "Projected " + stat, "data": []}],
            "meta": {
                "stat": stat,
                "lookback": lookback,
                "warnings": ["no_history"],
                "label_map": label_map_for([stat]),
            },
        }
    y = out["pred"]
    data = [{"x": "Next season", "y": float(y)}]
    meta = {
        "stat": stat,
        "model": "ridge",
        "lookback": lookback,
        "league_mean_baseline": out["league_mean"],
        "delta_vs_league": out["delta_vs_league"],
        "latest_year_used": out["meta"]["latest_year"],
        "trained_rows": out["meta"]["trained_rows"],
        "label_map": label_map_for([stat]),
        "title": "Projected " + stat_label(stat),
    }
    return {"chart_type": "bar", "series": [{"id": "Projected " + stat, "data": data}], "meta": meta}


def predict_player_above_avg_prob(db, player_id, stat, lookback=3):
    out = probability_above_average(db, player_id, stat, lookback=lookback, train_if_missing=True)
    if out is None:
        return {
            "chart_type": "bar",
            "series": [{"id": "Above-Avg Prob", "data": []}],
            "meta": {
                "stat": stat,
                "lookback": lookback,
                "warnings": ["no_history"],
                "label_map": label_map_for([stat]),
            },
        }
    p = out["prob_above_avg"]
    data = [{"x": "Above league avg", "y": float(100.0 * p)}]
    meta = {
        "stat": stat,
        "model": "logistic",
        "lookback": lookback,
        "league_mean_baseline": out["league_mean"],
        "latest_year_used": out["meta"]["latest_year"],
        "trained_rows": out["meta"]["trained_rows"],
        "unit": "percent",
        "label_map": label_map_for([stat]),
        "title": f"Above-Average Probability — {stat_label(stat)}",
    }
    return {"chart_type": "bar", "series": [{"id": "Probability (%)", "data": data}], "meta": meta}
