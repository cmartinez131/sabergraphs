# backend/app/toolkit/stats.py
from collections import defaultdict
import numpy as np
import pandas as pd
from sqlalchemy import func, desc, asc, inspect, literal_column

from ..db.models import BattingStats

# ---------- canonical labels (backend source of truth) ----------
STAT_LABELS = {
    "woba": "wOBA",
    "on_base_plus_slg": "OPS",
    "on_base_percent": "On-Base %",
    "slg_percent": "Slugging %",
    "isolated_power": "ISO",
    "batting_avg": "Batting Average",
    "home_run": "Home Runs",
    "r_total_stolen_base": "Stolen Bases",
    "bb_percent": "Walk %",
    "k_percent": "Strikeout %",
    "barrel_batted_rate": "Barrel %",
    "sprint_speed": "Sprint Speed",
    "plate_appearances": "Plate Appearances",
    "player_age": "Age",
    "meatball_percent": "Meatball %",
    "meatball_swing_percent": "Meatball Swing %",
    "b_rbi": "RBIs",  # important for RBI legend/labels
}

# ---- Rate stats that should apply MLB qualification (3.1 PA per scheduled game) ----
RATE_QUAL_STATS = {
    "batting_avg",
    "on_base_percent",
    "slg_percent",
    "on_base_plus_slg",
    "woba",
    "isolated_power",
    # You can extend this set if you want other percentage/ratio stats qualified by PA.
}


def stat_label(slug: str) -> str:
    if not isinstance(slug, str) or not slug:
        return str(slug)
    if slug in STAT_LABELS:
        return STAT_LABELS[slug]
    # simple fallback: snake_case -> Title Case
    parts = [p for p in slug.split("_") if p]
    if not parts:
        return slug
    base = " ".join(w.capitalize() for w in parts)
    # small polish: convert trailing "Percent" to "%"
    if base.endswith(" Percent"):
        base = base[: -len(" Percent")] + " %"
    return base


def label_map_for(stats) -> dict:
    out = {}
    for s in (stats or []):
        out[str(s)] = stat_label(str(s))
    return out


# ------------- helpers: reflection + safe column access -------------

def table_columns(db):
    insp = inspect(db.bind)
    cols = insp.get_columns(BattingStats.__tablename__)
    return {c["name"] for c in cols}


def is_safe_token(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    for ch in s:
        if not (ch.isalnum() or ch == "_"):
            return False
    return True


def resolve_stat_column(db, stat: str):
    if not is_safe_token(stat):
        raise ValueError(f"Illegal stat name: {stat}")
    col = getattr(BattingStats, stat, None)
    if col is not None:
        return col
    if stat in table_columns(db):
        return literal_column(stat)
    raise ValueError(f"Unknown/unsupported stat: {stat}")


def col_exists(db, name):
    if getattr(BattingStats, name, None) is not None:
        return True
    return name in table_columns(db)


def latest_year(db):
    return db.query(func.max(BattingStats.year)).scalar() or 2025


# ---------- PA column + MLB qualification helpers ----------

def _pa_column_name(db) -> str or None:
    """
    Return the actual PA column name that exists in the DB: prefer 'plate_appearances',
    fall back to 'pa'. Return None if neither exists.
    """
    cols = table_columns(db)
    if "plate_appearances" in cols:
        return "plate_appearances"
    if "pa" in cols:
        return "pa"
    # In case reflection is unavailable for some reason, fall back to model attr check.
    if getattr(BattingStats, "plate_appearances", None) is not None:
        return "plate_appearances"
    return None


# Scheduled MLB games by season (used for qualification threshold).
# Your dataset is 2015–2025; the only atypical season here is 2020 (60 games).
_GAMES_BY_YEAR = {
    2020: 60,
}
_DEFAULT_SCHEDULED_GAMES = 162  # modern MLB regular seasons


def _scheduled_games(year: int) -> int:
    return int(_GAMES_BY_YEAR.get(int(year), _DEFAULT_SCHEDULED_GAMES))


def _qualified_pa_threshold(year: int) -> int:
    """
    MLB qualifier for batting rate stat titles: 3.1 PA per scheduled game,
    rounded to the nearest whole PA (nearest integer).
    e.g. 162g -> round(3.1*162) = 502; 60g (2020) -> 186.
    """
    games = _scheduled_games(year)
    return int(round(3.1 * games))


def _auto_min_pa_if_rate_stat(stat: str, year: int, min_pa: int or None) -> int or None:
    """
    If stat is a rate stat AND caller did not specify min_pa, return the MLB-qualified threshold.
    Otherwise, return the provided min_pa unchanged.
    """
    if min_pa is None and stat in RATE_QUAL_STATS and year is not None:
        return _qualified_pa_threshold(int(year))
    return min_pa


# ---------- helper: name/id lookups ----------

def name_for_id(db, pid):
    row = (
        db.query(BattingStats.full_name)
        .filter(BattingStats.player_id == pid)
        .order_by(BattingStats.year.desc())
        .first()
    )
    return row[0] if row else str(pid)


def names_for_ids(db, ids):
    return {pid: name_for_id(db, pid) for pid in ids}


# ----------------- compare (bar/line) -----------------

def compare_players_by_season(db, player_ids, stat, year=None, start_year=None, end_year=None):
    col = resolve_stat_column(db, stat)
    if year and (start_year or end_year):
        raise ValueError("Provide either 'year' OR 'start_year'+'end_year', not both.")

    is_single_year = bool(year)
    meta = {"warnings": [], "label_map": label_map_for([stat])}
    names_map = names_for_ids(db, player_ids)
    names_in_order = [names_map.get(pid, str(pid)) for pid in player_ids]

    q = (
        db.query(BattingStats.player_id, BattingStats.full_name, BattingStats.year, col.label("v"))
        .filter(BattingStats.player_id.in_(player_ids))
    )

    if is_single_year:
        q = q.filter(BattingStats.year == year)
    else:
        if not start_year or not end_year:
            latest = latest_year(db)
            start_year, end_year = latest - 4, latest
        q = q.filter(BattingStats.year.between(start_year, end_year))

    rows = q.order_by(BattingStats.full_name, BattingStats.year).all()

    if is_single_year:
        returned_pids = {pid for (pid, _nm, _y, v) in rows if v is not None}
        missing_pids = [pid for pid in player_ids if pid not in returned_pids]

        for pid in missing_pids:
            had_row = (
                db.query(BattingStats.player_id)
                .filter(BattingStats.player_id == pid, BattingStats.year == year)
                .first()
            )
            reason = "no row for that year" if not had_row else f"'{stat}' is null for that year"
            meta["warnings"].append(
                {
                    "type": "missing_value",
                    "player_id": pid,
                    "player": names_map.get(pid, str(pid)),
                    "year": year,
                    "stat": stat,
                    "reason": reason,
                }
            )

        data = [{"x": name, "y": float(v)} for (_pid, name, _y, v) in rows if v is not None]
        meta["title"] = f"{' vs '.join(names_in_order)} — {stat_label(stat)} ({year})"
        return {"chart_type": "bar", "series": [{"id": stat, "data": data}], "meta": meta}

    by_player = defaultdict(list)
    seen_pid_with_data = set()
    for pid, name, y, v in rows:
        if v is not None:
            by_player[name].append({"x": int(y), "y": float(v)})
            seen_pid_with_data.add(pid)

    for pid in player_ids:
        if pid not in seen_pid_with_data:
            meta["warnings"].append(
                {
                    "type": "no_data_in_range",
                    "player_id": pid,
                    "player": names_map.get(pid, str(pid)),
                    "start_year": start_year,
                    "end_year": end_year,
                    "stat": stat,
                }
            )

    series = [{"id": name, "data": pts} for name, pts in by_player.items()]
    meta["x_years"] = list(range(int(start_year), int(end_year) + 1))
    meta["title"] = f"{' vs '.join(names_in_order)} — {stat_label(stat)} ({start_year}–{end_year})"
    return {"chart_type": "line", "series": series, "meta": meta}


# ----------------- 1) leaderboard (bar) -----------------

def leaderboard(db, stat, year=None, limit=10, min_pa=None, order="desc"):
    col = resolve_stat_column(db, stat)
    year = year or latest_year(db)

    # Auto-qualify PA if this is a rate stat and min_pa not provided
    effective_min_pa = _auto_min_pa_if_rate_stat(stat, year, min_pa)
    pa_name = _pa_column_name(db)
    pa_col = resolve_stat_column(db, pa_name) if (pa_name and effective_min_pa) else None

    q = db.query(BattingStats.player_id, BattingStats.full_name, col.label("v")).filter(BattingStats.year == year)
    if pa_col is not None:
        q = q.filter(pa_col >= int(effective_min_pa))

    q = q.order_by(desc("v") if str(order).lower() != "asc" else asc("v")).limit(int(limit))
    rows = q.all()
    data = [{"x": name, "y": float(v)} for _pid, name, v in rows if v is not None]

    dir_label = "Top" if str(order).lower() != "asc" else "Bottom"
    title = f"{dir_label} {int(limit)} {stat_label(stat)} — {year}"
    meta = {"title": title, "label_map": label_map_for([stat])}

    if pa_col is not None and effective_min_pa:
        meta["title"] = title + " (qualified)"
        meta["qualifier"] = {
            "min_pa": int(effective_min_pa),
            "rule": "MLB 3.1 PA per scheduled game (Rule 9.22)",
            "scheduled_games": _scheduled_games(year),
            "pa_column": pa_name,
        }
    elif stat in RATE_QUAL_STATS and effective_min_pa and pa_col is None:
        # We wanted to qualify but couldn't find a PA column; add a soft warning
        meta["warnings"] = [{"type": "missing_pa_column", "wanted_min_pa": int(effective_min_pa)}]

    return {"chart_type": "bar", "series": [{"id": stat, "data": data}], "meta": meta}


# ----------------- 1b) leaderboard across a range (bar) -----------------

def leaderboard_range(db, stat, start_year, end_year, limit=10, agg="sum", order="desc", min_pa=None):
    col = resolve_stat_column(db, stat)
    start_year, end_year = int(start_year), int(end_year)

    # We do NOT auto-apply MLB qualification across ranges by default,
    # because official qualifiers are per-season. Honor caller-supplied min_pa if provided.
    pa_name = _pa_column_name(db)
    pa_sum = func.sum(resolve_stat_column(db, pa_name)) if (pa_name and min_pa) else None

    agg_sum = func.sum(col).label("sum_v")
    agg_avg = func.avg(col).label("avg_v")

    q = (
        db.query(
            BattingStats.player_id,
            BattingStats.full_name,
            agg_sum,
            agg_avg,
            (pa_sum.label("tot_pa") if pa_sum is not None else literal_column("0").label("tot_pa")),
        )
        .filter(BattingStats.year.between(start_year, end_year))
        .group_by(BattingStats.player_id, BattingStats.full_name)
    )

    if min_pa and pa_sum is not None:
        q = q.having(pa_sum >= int(min_pa))

    use_col = "avg_v" if str(agg).lower() == "avg" else "sum_v"
    q = q.order_by(desc(use_col) if str(order).lower() != "asc" else asc(use_col)).limit(int(limit))

    rows = q.all()

    data = []
    for r in rows:
        val = getattr(r, use_col)
        if val is not None:
            data.append({"x": r.full_name, "y": float(val)})

    dir_label = "Top" if str(order).lower() != "asc" else "Bottom"
    agg_label = "average" if str(agg).lower() == "avg" else "total"
    meta = {
        "title": f"{dir_label} {int(limit)} {stat_label(stat)} — {start_year}–{end_year} ({agg_label})",
        "label_map": label_map_for([stat]),
        "range": {"start_year": start_year, "end_year": end_year, "agg": agg_label},
    }
    if min_pa and pa_sum is not None:
        meta["qualifier"] = {"min_pa_total": int(min_pa), "pa_column": pa_name, "applied_on": "sum(PA) over range"}
    return {"chart_type": "bar", "series": [{"id": f"{stat} ({agg_label})", "data": data}], "meta": meta}

# ----------------- 1c) leaderboard by year (facet of bars) -----------------

def leaderboard_by_year(db, stat, start_year, end_year, limit=10, order="desc", min_pa=None):
    """
    For each year in [start_year, end_year], return the top/bottom N players by `stat`
    for that single season. Returns a facet of bar charts (one facet per year).

    If `min_pa` is not provided and `stat` is a rate stat, we auto-apply the MLB
    per-season qualifier (3.1 * scheduled_games_for_that_year), per year.
    """
    col = resolve_stat_column(db, stat)
    start_year, end_year = int(start_year), int(end_year)
    years = list(range(start_year, end_year + 1))

    facets = []
    dir_label = "Top" if str(order).lower() != "asc" else "Bottom"
    label_map = label_map_for([stat])

    pa_name = _pa_column_name(db)

    for y in years:
        eff_min_pa = _auto_min_pa_if_rate_stat(stat, y, min_pa)
        pa_col = resolve_stat_column(db, pa_name) if (pa_name and eff_min_pa) else None

        q = db.query(BattingStats.player_id, BattingStats.full_name, col.label("v")).filter(BattingStats.year == y)
        if pa_col is not None:
            q = q.filter(pa_col >= int(eff_min_pa))
        q = q.order_by(desc("v") if str(order).lower() != "asc" else asc("v")).limit(int(limit))
        rows = q.all()

        data = [{"x": name, "y": float(v)} for _pid, name, v in rows if v is not None]
        fmeta = {"label_map": label_map}

        title = f"{dir_label} {int(limit)} {stat_label(stat)} — {y}"
        if pa_col is not None and eff_min_pa:
            title += " (qualified)"
            fmeta["qualifier"] = {
                "min_pa": int(eff_min_pa),
                "rule": "MLB 3.1 PA per scheduled game (Rule 9.22)",
                "scheduled_games": _scheduled_games(y),
                "pa_column": pa_name,
            }
        elif stat in RATE_QUAL_STATS and eff_min_pa and pa_col is None:
            fmeta["warnings"] = [{"type": "missing_pa_column", "year": y, "wanted_min_pa": int(eff_min_pa)}]

        facets.append({
            "title": title,
            "chart_type": "bar",
            "series": [{"id": stat, "data": data}],
            "meta": fmeta,
        })

    meta = {
        "title": f"Single-season leaders by year — {start_year}–{end_year}",
        "label_map": label_map,
        "range": {"start_year": start_year, "end_year": end_year}
    }
    return {"chart_type": "facet", "facets": facets, "meta": meta}


# ----------------- 2) career arc (line) -----------------

def career_arc(db, player_id, stat, start_year=None, end_year=None):
    col = resolve_stat_column(db, stat)
    if not start_year or not end_year:
        end_year = end_year or latest_year(db)
        start_year = start_year or end_year - 6

    rows = (
        db.query(BattingStats.year, col.label("v"))
        .filter(BattingStats.player_id == player_id)
        .filter(BattingStats.year.between(start_year, end_year))
        .order_by(BattingStats.year.asc())
        .all()
    )

    pts = [{"x": int(y), "y": float(v)} for y, v in rows if v is not None]
    name = db.query(BattingStats.full_name).filter(BattingStats.player_id == player_id).first()
    label = name[0] if name else str(player_id)
    meta = {
        "x_years": list(range(int(start_year), int(end_year) + 1)),
        "title": f"{label} — {stat_label(stat)} ({start_year}–{end_year})",
        "label_map": label_map_for([stat]),
    }
    return {"chart_type": "line", "series": [{"id": label, "data": pts}], "meta": meta}


# ----------------- 3) rolling mean (line) -----------------

def rolling_mean(db, player_id, stat, window=3, start_year=None, end_year=None):
    col = resolve_stat_column(db, stat)
    if not start_year or not end_year:
        end_year = end_year or latest_year(db)
        start_year = start_year or end_year - 8

    rows = (
        db.query(BattingStats.year, col.label("v"))
        .filter(BattingStats.player_id == player_id)
        .filter(BattingStats.year.between(start_year, end_year))
        .order_by(BattingStats.year.asc())
        .all()
    )

    years = [y for y, v in rows if v is not None]
    vals = [float(v) for y, v in rows if v is not None]
    if not years:
        return {
            "chart_type": "line",
            "series": [],
            "meta": {"x_years": list(range(int(start_year), int(end_year) + 1)), "label_map": label_map_for([stat])},
        }

    s = pd.Series(vals).rolling(int(window), min_periods=1).mean().tolist()
    pts = [{"x": int(y), "y": float(m)} for y, m in zip(years, s)]

    name = db.query(BattingStats.full_name).filter(BattingStats.player_id == player_id).first()
    meta = {
        "x_years": list(range(int(start_year), int(end_year) + 1)),
        "title": f"{name[0] if name else str(player_id)} — {stat_label(stat)} (rolling {window}, {start_year}–{end_year})",
        "label_map": label_map_for([stat]),
    }
    return {
        "chart_type": "line",
        "series": [{"id": (name[0] if name else str(player_id)) + f" (rolling {window})", "data": pts}],
        "meta": meta,
    }


# ----------------- 4) year-over-year change (bar) -----------------

def yoy_change(db, player_id, stat, start_year=None, end_year=None):
    col = resolve_stat_column(db, stat)
    if not start_year or not end_year:
        end_year = end_year or latest_year(db)
        start_year = start_year or end_year - 8

    rows = (
        db.query(BattingStats.year, col.label("v"))
        .filter(BattingStats.player_id == player_id)
        .filter(BattingStats.year.between(start_year, end_year))
        .order_by(BattingStats.year.asc())
        .all()
    )

    years = [y for y, v in rows if v is not None]
    vals = [float(v) for y, v in rows if v is not None]
    if len(vals) < 2:
        meta = {"title": f"Δ {stat_label(stat)} ({start_year}–{end_year})", "label_map": label_map_for([stat])}
        return {"chart_type": "bar", "series": [{"id": "Δ", "data": []}], "meta": meta}

    deltas = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    data = [{"x": int(years[i]), "y": float(deltas[i - 1])} for i in range(1, len(years))]
    meta = {"title": f"Δ {stat_label(stat)} ({start_year}–{end_year})", "label_map": label_map_for([stat])}
    return {"chart_type": "bar", "series": [{"id": f"Δ {stat} {start_year}->{end_year}", "data": data}], "meta": meta}


# ----------------- 5) percentile rank (bar) -----------------

def percentile_rank(db, player_ids, stat, year, min_pa=None):
    col = resolve_stat_column(db, stat)

    pa_name = _pa_column_name(db)
    pa_col = resolve_stat_column(db, pa_name) if (pa_name and min_pa) else None

    q = db.query(BattingStats.player_id, BattingStats.full_name, col.label("v")).filter(BattingStats.year == year)
    if pa_col is not None:
        q = q.filter(pa_col >= int(min_pa))
    league = q.all()

    league_vals = [float(v) for pid, name, v in league if v is not None]
    if not league_vals:
        meta = {"title": f"{stat_label(stat)} percentile ({year})", "label_map": label_map_for([stat])}
        return {"chart_type": "bar", "series": [{"id": "percentile", "data": []}], "meta": meta}

    arr = np.array(sorted(league_vals))
    by_id = {pid: (name, float(v)) for pid, name, v in league if v is not None}
    data = []
    for pid in player_ids:
        if pid in by_id:
            name, val = by_id[pid]
            pct = float(100.0 * (arr.searchsorted(val, side="right") / len(arr)))
            data.append({"x": name, "y": round(pct, 1)})
    meta = {"title": f"{stat_label(stat)} percentile ({year})", "label_map": label_map_for([stat])}
    return {"chart_type": "bar", "series": [{"id": f"{stat} percentile ({year})", "data": data}], "meta": meta}


# ----------------- 6) improvement leaderboard (bar) -----------------

def improvement_leaderboard(db, stat, year_start, year_end, limit=10, min_pa=None):
    col = resolve_stat_column(db, stat)
    q = (
        db.query(BattingStats.player_id, BattingStats.full_name, BattingStats.year, col.label("v"))
        .filter(BattingStats.year.in_([year_start, year_end]))
    )
    if min_pa:
        pa_name = _pa_column_name(db)
        if pa_name:
            q = q.filter(resolve_stat_column(db, pa_name) >= int(min_pa))

    rows = q.all()
    if not rows:
        meta = {
            "title": f"Most improved — {stat_label(stat)} ({year_start}→{year_end})",
            "label_map": label_map_for([stat]),
        }
        return {"chart_type": "bar", "series": [{"id": "Δ", "data": []}], "meta": meta}

    df = pd.DataFrame(rows, columns=["player_id", "full_name", "year", "v"])
    pivot = df.pivot_table(index=["player_id", "full_name"], columns="year", values="v", aggfunc="mean")
    pivot = pivot.dropna(subset=[year_start, year_end], how="any")
    pivot["delta"] = pivot[year_end] - pivot[year_start]
    top = pivot.sort_values("delta", ascending=False).head(int(limit))

    data = [{"x": name, "y": float(d)} for (_, name), d in zip(top.index, top["delta"].tolist())]
    meta = {"title": f"Most improved — {stat_label(stat)} ({year_start}→{year_end})", "label_map": label_map_for([stat])}
    return {"chart_type": "bar", "series": [{"id": f"Δ {stat} {year_start}->{year_end}", "data": data}], "meta": meta}


# ----------------- 7) rate per PA (bar) -----------------

def rate_per_pa(db, player_ids, numerator_stat, year, per=600, pa_col="plate_appearances"):
    # Use whichever PA column actually exists.
    real_pa_name = _pa_column_name(db) or pa_col
    if not col_exists(db, real_pa_name) and real_pa_name not in table_columns(db):
        raise ValueError(f"Missing column: {real_pa_name}")
    num = resolve_stat_column(db, numerator_stat)
    pa = resolve_stat_column(db, real_pa_name)

    rows = (
        db.query(BattingStats.full_name, num.label("n"), pa.label("pa"))
        .filter(BattingStats.player_id.in_(player_ids))
        .filter(BattingStats.year == year)
        .all()
    )

    data = []
    for name, n, pa_ in rows:
        if pa_ and pa_ > 0 and n is not None:
            rate = (float(n) / float(pa_)) * float(per)
            data.append({"x": name, "y": rate})
    meta = {"title": f"{stat_label(numerator_stat)} per {per} PA ({year})", "label_map": label_map_for([numerator_stat])}
    return {"chart_type": "bar", "series": [{"id": f"{numerator_stat} per {per} PA", "data": data}], "meta": meta}


# ----------------- 8) radar multi-stat (radar) -----------------

def radar_multistat(db, player_ids, stats, year):
    needed = [resolve_stat_column(db, s) for s in stats]
    q = (
        db.query(BattingStats.full_name, *needed)
        .filter(BattingStats.player_id.in_(player_ids))
        .filter(BattingStats.year == year)
    )
    rows = q.all()

    data = []
    for i, sname in enumerate(stats):
        row_obj = {"stat": sname}
        for row in rows:
            name = row[0]
            val = row[1 + i]
            if val is not None:
                row_obj[name] = float(val)
        data.append(row_obj)

    meta = {"title": f"Radar — {', '.join(stat_label(s) for s in stats)} ({year})", "label_map": label_map_for(stats)}
    return {"chart_type": "radar", "series": data, "meta": meta}


# ----------------- 9) histogram (bar) -----------------

def stat_histogram(db, stat, year, bins=12, min_pa=None):
    col = resolve_stat_column(db, stat)

    pa_name = _pa_column_name(db)
    pa_col = resolve_stat_column(db, pa_name) if (pa_name and min_pa) else None

    q = db.query(col.label("v")).filter(BattingStats.year == year)
    if pa_col is not None:
        q = q.filter(pa_col >= int(min_pa))
    vals = [float(v) for (v,) in q.all() if v is not None]
    if not vals:
        meta = {"title": f"{stat_label(stat)} histogram ({year})", "label_map": label_map_for([stat])}
        return {"chart_type": "bar", "series": [{"id": "hist", "data": []}], "meta": meta}

    hist, edges = np.histogram(vals, bins=int(bins))
    centers = 0.5 * (edges[:-1] + edges[1:])
    data = [{"x": f"{c:.3f}", "y": int(cnt)} for c, cnt in zip(centers, hist)]
    meta = {"title": f"{stat_label(stat)} histogram ({year})", "label_map": label_map_for([stat])}
    return {"chart_type": "bar", "series": [{"id": f"{stat} histogram {year}", "data": data}], "meta": meta}


# ----------------- NEW: multi-stat, multi-player compare -----------------

def _resolve_ids_from_maybe_names(db, players):
    ids = []
    for p in players:
        if isinstance(p, int) or (isinstance(p, str) and str(p).isdigit()):
            pid = int(p)
            if pid not in ids:
                ids.append(pid)
        elif isinstance(p, str):
            like = f"%{p.lower()}%"
            row = (
                db.query(BattingStats.player_id)
                .filter(func.lower(BattingStats.full_name).like(like))
                .order_by(BattingStats.year.desc())
                .first()
            )
            if row:
                pid = int(row[0])
                if pid not in ids:
                    ids.append(pid)
    return ids


def _avg_last_n_years(db, pid, stat, anchor_year, n):
    col = resolve_stat_column(db, stat)
    yrs = list(range(anchor_year - n + 1, anchor_year + 1))
    rows = (
        db.query(col.label("v"))
        .filter(BattingStats.player_id == pid, BattingStats.year.in_(yrs))
        .all()
    )
    vals = [float(v) for (v,) in rows if v is not None]
    return float(np.mean(vals)) if vals else None


def compare_multi(
    db,
    players,
    stats,
    year=None,
    start_year=None,
    end_year=None,
    mode="players_by_stat",
    layout="grouped",
    normalize=None,
    window=None,
):
    # facet for multi-stat over time
    if (start_year and end_year) and len(stats) > 1:
        pids = _resolve_ids_from_maybe_names(db, players)
        x_years = list(range(int(start_year), int(end_year) + 1))
        facets = []
        for s in stats:
            by_player = []
            for pid in pids:
                res = career_arc(db, pid, s, start_year, end_year)
                by_player.extend(res["series"])
            facets.append(
                {
                    "title": stat_label(s),
                    "chart_type": "line",
                    "series": by_player,
                    "meta": {"x_years": x_years, "label_map": label_map_for([s])},
                }
            )
        return {
            "chart_type": "facet",
            "facets": facets,
            "meta": {
                "facet_type": "by_stat",
                "layout": "grid",
                "x_years": x_years,
                "label_map": label_map_for(stats),
            },
        }

    if year and (start_year or end_year):
        raise ValueError("Provide either 'year' OR 'start_year'+'end_year', not both.")
    if not year:
        year = latest_year(db)

    pids = _resolve_ids_from_maybe_names(db, players)
    labels = names_for_ids(db, pids)
    per_pa = None
    if isinstance(normalize, dict) and "per_pa" in normalize:
        per_pa = int(normalize["per_pa"])
        real_pa_name = _pa_column_name(db) or "plate_appearances"
        if not col_exists(db, real_pa_name) and real_pa_name not in table_columns(db):
            raise ValueError("normalize.per_pa requested but a PA column was not found.")
        # if we got here, downstream usage will resolve the correct column

    for s in stats:
        _ = resolve_stat_column(db, s)

    warnings = []
    matrix = {pid: {} for pid in pids}
    for pid in pids:
        for s in stats:
            if window and int(window) > 0:
                val = _avg_last_n_years(db, pid, s, year, int(window))
                if val is None:
                    warnings.append(
                        {
                            "type": "missing_window",
                            "player_id": pid,
                            "player": labels[pid],
                            "stat": s,
                            "year": year,
                            "window": int(window),
                        }
                    )
            else:
                col = resolve_stat_column(db, s)

                # Use real PA column if normalization is requested
                real_pa_name = _pa_column_name(db) or "plate_appearances"
                row = (
                    db.query(col.label("v"), resolve_stat_column(db, real_pa_name).label("pa"))
                    .filter(BattingStats.player_id == pid, BattingStats.year == year)
                    .first()
                )
                if not row:
                    warnings.append(
                        {
                            "type": "no_row_for_year",
                            "player_id": pid,
                            "player": labels[pid],
                            "stat": s,
                            "year": year,
                        }
                    )
                    val = None
                else:
                    v = float(row[0]) if row[0] is not None else None
                    pa_val = int(row[1]) if len(row) > 1 and row[1] is not None else None
                    if v is None:
                        warnings.append(
                            {
                                "type": "null_value",
                                "player_id": pid,
                                "player": labels[pid],
                                "stat": s,
                                "year": year,
                            }
                        )
                    if per_pa and v is not None and pa_val and pa_val > 0:
                        v = (v / pa_val) * per_pa
                    val = v
            matrix[pid][s] = val

    series = []
    if mode == "players_by_stat":
        for s in stats:
            data = []
            for pid in pids:
                v = matrix[pid].get(s)
                if v is not None:
                    data.append({"x": labels[pid], "y": float(v)})
            series.append({"id": s, "data": data})
    else:
        for pid in pids:
            data = []
            for s in stats:
                v = matrix[pid].get(s)
                if v is not None:
                    data.append({"x": s, "y": float(v)})
            series.append({"id": labels[pid], "data": data})

    title_players = ", ".join(labels[pid] for pid in pids)
    title_stats = ", ".join(stat_label(s) for s in stats)

    return {
        "chart_type": "bar",
        "series": series,
        "meta": {
            "layout": layout,
            "mode": mode,
            "year": year,
            "window": window,
            "normalized_per_pa": per_pa,
            "warnings": warnings,
            "label_map": label_map_for(stats),
            "title": f"{title_players} — {title_stats} ({year})",
        },
    }
