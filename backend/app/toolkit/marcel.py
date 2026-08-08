# backend/app/toolkit/marcel.py
#
# Classic Marcel projections for hitters (Tango's "the Marcel the Monkey
# Forecasting System"): a deliberately simple, hard-to-beat baseline.
#
#   1. Recency-weight the last three seasons 5/4/3 (most recent first).
#   2. Regress toward the league mean by adding ~1200 PA of league-average
#      "ballast" to the weighted sample.
#   3. Nudge for age: improve toward the peak below age 29, decline above it.
#   4. Project playing time as 0.5*PA[t-1] + 0.1*PA[t-2] + 200.
#
# Rate stats (e.g. woba) are projected as rates; counting stats (e.g.
# home_run) are converted to a per-PA rate, projected, then scaled back to
# the projected PA.
#
# The math lives in pure-pandas functions over a "panel" DataFrame
# (player_id, full_name, year, age, pa, <stat>) so it is unit-testable
# without a database; `load_panel`/`marcel_project` are the thin DB entry
# points.

import numpy as np
import pandas as pd

from ..db.models import BattingStats
from .stats import latest_year, resolve_stat_column

# t-1, t-2, t-3 season weights
MARCEL_WEIGHTS = (5.0, 4.0, 3.0)
# PA of league-average ballast mixed into every projection
BALLAST_PA = 1200.0
# Projected PA = 0.5*PA[t-1] + 0.1*PA[t-2] + PA_CONSTANT
PA_WEIGHTS = (0.5, 0.1)
PA_CONSTANT = 200.0
# Age adjustment: +0.6%/yr under peak, -0.3%/yr over peak
PEAK_AGE = 29
AGE_IMPROVE_PER_YEAR = 0.006
AGE_DECLINE_PER_YEAR = 0.003

# Stats whose column stores a rate (numerator = value * PA). Anything not
# listed here is treated as a counting stat (numerator = value).
RATE_STATS = {
    "woba",
    "batting_avg",
    "on_base_percent",
    "slg_percent",
    "on_base_plus_slg",
    "isolated_power",
    "xwoba",
    "xba",
}

PANEL_BASE_COLS = ["player_id", "full_name", "year", "age", "pa"]


def stat_kind(stat):
    return "rate" if stat in RATE_STATS else "counting"


def load_panel(db, stats):
    """One bulk query -> panel DataFrame with PANEL_BASE_COLS + one column
    per requested stat. Column resolution goes through the toolkit's safe
    resolver (identifier-whitelisted)."""
    stats = [s for s in dict.fromkeys(stats)]  # dedupe, keep order
    sel = [
        BattingStats.player_id,
        BattingStats.full_name,
        BattingStats.year,
        BattingStats.player_age,
        BattingStats.plate_appearances,
    ]
    sel += [resolve_stat_column(db, s).label(s) for s in stats]
    rows = db.query(*sel).all()
    df = pd.DataFrame(rows, columns=PANEL_BASE_COLS + stats)
    for c in ["player_id", "year", "age", "pa"] + stats:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["player_id", "year"])
    df["player_id"] = df["player_id"].astype(int)
    df["year"] = df["year"].astype(int)
    df["pa"] = df["pa"].fillna(0.0)
    return df


def _numerators(panel, stat):
    """Counting numerator X per row: value itself for counting stats,
    value * PA for rate stats. Rows with a null stat contribute nothing
    (X and PA masked to 0)."""
    valid = panel[stat].notna() & (panel["pa"] > 0)
    if stat_kind(stat) == "rate":
        x = (panel[stat] * panel["pa"]).where(valid, 0.0)
    else:
        x = panel[stat].where(valid, 0.0)
    pa = panel["pa"].where(valid, 0.0)
    return x.astype(float), pa.astype(float)


def league_rates(panel, stat):
    """PA-weighted league rate per season: sum(X) / sum(PA) over rows where
    the stat is present. Returns {year: rate}."""
    x, pa = _numerators(panel, stat)
    df = pd.DataFrame({"year": panel["year"], "x": x, "pa": pa})
    g = df.groupby("year").sum()
    g = g[g["pa"] > 0]
    return (g["x"] / g["pa"]).to_dict()


def weighted_league_rate(panel, stat, target_year, weights=MARCEL_WEIGHTS):
    """League rate for the ballast: league totals of the same three seasons,
    weighted 5/4/3. Seasons absent from the panel simply drop out."""
    x, pa = _numerators(panel, stat)
    df = pd.DataFrame({"year": panel["year"], "x": x, "pa": pa})
    totals = df.groupby("year").sum()
    num = den = 0.0
    for lag, w in enumerate(weights, start=1):
        season = target_year - lag
        if season in totals.index:
            num += w * float(totals.loc[season, "x"])
            den += w * float(totals.loc[season, "pa"])
    if den <= 0:
        return None
    return num / den


def age_multiplier(age_at_target):
    if age_at_target is None or not np.isfinite(age_at_target):
        return 1.0
    delta = PEAK_AGE - float(age_at_target)
    per_year = AGE_IMPROVE_PER_YEAR if delta > 0 else AGE_DECLINE_PER_YEAR
    return 1.0 + delta * per_year


def marcel_project_all(panel, stat, target_year, weights=MARCEL_WEIGHTS,
                       ballast_pa=BALLAST_PA):
    """Vectorized Marcel for every player with at least one season in the
    3-year window before `target_year`.

    Only panel rows with year < target_year are ever read (no leakage).
    Returns a DataFrame indexed by player_id with columns:
      proj_rate, proj_pa, proj_value, age_mult, weighted_pa, n_seasons,
      age_at_target, full_name
    """
    hist = panel[panel["year"] < target_year]
    lg_rate = weighted_league_rate(hist, stat, target_year, weights)
    if lg_rate is None:
        return pd.DataFrame(
            columns=["proj_rate", "proj_pa", "proj_value", "age_mult",
                     "weighted_pa", "n_seasons", "age_at_target", "full_name"]
        )

    x, pa = _numerators(hist, stat)
    df = pd.DataFrame({
        "player_id": hist["player_id"],
        "year": hist["year"],
        "x": x,
        "pa": pa,
        "raw_pa": hist["pa"].astype(float),
    })

    # Weighted numerator / denominator over the 3-season window.
    num = None
    den = None
    proj_pa = None
    n_seasons = None
    for lag, w in enumerate(weights, start=1):
        season = df[df["year"] == target_year - lag].set_index("player_id")
        s_num = season["x"] * w
        s_den = season["pa"] * w
        s_cnt = (season["pa"] > 0).astype(int)
        num = s_num if num is None else num.add(s_num, fill_value=0.0)
        den = s_den if den is None else den.add(s_den, fill_value=0.0)
        n_seasons = s_cnt if n_seasons is None else n_seasons.add(s_cnt, fill_value=0)
        if lag <= len(PA_WEIGHTS):
            s_pa = season["raw_pa"] * PA_WEIGHTS[lag - 1]
            proj_pa = s_pa if proj_pa is None else proj_pa.add(s_pa, fill_value=0.0)

    out = pd.DataFrame({"weighted_pa": den, "num": num, "n_seasons": n_seasons})
    out = out[out["weighted_pa"] > 0]
    if out.empty:
        return pd.DataFrame(
            columns=["proj_rate", "proj_pa", "proj_value", "age_mult",
                     "weighted_pa", "n_seasons", "age_at_target", "full_name"]
        )
    out["proj_pa"] = (proj_pa.reindex(out.index).fillna(0.0)
                      if proj_pa is not None else 0.0) + PA_CONSTANT

    # Regression to the league mean: ballast_pa of league-average production.
    out["pre_age_rate"] = (
        (out["num"] + ballast_pa * lg_rate) / (out["weighted_pa"] + ballast_pa)
    )

    # Age at target = age at most recent observed season + elapsed years.
    latest = (
        hist[hist["age"].notna()]
        .sort_values("year")
        .groupby("player_id")
        .last()[["year", "age"]]
    )
    age_at_target = latest["age"] + (target_year - latest["year"])
    out["age_at_target"] = age_at_target.reindex(out.index)
    out["age_mult"] = out["age_at_target"].map(age_multiplier)

    out["proj_rate"] = (out["pre_age_rate"] * out["age_mult"]).clip(lower=0.0)
    if stat_kind(stat) == "rate":
        out["proj_value"] = out["proj_rate"]
    else:
        out["proj_value"] = out["proj_rate"] * out["proj_pa"]

    names = (
        panel[panel["full_name"].notna()]
        .sort_values("year")
        .groupby("player_id")["full_name"]
        .last()
    )
    out["full_name"] = names.reindex(out.index)
    out["league_rate"] = lg_rate
    return out[["proj_rate", "proj_pa", "proj_value", "age_mult", "weighted_pa",
                "n_seasons", "age_at_target", "full_name", "league_rate"]]


def marcel_project(db, player_id, stat, target_year=None):
    """Single-player Marcel projection. Returns a dict with the projected
    value and its components, or None if the player has no usable history
    in the 3-season window."""
    panel = load_panel(db, [stat])
    if target_year is None:
        target_year = int(latest_year(db)) + 1
    all_proj = marcel_project_all(panel, stat, int(target_year))
    pid = int(player_id)
    if pid not in all_proj.index:
        return None
    row = all_proj.loc[pid]
    return {
        "stat": stat,
        "kind": stat_kind(stat),
        "target_year": int(target_year),
        "proj_value": float(row["proj_value"]),
        "proj_rate": float(row["proj_rate"]),
        "proj_pa": float(row["proj_pa"]),
        "age_mult": float(row["age_mult"]),
        "age_at_target": (
            None if pd.isna(row["age_at_target"]) else float(row["age_at_target"])
        ),
        "weighted_pa": float(row["weighted_pa"]),
        "n_seasons": int(row["n_seasons"]),
        "league_rate": float(row["league_rate"]),
        "weights": list(MARCEL_WEIGHTS),
        "ballast_pa": float(BALLAST_PA),
    }
