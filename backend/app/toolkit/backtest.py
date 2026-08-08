# backend/app/toolkit/backtest.py
#
# Season-holdout backtest harness: train through season N-1, predict season
# N, for each target season. Four systems are compared on the SAME eligible
# population so the error numbers are directly comparable:
#
#   naive     repeat the most recent observed season
#   trailing  unweighted mean of the last 3 observed seasons (existing baseline)
#   knn       aging-curve + KNN comparables (existing), run with max_year=N-1
#             so it cannot see the evaluation period
#   marcel    classic Marcel (toolkit/marcel.py)
#
# Eligibility for target season N (applied identically to every system):
#   - target-season PA >= min_pa and the stat observed in season N
#   - at least one season with the stat observed (PA > 0) in the 3-year
#     window before N, so every system has usable history
#
# Experience buckets (by seasons observed in the data before N — true
# rookies with zero prior seasons cannot be predicted by any of these
# systems and are therefore not part of the evaluation):
#   rookie   1 prior observed season
#   2-3yr    2-3 prior observed seasons
#   veteran  4+ prior observed seasons
#
# Calibration: the 80% residual band (p10-p90 of actual-minus-predicted) is
# fit ONLY on folds strictly before the evaluated season and applied to that
# season — out-of-sample by construction. The KNN system's own p10/p90
# output band is additionally scored as-is ("native band").

import json
import os

import numpy as np
import pandas as pd

from .aging import project_stat_aging_knn
from .marcel import MARCEL_WEIGHTS, load_panel, marcel_project_all

# Written by `python -m app.toolkit.backtest_report`; read by /api/backtest
# and by knn_band_calibration() below.
RESULTS_JSON = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "ml_models", "backtest_results.json")
)

BUCKET_ROOKIE = "rookie (1 prior season)"
BUCKET_EARLY = "2-3 prior seasons"
BUCKET_VETERAN = "veteran (4+ prior seasons)"

DEFAULT_SYSTEMS = ("naive", "trailing", "marcel", "knn")
NOMINAL_BAND = 0.80

SYSTEM_LABELS = {
    "naive": "Naive repeat",
    "trailing": "Trailing mean (3yr)",
    "knn": "KNN-aging",
    "marcel": "Marcel",
}


def knn_band_calibration(results_path=RESULTS_JSON):
    """Calibration disclosure attached to every aging_knn response.

    The season-holdout backtest measured the empirical coverage of the KNN
    projection's own p10-p90 band at roughly half its nominal 80% for
    next-season forecasts (48.7% HR / 47.1% wOBA, n=1324) — the band is too
    narrow. Replacing it with residual-based bands needs per-horizon
    backtests and is open work; until then the API labels the method
    experimental and ships the measured numbers with every payload rather
    than hiding them.
    """
    out = {
        "status": "experimental",
        "nominal": NOMINAL_BAND,
        "note": (
            "Backtested empirical coverage of this p10-p90 band was well "
            "below the nominal 80% for next-season forecasts (see "
            "docs/BACKTEST.md). Treat the band as a lower bound on "
            "uncertainty."
        ),
    }
    try:
        with open(results_path) as fh:
            results = json.load(fh)
        rows = results.get("knn_native_band") or []
        coverage = {r["stat"]: round(float(r["coverage"]), 3) for r in rows}
        if coverage:
            out["measured_h1_coverage"] = coverage
    except Exception:
        pass
    return out


def _experience_bucket(n_prior):
    if n_prior <= 1:
        return BUCKET_ROOKIE
    if n_prior <= 3:
        return BUCKET_EARLY
    return BUCKET_VETERAN


def _eligible_for_season(panel, stat, season, min_pa, window):
    """Player ids eligible at target `season`, plus per-player experience
    buckets. See module docstring for the definition."""
    observed = panel[stat].notna() & (panel["pa"] > 0)
    target = panel[(panel["year"] == season) & (panel["pa"] >= min_pa) & panel[stat].notna()]
    prior = panel[(panel["year"] < season) & observed]
    recent = prior[prior["year"] >= season - window]

    ids = set(target["player_id"]) & set(recent["player_id"])
    n_prior = prior[prior["player_id"].isin(ids)].groupby("player_id")["year"].nunique()
    buckets = n_prior.map(_experience_bucket)
    actuals = target.set_index("player_id")[stat]
    return sorted(ids), buckets, actuals


def _predict_naive(panel, stat, season, ids):
    prior = panel[(panel["year"] < season) & panel[stat].notna()].sort_values("year")
    latest = prior.groupby("player_id")[stat].last()
    return latest.reindex(ids)


def _predict_trailing(panel, stat, season, ids, window=3):
    prior = panel[(panel["year"] < season) & panel[stat].notna()].sort_values("year")
    tail = prior.groupby("player_id").tail(window)
    return tail.groupby("player_id")[stat].mean().reindex(ids)


def _predict_marcel(panel, stat, season, ids):
    proj = marcel_project_all(panel, stat, season)
    return proj["proj_value"].reindex(ids)


def _predict_knn_one(engine, panel, stat, season, pid, knn_kwargs):
    """One KNN-aging projection with the training cutoff at season-1.
    Returns (pred, band_lo, band_hi), any of which may be None."""
    prior = panel[
        (panel["player_id"] == pid) & (panel["year"] < season) & panel[stat].notna()
    ]
    if prior.empty:
        return None, None, None
    base_year = int(prior["year"].max())
    horizon = season - base_year
    series, _meta = project_stat_aging_knn(
        db=None,
        db_engine=engine,
        player_id=pid,
        stat=stat,
        horizon=horizon,
        lookback=knn_kwargs.get("lookback", 3),
        k=knn_kwargs.get("k", 25),
        age_cap=knn_kwargs.get("age_cap", 42),
        alpha_comps=knn_kwargs.get("alpha_comps", 0.5),
        min_pa=knn_kwargs.get("min_pa", 200),
        max_year=season - 1,
    )

    def _value_at(series_id):
        for s in series:
            if s.get("id") == series_id or str(s.get("id", "")).startswith(series_id):
                for pt in s.get("data", []):
                    if pt.get("x") == season:
                        return float(pt["y"])
        return None

    pred = _value_at("Projected ")
    lo = _value_at("p10")
    hi = _value_at("p90")
    return pred, lo, hi


def run_season_holdout(
    db=None,
    engine=None,
    panel=None,
    stats=("woba", "home_run"),
    target_seasons=(2022, 2023, 2024, 2025),
    fold_start=2018,
    min_pa=200,
    systems=DEFAULT_SYSTEMS,
    trailing_window=3,
    knn_kwargs=None,
    player_limit=None,
    progress=None,
):
    """Run the holdout backtest and return prediction records + summary
    tables (see summarize_records). Folds are computed from `fold_start`
    through max(target_seasons); folds before the first target season only
    feed the out-of-sample residual-band fit.

    `panel` may be injected for tests; otherwise loaded via `db`.
    `engine` is only required when "knn" is among the systems.
    """
    log = progress or (lambda msg: None)
    knn_kwargs = knn_kwargs or {}
    if panel is None:
        if db is None:
            raise ValueError("Provide either a preloaded panel or a db session.")
        panel = load_panel(db, list(stats))
    if "knn" in systems and engine is None:
        raise ValueError("The knn system requires a SQLAlchemy engine.")

    window = len(MARCEL_WEIGHTS)
    fold_seasons = list(range(int(fold_start), max(target_seasons) + 1))
    records = []

    for stat in stats:
        for season in fold_seasons:
            ids, buckets, actuals = _eligible_for_season(panel, stat, season, min_pa, window)
            if player_limit is not None:
                ids = ids[: int(player_limit)]
            if not ids:
                continue
            log(f"fold {stat}/{season}: {len(ids)} eligible players")

            preds = {}
            if "naive" in systems:
                preds["naive"] = _predict_naive(panel, stat, season, ids)
            if "trailing" in systems:
                preds["trailing"] = _predict_trailing(panel, stat, season, ids, trailing_window)
            if "marcel" in systems:
                preds["marcel"] = _predict_marcel(panel, stat, season, ids)

            knn_bands = {}
            if "knn" in systems:
                knn_vals = {}
                for pid in ids:
                    p, lo, hi = _predict_knn_one(engine, panel, stat, season, pid, knn_kwargs)
                    knn_vals[pid] = p
                    knn_bands[pid] = (lo, hi)
                preds["knn"] = pd.Series(knn_vals, dtype=float).reindex(ids)

            for system, series in preds.items():
                for pid in ids:
                    pred = series.get(pid)
                    lo, hi = knn_bands.get(pid, (None, None)) if system == "knn" else (None, None)
                    records.append({
                        "system": system,
                        "stat": stat,
                        "season": season,
                        "player_id": pid,
                        "actual": float(actuals[pid]),
                        "pred": None if pred is None or pd.isna(pred) else float(pred),
                        "band_lo": lo,
                        "band_hi": hi,
                        "bucket": buckets.get(pid),
                    })

    records_df = pd.DataFrame(records)
    results = summarize_records(records_df, list(target_seasons))
    results["config"] = {
        "stats": list(stats),
        "target_seasons": [int(s) for s in target_seasons],
        "fold_start": int(fold_start),
        "min_pa": int(min_pa),
        "systems": list(systems),
        "trailing_window": int(trailing_window),
        "eligibility_window_years": window,
        "nominal_band": NOMINAL_BAND,
    }
    return records_df, results


def _metrics(group):
    err = group["pred"] - group["actual"]
    return {
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "mae": float(np.mean(np.abs(err))),
        "n": int(len(group)),
    }


def summarize_records(records_df, target_seasons):
    """Reduce raw prediction records to the report tables. Only rows in
    `target_seasons` count toward headline metrics; earlier folds feed the
    residual-band fit."""
    out = {"per_season": [], "overall": [], "per_bucket": [],
           "calibration": [], "knn_native_band": []}
    if records_df.empty:
        return out

    scored = records_df[records_df["pred"].notna()].copy()
    head = scored[scored["season"].isin(target_seasons)]

    for (system, stat, season), grp in head.groupby(["system", "stat", "season"]):
        out["per_season"].append({"system": system, "stat": stat,
                                  "season": int(season), **_metrics(grp)})
    for (system, stat), grp in head.groupby(["system", "stat"]):
        out["overall"].append({"system": system, "stat": stat, **_metrics(grp)})
    for (system, stat, bucket), grp in head.groupby(["system", "stat", "bucket"]):
        out["per_bucket"].append({"system": system, "stat": stat,
                                  "bucket": bucket, **_metrics(grp)})

    # Out-of-sample residual-band calibration (nominal 80%).
    for (system, stat), grp in scored.groupby(["system", "stat"]):
        covered = 0
        n_eval = 0
        for season in sorted(target_seasons):
            fit = grp[grp["season"] < season]
            ev = grp[grp["season"] == season]
            if len(fit) < 30 or ev.empty:
                continue
            resid = (fit["actual"] - fit["pred"]).to_numpy()
            q10, q90 = np.percentile(resid, [10, 90])
            inside = (ev["actual"] >= ev["pred"] + q10) & (ev["actual"] <= ev["pred"] + q90)
            covered += int(inside.sum())
            n_eval += int(len(ev))
        if n_eval:
            out["calibration"].append({
                "system": system, "stat": stat,
                "coverage": covered / n_eval, "n_eval": n_eval,
                "band": "residual p10-p90, fit on folds < evaluated season",
            })

    # KNN's own projection band, scored as produced.
    knn = head[(head["system"] == "knn") & head["band_lo"].notna() & head["band_hi"].notna()]
    for stat, grp in knn.groupby("stat"):
        inside = (grp["actual"] >= grp["band_lo"]) & (grp["actual"] <= grp["band_hi"])
        out["knn_native_band"].append({
            "stat": stat,
            "coverage": float(inside.mean()),
            "n_eval": int(len(grp)),
            "band": "knn native p10-p90 output",
        })
    return out
