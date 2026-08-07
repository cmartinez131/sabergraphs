# backend/app/toolkit/ml.py
import os
import json
import numpy as np
import pandas as pd

from sqlalchemy import func
from sklearn.linear_model import Ridge, LogisticRegression

from ..db.models import BattingStats
from .stats import resolve_stat_column  # unified safe resolver

# --------- small helpers (no leading underscores) ---------

def stat_column(db, stat):
    """
    Return a SQLAlchemy column/expression for `stat`, supporting both
    ORM attributes and raw DB columns via reflection (see stats.resolve_stat_column).
    """
    return resolve_stat_column(db, stat)

def latest_year(db):
    y = db.query(func.max(BattingStats.year)).scalar()
    return int(y) if y else 2025

def model_path(stat, lookback=3, kind="ridge"):
    name = f"{kind}_{stat}_L{int(lookback)}.json"
    base = os.path.join(os.path.dirname(__file__), "..", "ml_models")
    return os.path.abspath(os.path.join(base, name))

def ensure_dir(path):
    d = os.path.dirname(path)
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

# --------- dataset building ---------

def make_training_frame(db, stat, lookback=3, min_pa=0):
    """
    Build a per-player/year panel and create a supervised dataset where
    features are based on seasons up to year t, and the target is stat at year t+1.
    """
    col = stat_column(db, stat)
    sel = [
        BattingStats.player_id,
        BattingStats.full_name,
        BattingStats.year,
        BattingStats.player_age,
        BattingStats.plate_appearances,
        col.label("stat"),
    ]
    rows = db.query(*sel).all()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["player_id", "full_name", "year", "age", "pa", "stat"])
    df = df.sort_values(["player_id", "year"]).reset_index(drop=True)

    # league aggregates per year for normalization/targets
    lg = df.groupby("year")["stat"].agg(["mean", "std"]).rename(columns={"mean": "lg_mean", "std": "lg_std"})
    df = df.merge(lg, left_on="year", right_index=True, how="left")

    # lags and rolling features by player
    feats = []
    for pid, g in df.groupby("player_id"):
        g = g.sort_values("year")
        g["lag1"] = g["stat"].shift(1)
        g["lag2"] = g["stat"].shift(2)
        g["roll_mean"] = g["stat"].rolling(lookback, min_periods=1).mean().shift(1)
        g["roll_std"] = g["stat"].rolling(lookback, min_periods=1).std().shift(1)
        g["z_last"] = (g["lag1"] - g["lg_mean"]) / g["lg_std"]
        # target is next year's stat
        g["target"] = g["stat"].shift(-1)
        g["target_year"] = g["year"] + 1
        g["age_next"] = (g["age"] + 1).fillna(g["age"])
        feats.append(g)
    X = pd.concat(feats, ignore_index=True)

    # league mean for the target year (to compute above/below average and delta)
    lg_next = lg.rename(columns={"lg_mean": "lg_mean_next", "lg_std": "lg_std_next"})
    X = X.merge(lg_next, left_on="target_year", right_index=True, how="left")

    # optional PA filter
    if min_pa and "pa" in X.columns:
        X = X[X["pa"].fillna(0) >= int(min_pa)]

    # keep only rows with all key ingredients
    keep_cols = ["player_id", "full_name", "year", "target_year",
                 "lag1", "lag2", "roll_mean", "roll_std", "z_last",
                 "age_next", "lg_mean_next", "lg_std_next", "target"]
    X = X[keep_cols].dropna(subset=["lag1", "target", "lg_mean_next"])

    # fill remaining NaNs (e.g., roll_std early) with 0
    for c in ["lag2", "roll_mean", "roll_std", "z_last"]:
        X[c] = X[c].fillna(0.0)

    # features and targets
    feature_cols = ["lag1", "lag2", "roll_mean", "roll_std", "z_last", "age_next"]
    y_reg = X["target"].values.astype(float)
    y_cls = (X["target"].values > X["lg_mean_next"].values).astype(int)

    return X, feature_cols, y_reg, y_cls

# --------- train/save/load ---------

def train_ridge_and_save(db, stat, lookback=3, min_pa=0, alpha=1.0, save=True):
    X, feature_cols, y_reg, _ = make_training_frame(db, stat, lookback, min_pa)
    if len(X) < 20:
        raise ValueError("Not enough rows to train ridge model.")

    means = X[feature_cols].mean().to_dict()
    stds = (X[feature_cols].std().replace(0, 1)).to_dict()
    Xz = (X[feature_cols] - pd.Series(means)).divide(pd.Series(stds))

    model = Ridge(alpha=float(alpha))
    model.fit(Xz.values, y_reg)

    params = {
        "kind": "ridge",
        "stat": stat,
        "lookback": int(lookback),
        "feature_cols": feature_cols,
        "coef": list(model.coef_),
        "intercept": float(model.intercept_),
        "means": means,
        "stds": stds,
        "trained_rows": int(len(X)),
    }

    if save:
        p = model_path(stat, lookback, "ridge")
        ensure_dir(p)
        with open(p, "w") as f:
            json.dump(params, f)
    return params

def train_logistic_and_save(db, stat, lookback=3, min_pa=0, C=1.0, save=True):
    X, feature_cols, _, y_cls = make_training_frame(db, stat, lookback, min_pa)
    if len(X) < 20:
        raise ValueError("Not enough rows to train logistic model.")

    means = X[feature_cols].mean().to_dict()
    stds = (X[feature_cols].std().replace(0, 1)).to_dict()
    Xz = (X[feature_cols] - pd.Series(means)).divide(pd.Series(stds))

    clf = LogisticRegression(C=float(C), max_iter=200)
    clf.fit(Xz.values, y_cls)

    params = {
        "kind": "logistic",
        "stat": stat,
        "lookback": int(lookback),
        "feature_cols": feature_cols,
        "coef": list(clf.coef_[0]),
        "intercept": float(clf.intercept_[0]),
        "means": means,
        "stds": stds,
        "trained_rows": int(len(X)),
    }

    if save:
        p = model_path(stat, lookback, "logistic")
        ensure_dir(p)
        with open(p, "w") as f:
            json.dump(params, f)
    return params

def load_model(kind, stat, lookback=3):
    p = model_path(stat, lookback, kind)
    if not os.path.exists(p):
        return None
    with open(p, "r") as f:
        return json.load(f)

# --------- inference helpers ---------

def player_feature_row(db, player_id, stat, lookback=3):
    """
    Build one feature row using the most recent history available and return:
      row (dict), latest_year (int), league_mean_next (float), league_std_next (float)
    """
    col = stat_column(db, stat)
    rows = (
        db.query(
            BattingStats.year,
            BattingStats.player_age,
            BattingStats.plate_appearances,
            col.label("stat"),
        )
        .filter(BattingStats.player_id == int(player_id))
        .order_by(BattingStats.year.asc())
        .all()
    )
    if not rows:
        return None, None, None, None

    df = pd.DataFrame(rows, columns=["year", "age", "pa", "stat"]).sort_values("year")
    last_year = int(df["year"].max())

    # lags from last seasons up to lookback
    df["roll_mean"] = df["stat"].rolling(lookback, min_periods=1).mean()
    df["roll_std"] = df["stat"].rolling(lookback, min_periods=1).std().fillna(0.0)

    row_last = df.iloc[-1]
    lag1 = float(row_last["stat"])
    lag2 = float(df.iloc[-2]["stat"]) if len(df) >= 2 else 0.0
    roll_mean = float(row_last["roll_mean"])
    roll_std = float(row_last["roll_std"])
    age_next = float((row_last["age"] or 0) + 1)

    # league mean for next year (proxy: use last year's mean as baseline)
    lg = (
        db.query(func.avg(col).label("m"), func.stddev(col).label("s"))
        .filter(BattingStats.year == last_year)
        .first()
    )
    lg_mean_next = float(lg[0]) if lg and lg[0] is not None else None
    lg_std_next = float(lg[1]) if lg and lg[1] is not None else None

    # z_last relative to last year's league
    if lg_mean_next is not None and lg_std_next not in (None, 0):
        z_last = (lag1 - lg_mean_next) / lg_std_next
    else:
        z_last = 0.0

    feat = {
        "lag1": lag1,
        "lag2": lag2,
        "roll_mean": roll_mean,
        "roll_std": roll_std,
        "z_last": z_last,
        "age_next": age_next,
    }
    return feat, last_year, lg_mean_next, lg_std_next

def apply_linear_params(params, feat_row):
    cols = params["feature_cols"]
    means = params["means"]
    stds = params["stds"]
    x = []
    for c in cols:
        val = float(feat_row.get(c, 0.0))
        mu = float(means.get(c, 0.0))
        sd = float(stds.get(c, 1.0)) or 1.0
        x.append((val - mu) / sd)
    x = np.array(x)
    coef = np.array(params["coef"])
    pred = float(np.dot(coef, x) + params["intercept"])
    return pred

# --------- public inference APIs ---------

def predict_next_stat(db, player_id, stat, lookback=3, train_if_missing=True):
    """
    Returns dict: { 'pred': float, 'league_mean': float, 'delta_vs_league': float, 'meta': {...} }
    Trains a small ridge model if no saved params are found.
    """
    params = load_model("ridge", stat, lookback)
    if params is None and train_if_missing:
        params = train_ridge_and_save(db, stat, lookback, min_pa=0, alpha=1.0, save=True)

    feat, last_year_val, lg_mean_next, _ = player_feature_row(db, player_id, stat, lookback)
    if feat is None:
        return None

    pred = apply_linear_params(params, feat) if params else feat["lag1"]
    delta = pred - lg_mean_next if lg_mean_next is not None else None

    return {
        "pred": float(pred),
        "league_mean": float(lg_mean_next) if lg_mean_next is not None else None,
        "delta_vs_league": float(delta) if delta is not None else None,
        "meta": {
            "stat": stat,
            "lookback": int(lookback),
            "latest_year": int(last_year_val),
            "model_kind": params["kind"] if params else "none",
            "trained_rows": params.get("trained_rows") if params else None,
        },
    }

def probability_above_average(db, player_id, stat, lookback=3, train_if_missing=True):
    params = load_model("logistic", stat, lookback)
    if params is None and train_if_missing:
        params = train_logistic_and_save(db, stat, lookback, min_pa=0, C=1.0, save=True)

    feat, last_year_val, lg_mean_next, _ = player_feature_row(db, player_id, stat, lookback)
    if feat is None:
        return None

    # manual logistic with stored coef
    cols = params["feature_cols"]
    means = params["means"]
    stds = params["stds"]
    x = []
    for c in cols:
        val = float(feat.get(c, 0.0))
        mu = float(means.get(c, 0.0))
        sd = float(stds.get(c, 1.0)) or 1.0
        x.append((val - mu) / sd)
    x = np.array(x)
    z = float(np.dot(np.array(params["coef"]), x) + params["intercept"])
    p = float(1.0 / (1.0 + np.exp(-z)))

    return {
        "prob_above_avg": p,
        "league_mean": float(lg_mean_next) if lg_mean_next is not None else None,
        "meta": {
            "stat": stat,
            "lookback": int(lookback),
            "latest_year": int(last_year_val),
            "model_kind": params["kind"] if params else "none",
            "trained_rows": params.get("trained_rows") if params else None,
        },
    }
