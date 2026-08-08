# backend/app/toolkit/aging.py


import numpy as np
import pandas as pd
from sqlalchemy import inspect, text

# --------------------------
# Config knobs (safe defaults)
# --------------------------
DEFAULT_MIN_PA = 200         # filter for league aging curve & comps
DEFAULT_AGE_MIN = 18
DEFAULT_AGE_MAX = 45
DEFAULT_START_YEAR = 2015
DEFAULT_END_YEAR = 2025

# Small guardrail for division by zero in ratio math
EPS = 1e-9

# Sentinel year bound used when no max_year cutoff is requested.
NO_YEAR_CAP = 9999


def _year_cap(max_year):
    """Normalize an optional training-data cutoff. `max_year` exists so the
    backtest harness can evaluate this system honestly: with max_year=N-1 no
    query may read seasons >= N. Default (None) = production behavior, all
    available seasons."""
    return int(max_year) if max_year is not None else NO_YEAR_CAP


def _table_columns(engine, table_name):
    # Dialect-agnostic (works on Postgres and the sqlite test fixtures).
    return {c["name"] for c in inspect(engine).get_columns(table_name)}


def _ensure_stat_column(engine, stat):
    cols = _table_columns(engine, "batting_stats")
    if stat not in cols:
        raise ValueError("Unknown stat column: %s" % stat)
    return stat


def _fetch_player_history(engine, player_id, stat, max_year=None):
    sql = text(
        """
        SELECT year, player_age, plate_appearances, {stat} AS v
        FROM batting_stats
        WHERE player_id = :pid
          AND {stat} IS NOT NULL
          AND year <= :max_year
        ORDER BY year ASC
        """.format(stat=stat)
    )
    df = pd.read_sql(
        sql, engine,
        params={"pid": int(player_id), "max_year": _year_cap(max_year)},
    )
    # Clean up types
    for c in ("year", "player_age", "plate_appearances"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["v"] = pd.to_numeric(df["v"], errors="coerce")
    df = df.dropna(subset=["year", "player_age"])
    return df


def _league_age_curve(engine, stat, min_pa=DEFAULT_MIN_PA, y0=DEFAULT_START_YEAR, y1=DEFAULT_END_YEAR, max_year=None):
    if max_year is not None:
        y1 = min(int(y1), int(max_year))
    # Build league mean by age across the window (filtering for min PA)
    sql = text(
        """
        SELECT player_age, AVG({stat}) AS mean_stat, COUNT(*) AS n
        FROM batting_stats
        WHERE year BETWEEN :y0 AND :y1
          AND {stat} IS NOT NULL
          AND (plate_appearances IS NULL OR plate_appearances >= :min_pa)
        GROUP BY player_age
        ORDER BY player_age
        """.format(stat=stat)
    )
    df = pd.read_sql(sql, engine, params={"y0": int(y0), "y1": int(y1), "min_pa": int(min_pa)})
    df["player_age"] = pd.to_numeric(df["player_age"], errors="coerce")
    df["mean_stat"] = pd.to_numeric(df["mean_stat"], errors="coerce")
    df = df.dropna(subset=["player_age", "mean_stat"]).sort_values("player_age")
    # Keep only sensible ages
    df = df[(df["player_age"] >= DEFAULT_AGE_MIN) & (df["player_age"] <= DEFAULT_AGE_MAX)]
    return df.reset_index(drop=True)


def _nearest_age_value(curve_df, age):
    """Return mean_stat for nearest age in curve_df to 'age'."""
    if curve_df.empty:
        return None
    idx = (curve_df["player_age"] - age).abs().idxmin()
    return float(curve_df.loc[idx, "mean_stat"])


def _ratios_vs_age(curve_df, age0, horizon, age_cap):
    """
    Build league ratios R[Δ] = mean(age0+Δ) / mean(age0) for Δ = 1..horizon,
    clamped at age_cap; hold last known ratio if we run out of ages.
    """
    if curve_df.empty:
        return [1.0] * int(horizon)

    base = _nearest_age_value(curve_df, age0)
    if base is None or abs(base) < EPS:
        # If base is missing or ~0, just return neutral factors (no change).
        return [1.0] * int(horizon)

    ratios = []
    last_ratio = 1.0
    for d in range(1, int(horizon) + 1):
        tgt_age = age0 + d
        if tgt_age > age_cap:
            ratios.append(last_ratio)
            continue
        val = _nearest_age_value(curve_df, tgt_age)
        if val is None:
            ratios.append(last_ratio)
        else:
            r = float(val) / float(base) if abs(base) >= EPS else 1.0
            last_ratio = r
            ratios.append(r)
    return ratios


def _encode_categorical(series, allowed):
    # one-hot as dict
    out = {}
    val = None
    if len(series) > 0:
        val = str(series.iloc[0]) if pd.notna(series.iloc[0]) else None
    for a in allowed:
        out["%s=%s" % (series.name, a)] = 1.0 if (val == a) else 0.0
    return out


def _standardize(df, cols):
    mu = df[cols].mean()
    sd = df[cols].std(ddof=0).replace(0, 1.0)
    z = (df[cols] - mu) / sd
    dfz = df.copy()
    for c in cols:
        dfz[c] = z[c]
    return dfz, mu, sd


def _candidate_snapshot_df(engine, stat, age0, min_pa, max_year=None):
    """
    Get one row per player around age0 (nearest age in {age0-1, age0, age0+1}).
    Pull features for KNN.
    """
    # Pull 3-age window to find the nearest season per player
    sql = text(
        """
        SELECT
            b.player_id,
            b.full_name,
            b.year,
            b.player_age,
            b.plate_appearances,
            b.batting_avg,
            b.on_base_percent,
            b.slg_percent,
            b.isolated_power,
            b.k_percent,
            b.bb_percent,
            b.sprint_speed,
            b.home_run,
            b.{stat} AS target_stat
        FROM batting_stats b
        WHERE b.{stat} IS NOT NULL
          AND b.player_age BETWEEN :a0m1 AND :a0p1
          AND b.year <= :max_year
          AND (b.plate_appearances IS NULL OR b.plate_appearances >= :min_pa)
        """.format(stat=stat)
    )
    df = pd.read_sql(
        sql, engine,
        params={
            "a0m1": int(age0) - 1,
            "a0p1": int(age0) + 1,
            "min_pa": int(min_pa),
            "max_year": _year_cap(max_year),
        },
    )
    if df.empty:
        return df

    # Attach profiles (height, weight, bats, throws, position)
    prof_cols = [
        "player_id", "height_in", "weight_lb", "bats", "throws",
        "primary_position", "primary_position_name", "is_active"
    ]
    try:
        prof = pd.read_sql("SELECT " + ",".join(prof_cols) + " FROM player_profiles", engine)
    except Exception:
        prof = pd.DataFrame(columns=prof_cols)
    if not prof.empty:
        df = df.merge(prof, on="player_id", how="left")

    # Pick per-player nearest age row
    df["age_diff"] = (df["player_age"] - age0).abs()
    df = df.sort_values(["player_id", "age_diff", "year"])
    df = df.groupby("player_id", as_index=False).first()

    return df


def _knn_comparables(engine, player_id, stat, base_age, min_pa, k, max_year=None):
    """
    Return candidate DF with distances and a separate row (base_row) for the target player.
    """
    cands = _candidate_snapshot_df(engine, stat, base_age, min_pa, max_year=max_year)
    if cands.empty:
        return cands, None

    # Identify base row (our player); if not present in candidates (e.g., PA filter),
    # fetch a fallback row at nearest age without PA filter.
    base = cands[cands["player_id"] == int(player_id)]
    if base.empty:
        # Fallback: pull latest row for player for this stat
        ph = _fetch_player_history(engine, player_id, stat, max_year=max_year)
        ph = ph.sort_values("year")
        if ph.empty:
            return cands.iloc[0:0], None
        base_row = ph.iloc[-1:].copy()
        base_row["target_stat"] = base_row["v"]
        base_row["plate_appearances"] = base_row.get("plate_appearances", np.nan)
        base_row["player_id"] = int(player_id)
        base_row["player_age"] = base_age
        base_row["full_name"] = None
        base = base_row
        # The history row lacks the candidate feature columns (batting_avg,
        # profile fields, ...). Add them as NaN so feature assembly below can
        # median-impute instead of raising KeyError.
        for c in cands.columns:
            if c not in base.columns:
                base[c] = np.nan
    else:
        base = base.iloc[:1].copy()

    # Assemble features (numerical + simple one-hots for bats/position)
    feature_cols = [
        "player_age", "plate_appearances", "batting_avg", "on_base_percent",
        "slg_percent", "isolated_power", "k_percent", "bb_percent",
        "sprint_speed", "home_run", "height_in", "weight_lb", "target_stat"
    ]

    # Ensure numeric, fill NaN with column medians later
    for c in feature_cols:
        if c in cands.columns:
            cands[c] = pd.to_numeric(cands[c], errors="coerce")
        if c in base.columns:
            base[c] = pd.to_numeric(base[c], errors="coerce")

    # Categorical encodings
    bats_allowed = ["R", "L", "S", None]
    pos_allowed = ["C","1B","2B","SS","3B","LF","CF","RF","DH", None]

    # Add one-hots
    for a in bats_allowed:
        key = "bats=%s" % a
        cands[key] = (cands["bats"].astype(str) == str(a)).astype(float)
        base[key] = (base["bats"].astype(str) == str(a)).astype(float) if "bats" in base.columns else 0.0

    for p in pos_allowed:
        key = "pos=%s" % p
        cands[key] = (cands["primary_position"].astype(str) == str(p)).astype(float)
        base[key] = (base["primary_position"].astype(str) == str(p)).astype(float) if "primary_position" in base.columns else 0.0

    # Final feature list
    feat_cols = [c for c in feature_cols if c in cands.columns] + \
                [c for c in cands.columns if c.startswith("bats=") or c.startswith("pos=")]

    # Median impute numeric NA
    med = cands[feat_cols].median(numeric_only=True)
    cands[feat_cols] = cands[feat_cols].fillna(med)
    base[feat_cols] = base[feat_cols].fillna(med)

    # Standardize
    cands_z, mu, sd = _standardize(cands, feat_cols)
    base_z = base.copy()
    for c in feat_cols:
        base_z[c] = (base[c] - mu.get(c, 0.0)) / (sd.get(c, 1.0) if sd.get(c, 1.0) != 0 else 1.0)

    # Distance
    diff = cands_z[feat_cols].values - base_z[feat_cols].values[0]
    dists = np.sqrt((diff ** 2).sum(axis=1))
    cands_z["dist"] = dists

    # Exclude self
    cands_z = cands_z[cands_z["player_id"] != int(player_id)]

    # Top-k
    cands_z = cands_z.sort_values("dist").head(int(k)).reset_index(drop=True)

    return cands_z, base.iloc[0].to_dict()


def _future_ratio_path_for_player(engine, pid, stat, base_age, horizon, age_cap, min_pa, max_year=None):
    """
    For one comparable player, build ratios at Δ=1..h where ratio = stat(age0+Δ)/stat(age0).
    Returns list of floats length=horizon (with None when not computable).

    NOTE on max_year: a comparable's "future" seasons are other players'
    real past seasons — but in a backtest they must still be capped at the
    training cutoff, otherwise the system peeks at seasons from the
    evaluation period.
    """
    # Pull the nearest row to base_age (to define the base)
    sql = text(
        """
        SELECT year, player_age, plate_appearances, {stat} AS v
        FROM batting_stats
        WHERE player_id = :pid
          AND {stat} IS NOT NULL
          AND year <= :max_year
        ORDER BY ABS(player_age - :age0), year
        LIMIT 1
        """.format(stat=stat)
    )
    base_df = pd.read_sql(
        sql, engine,
        params={"pid": int(pid), "age0": float(base_age), "max_year": _year_cap(max_year)},
    )
    if base_df.empty:
        return [None] * int(horizon), None, None
    base_row = base_df.iloc[0]
    base_val = float(base_row["v"]) if pd.notna(base_row["v"]) else None
    base_age_actual = int(base_row["player_age"]) if pd.notna(base_row["player_age"]) else None
    base_year = int(base_row["year"]) if pd.notna(base_row["year"]) else None

    if base_val is None or abs(base_val) < EPS:
        return [None] * int(horizon), base_year, base_age_actual

    # Now pull this player's future ages
    sql2 = text(
        """
        SELECT player_age, {stat} AS v
        FROM batting_stats
        WHERE player_id = :pid
          AND {stat} IS NOT NULL
          AND player_age BETWEEN :a0 AND :amax
          AND year <= :max_year
        """.format(stat=stat)
    )
    fut = pd.read_sql(
        sql2, engine,
        params={
            "pid": int(pid),
            "a0": int(base_age),
            "amax": int(age_cap),
            "max_year": _year_cap(max_year),
        },
    )
    fut["player_age"] = pd.to_numeric(fut["player_age"], errors="coerce")
    fut["v"] = pd.to_numeric(fut["v"], errors="coerce")
    fut = fut.dropna(subset=["player_age", "v"])

    # Build ratios aligned to Δ
    ratios = []
    for d in range(1, int(horizon) + 1):
        age_t = base_age + d
        row = fut[(fut["player_age"] - age_t).abs() <= 0.51]  # accept nearest integer age
        if row.empty:
            ratios.append(None)
        else:
            val = float(row.iloc[0]["v"])
            r = val / base_val if abs(base_val) >= EPS else None
            ratios.append(r)
    return ratios, base_year, base_age_actual


def _aggregate_comparable_paths(engine, comp_df, stat, base_age, horizon, age_cap, min_pa, max_year=None):
    """
    For all comparables, compute their ratio paths and aggregate p10/mean/p90 per Δ.
    """
    if comp_df.empty:
        return {
            "mean": [None] * int(horizon),
            "p10":  [None] * int(horizon),
            "p90":  [None] * int(horizon),
            "paths": [],
            "count": 0,
        }

    paths = []
    for _, row in comp_df.iterrows():
        rid = int(row["player_id"])
        r, _, _ = _future_ratio_path_for_player(
            engine, rid, stat, base_age, horizon, age_cap, min_pa, max_year=max_year
        )
        paths.append(r)

    # transpose-like aggregation
    agg_mean, agg_p10, agg_p90 = [], [], []
    for i in range(int(horizon)):
        vals = [p[i] for p in paths if p[i] is not None and np.isfinite(p[i])]
        if not vals:
            agg_mean.append(None)
            agg_p10.append(None)
            agg_p90.append(None)
        else:
            v = np.array(vals, dtype=float)
            agg_mean.append(float(np.mean(v)))
            agg_p10.append(float(np.percentile(v, 10)))
            agg_p90.append(float(np.percentile(v, 90)))

    return {
        "mean": agg_mean,
        "p10": agg_p10,
        "p90": agg_p90,
        "paths": paths,
        "count": int(len(paths)),
    }


def _recent_trend_multiplier(hist_df, lookback, cap=0.10):
    """
    Compute a gentle trend multiplier based on last <= lookback points:
    - Fit line on (year, stat). Convert slope to %/year relative to last value.
    - Return a small adjustment per-step: (1 + clamp(β * slope_pct, ±cap)) where β=0.15.
    We apply this once overall (not compounded per Δ).
    """
    if hist_df.empty:
        return 1.0

    df = hist_df.dropna(subset=["v"]).sort_values("year")
    if df.empty:
        return 1.0

    df = df.tail(int(lookback))
    if df.shape[0] < 2:
        return 1.0

    x = df["year"].values.astype(float)
    y = df["v"].values.astype(float)
    # simple linear regression
    A = np.vstack([x, np.ones_like(x)]).T
    m, b = np.linalg.lstsq(A, y, rcond=None)[0]
    last_v = y[-1]
    if abs(last_v) < EPS:
        return 1.0
    slope_pct = m / abs(last_v)
    beta = 0.15
    adj = 1.0 + max(-cap, min(cap, beta * slope_pct))
    return float(adj)


def project_stat_aging_knn(
    db,
    db_engine,
    player_id,
    stat,
    horizon,
    lookback,
    k=25,
    age_cap=42,
    alpha_comps=0.5,
    min_pa=DEFAULT_MIN_PA,
    max_year=None,
):
    """
    Implements your write-up:
      1) League aging curve ratios
      2) Recent player trend direction (gentle multiplier)
      3) KNN comparables ratio paths
      4) Blend league & comps; output mean + p10/p90 bands over next N years

    `max_year` caps every query at a training cutoff (year <= max_year) so
    the backtest harness can evaluate this system without future leakage.
    Default None = use all available data (production behavior).

    Returns:
      series (list of Nivo line series)
      meta (dict)
    """
    # Validate stat column
    stat = _ensure_stat_column(db_engine, stat)

    # Player history to get baseline (latest) age & value
    hist = _fetch_player_history(db_engine, player_id, stat, max_year=max_year)
    if hist.empty:
        return [
            {"id": "Projected " + stat, "data": []}
        ], {
            "warnings": ["no_history"],
            "stat": stat,
        }

    hist = hist.sort_values("year")
    base_row = hist.iloc[-1]
    base_year = int(base_row["year"])
    base_age = int(base_row["player_age"]) if pd.notna(base_row["player_age"]) else None
    base_val = float(base_row["v"]) if pd.notna(base_row["v"]) else None

    # Fallback for missing age/value
    if base_age is None:
        # try median age in hist
        try:
            base_age = int(round(hist["player_age"].dropna().median()))
        except Exception:
            base_age = 28
    if base_val is None or not np.isfinite(base_val):
        # use trailing mean as base
        vals = hist["v"].dropna().tail(int(max(1, lookback))).values
        base_val = float(np.mean(vals)) if len(vals) else 0.0

    # Clamp horizon by age_cap
    max_h = int(horizon)
    if base_age + max_h > int(age_cap):
        max_h = max(0, int(age_cap) - int(base_age))
    if max_h <= 0:
        return [
            {"id": "Projected " + stat, "data": []}
        ], {
            "warnings": ["age_cap_reached"],
            "stat": stat,
            "baseline_age": base_age,
            "age_cap": int(age_cap),
        }

    # 1) League aging curve
    curve = _league_age_curve(db_engine, stat, min_pa=min_pa,
                              y0=DEFAULT_START_YEAR, y1=DEFAULT_END_YEAR,
                              max_year=max_year)
    league_ratios = _ratios_vs_age(curve, base_age, max_h, age_cap)

    # 2) Recent trend (gentle, one-shot)
    trend_mult = _recent_trend_multiplier(hist, lookback)

    # 3) KNN comps
    comps_df, base_snapshot = _knn_comparables(
        db_engine, player_id, stat, base_age, min_pa, k, max_year=max_year
    )
    comps_agg = _aggregate_comparable_paths(
        db_engine, comps_df, stat, base_age, max_h, age_cap, min_pa, max_year=max_year
    )

    # Build blended ratios & bands
    mean_blend, p10_blend, p90_blend = [], [], []
    for i in range(max_h):
        lr = league_ratios[i] if i < len(league_ratios) else 1.0
        cr_mean = comps_agg["mean"][i]
        cr_p10  = comps_agg["p10"][i]
        cr_p90  = comps_agg["p90"][i]

        if cr_mean is None or not np.isfinite(cr_mean):
            m = lr
        else:
            m = (1.0 - float(alpha_comps)) * lr + float(alpha_comps) * float(cr_mean)

        if cr_p10 is None or not np.isfinite(cr_p10):
            lo = lr * 0.90  # simple ±10% guard when no comps
        else:
            lo = (1.0 - float(alpha_comps)) * lr + float(alpha_comps) * float(cr_p10)

        if cr_p90 is None or not np.isfinite(cr_p90):
            hi = lr * 1.10
        else:
            hi = (1.0 - float(alpha_comps)) * lr + float(alpha_comps) * float(cr_p90)

        mean_blend.append(m)
        p10_blend.append(lo)
        p90_blend.append(hi)

    # Apply to base value + trend multiplier
    years = [base_year + d for d in range(1, max_h + 1)]
    proj = [float(base_val) * float(trend_mult) * float(r) for r in mean_blend]
    lo   = [float(base_val) * float(trend_mult) * float(r) for r in p10_blend]
    hi   = [float(base_val) * float(trend_mult) * float(r) for r in p90_blend]

    # Series for Nivo line
    series = [
        {"id": "Projected " + stat, "data": [{"x": years[i], "y": float(proj[i])} for i in range(len(years))]},
        {"id": "p10", "data": [{"x": years[i], "y": float(lo[i])}   for i in range(len(years))]},
        {"id": "p90", "data": [{"x": years[i], "y": float(hi[i])}   for i in range(len(years))]},
    ]

    meta = {
        "method": "aging_knn",
        "stat": stat,
        "baseline_year": base_year,
        "baseline_age": base_age,
        "base_value": float(base_val),
        "trend_multiplier": float(trend_mult),
        "league_curve_count": int(curve.shape[0]) if curve is not None else 0,
        "k_used": int(min(k, len(comps_df))) if comps_df is not None else 0,
        "alpha_comps": float(alpha_comps),
        "min_pa": int(min_pa),
        "age_cap": int(age_cap),
        "bands": {"p10": "lower", "p90": "upper"},
    }
    if max_year is not None:
        meta["max_year"] = int(max_year)

    return series, meta
