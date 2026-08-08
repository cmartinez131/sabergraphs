# backend/app/toolkit/battracking.py
#
# Toolkit functions over the Statcast bat-tracking mart
# (mart_bat_tracking_season, 2024+). Same contract as the rest of the
# toolkit: functions return the canonical chart payload
# {chart_type, series, meta} and never interpolate user input into SQL —
# stat selection goes through a fixed column map, names are bound
# parameters.

import numpy as np
from sqlalchemy import func, and_

from ..db.models import BattingStats, MartBatTrackingSeason as MBT
from .stats import label_map_for, resolve_stat_column, stat_label

DEFAULT_MIN_SWINGS = 100

# The only columns callers may rank/plot by — identifier allowlist.
TRACKING_STATS = {
    "avg_bat_speed": MBT.avg_bat_speed,
    "fast_swing_rate": MBT.fast_swing_rate,
    "avg_swing_length": MBT.avg_swing_length,
    "squared_up_rate": MBT.squared_up_rate,
    "blast_rate": MBT.blast_rate,
    "whiff_rate": MBT.whiff_rate,
    "batter_run_value": MBT.batter_run_value,
    "competitive_swings": MBT.competitive_swings,
    "swords": MBT.swords,
}

# Radar spokes for the skill profile: higher = better on every axis so the
# polygon area reads as skill. Contact is displayed as 1 - whiff_rate.
PROFILE_STATS = [
    "avg_bat_speed",
    "fast_swing_rate",
    "squared_up_rate",
    "blast_rate",
    "contact_rate_tracking",
]


def _tracking_col(stat):
    col = TRACKING_STATS.get(stat)
    if col is None:
        raise ValueError(
            f"Unknown bat-tracking stat: {stat}. "
            f"Choose from {sorted(TRACKING_STATS)}."
        )
    return col


def latest_tracking_season(db):
    s = db.query(func.max(MBT.season)).scalar()
    return int(s) if s else None


def _resolve_tracking_player(db, player, season, min_swings=0):
    """Resolve a player id or name fragment to one mart row for `season`."""
    q = db.query(MBT).filter(MBT.season == season)
    if isinstance(player, int) or (isinstance(player, str) and player.isdigit()):
        q = q.filter(MBT.batter_mlbam == int(player))
    else:
        q = q.filter(MBT.full_name.ilike(f"%{player}%"))
    rows = q.order_by(MBT.competitive_swings.desc().nullslast()).limit(2).all()
    if not rows:
        return None
    return rows[0]


def bat_speed_profile(db, player, season=None, min_swings=50):
    """Bat-speed/swing skill profile for one player-season vs the qualified
    league -> radar of percentile ranks (0-100), league median at 50."""
    if season is None:
        season = latest_tracking_season(db)
    if season is None:
        return {"chart_type": "radar", "series": [],
                "meta": {"warnings": ["no_bat_tracking_data"]}}

    row = _resolve_tracking_player(db, player, season)
    if row is None:
        return {"chart_type": "radar", "series": [],
                "meta": {"warnings": ["player_not_found"], "season": int(season)}}

    qualified = (
        db.query(MBT)
        .filter(MBT.season == season, MBT.competitive_swings >= int(min_swings))
        .all()
    )

    def spoke_values(r):
        return {
            "avg_bat_speed": r.avg_bat_speed,
            "fast_swing_rate": r.fast_swing_rate,
            "squared_up_rate": r.squared_up_rate,
            "blast_rate": r.blast_rate,
            "contact_rate_tracking": (
                None if r.whiff_rate is None else 1.0 - float(r.whiff_rate)
            ),
        }

    league = [spoke_values(r) for r in qualified]
    mine = spoke_values(row)

    series = []
    raw_values = {}
    for stat in PROFILE_STATS:
        pool = np.array([v[stat] for v in league if v[stat] is not None], dtype=float)
        val = mine[stat]
        if val is None or pool.size == 0:
            pct = None
        else:
            pct = float(100.0 * np.mean(pool <= float(val)))
        spoke = {"stat": stat, "League median": 50.0}
        spoke[row.full_name or str(row.batter_mlbam)] = pct if pct is not None else 0.0
        series.append(spoke)
        raw_values[stat] = None if val is None else float(val)

    label_map = {
        "avg_bat_speed": stat_label("avg_bat_speed"),
        "fast_swing_rate": stat_label("fast_swing_rate"),
        "squared_up_rate": stat_label("squared_up_rate"),
        "blast_rate": stat_label("blast_rate"),
        "contact_rate_tracking": "Contact Rate (1 − whiff)",
    }
    meta = {
        "title": f"Bat-Tracking Skill Profile — {row.full_name} ({season})",
        "label_map": label_map,
        "unit": "percentile (0-100) among qualified swingers",
        "season": int(season),
        "min_swings": int(min_swings),
        "qualified_pool": len(qualified),
        "competitive_swings": (
            None if row.competitive_swings is None else int(row.competitive_swings)
        ),
        "raw_values": raw_values,
        "note": "Bat-tracking data exists for 2024+ seasons only.",
    }
    return {"chart_type": "radar", "series": series, "meta": meta}


def blast_leaderboard(db, season=None, stat="blast_rate", limit=10,
                      min_swings=DEFAULT_MIN_SWINGS, order="desc"):
    """Leaderboard over a bat-tracking stat with a minimum-swing qualifier
    -> bar chart."""
    col = _tracking_col(stat)
    if season is None:
        season = latest_tracking_season(db)
    if season is None:
        return {"chart_type": "bar", "series": [{"id": stat, "data": []}],
                "meta": {"warnings": ["no_bat_tracking_data"]}}

    direction = col.asc() if str(order).lower() == "asc" else col.desc()
    rows = (
        db.query(MBT.full_name, col.label("v"), MBT.competitive_swings)
        .filter(
            MBT.season == season,
            MBT.competitive_swings >= int(min_swings),
            col.isnot(None),
        )
        .order_by(direction)
        .limit(int(limit))
        .all()
    )
    data = [{"x": name, "y": float(v)} for (name, v, _swings) in rows]
    dir_word = "Lowest" if str(order).lower() == "asc" else "Top"
    meta = {
        "title": f"{dir_word} {int(limit)} {stat_label(stat)} — {season} "
                 f"(min {int(min_swings)} competitive swings)",
        "label_map": {stat: stat_label(stat)},
        "season": int(season),
        "min_swings": int(min_swings),
        "qualifier": {"column": "competitive_swings", "min": int(min_swings)},
        "note": "Bat-tracking data exists for 2024+ seasons only.",
    }
    return {"chart_type": "bar", "series": [{"id": stat, "data": data}], "meta": meta}


def bat_speed_vs_production(db, season=None, production_stat="woba",
                            min_swings=DEFAULT_MIN_SWINGS, bin_width=1.0):
    """League-wide relationship between average bat speed and a production
    stat: players are binned by bat speed (bin_width mph) and the mean of
    the production stat is plotted per bin -> line chart. Correlation over
    the unbinned player points is reported in meta."""
    prod_col = resolve_stat_column(db, production_stat)
    if season is None:
        season = latest_tracking_season(db)
    if season is None:
        return {"chart_type": "line", "series": [{"id": production_stat, "data": []}],
                "meta": {"warnings": ["no_bat_tracking_data"]}}

    rows = (
        db.query(MBT.avg_bat_speed.label("speed"), prod_col.label("prod"))
        .select_from(MBT)
        .join(
            BattingStats,
            and_(
                BattingStats.player_id == MBT.batter_mlbam,
                BattingStats.year == MBT.season,
            ),
        )
        .filter(
            MBT.season == season,
            MBT.competitive_swings >= int(min_swings),
            MBT.avg_bat_speed.isnot(None),
            prod_col.isnot(None),
        )
        .all()
    )
    pts = [(float(s), float(p)) for (s, p) in rows]
    if len(pts) < 3:
        return {
            "chart_type": "line",
            "series": [{"id": production_stat, "data": []}],
            "meta": {"warnings": ["not_enough_players"], "season": int(season)},
        }

    speeds = np.array([p[0] for p in pts])
    prods = np.array([p[1] for p in pts])
    corr = float(np.corrcoef(speeds, prods)[0, 1])

    lo = np.floor(speeds.min() / bin_width) * bin_width
    # +bin_width past the floored max so a value sitting exactly on the top
    # edge still lands inside the final half-open bin [edge, edge+width).
    hi = np.floor(speeds.max() / bin_width) * bin_width + bin_width
    edges = np.arange(lo, hi + bin_width / 2.0, bin_width)
    data = []
    for i in range(len(edges) - 1):
        mask = (speeds >= edges[i]) & (speeds < edges[i + 1])
        if int(mask.sum()) == 0:
            continue
        center = float(edges[i] + bin_width / 2.0)
        data.append({
            "x": round(center, 2),
            "y": float(prods[mask].mean()),
            "n": int(mask.sum()),
        })

    meta = {
        "title": f"{stat_label(production_stat)} by Avg Bat Speed — {season}",
        "label_map": {
            **label_map_for([production_stat]),
            "avg_bat_speed": stat_label("avg_bat_speed"),
        },
        "x_label": stat_label("avg_bat_speed"),
        "y_label": stat_label(production_stat),
        "season": int(season),
        "min_swings": int(min_swings),
        "bin_width_mph": float(bin_width),
        "players": len(pts),
        "pearson_r": corr,
        "note": "Each point is the mean production of players in a "
                f"{bin_width:.0f}-mph bat-speed bin; n per bin in point meta.",
    }
    series = [{"id": stat_label(production_stat), "data": data}]
    return {"chart_type": "line", "series": series, "meta": meta}
