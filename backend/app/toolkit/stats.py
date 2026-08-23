# backend/app/toolkit/stats.py
from collections import defaultdict
import numpy as np
import pandas as pd
from sqlalchemy import func, desc, asc, inspect, literal_column

from ..db.models import BattingStats

# ---------- canonical labels (backend source of truth) ----------
# Tip: anything not listed here falls through to stat_label()'s smart formatter.
STAT_LABELS = {
    # Core rate/avg
    "woba": "wOBA",
    "xwoba": "xwOBA",
    "wobacon": "wOBAcon",
    "xwobacon": "xwOBAcon",
    "bacon": "BA on Contact",
    "xbacon": "xBA on Contact",
    "xba": "xBA",
    "xslg": "xSLG",
    "xobp": "xOBP",
    "xiso": "xISO",
    "xbadiff": "xBA – BA",
    "xslgdiff": "xSLG – SLG",
    "wobadiff": "wOBA Diff",
    "babip": "BABIP",
    "on_base_plus_slg": "OPS",
    "on_base_percent": "On-Base %",
    "slg_percent": "Slugging %",
    "isolated_power": "ISO",
    "batting_avg": "Batting Average",

    # Counting (batting)
    "ab": "At-Bats",
    "pa": "Plate Appearances",
    "plate_appearances": "Plate Appearances",
    "hit": "Hits",
    "single": "Singles",
    "double": "Doubles",
    "triple": "Triples",
    "home_run": "Home Runs",
    "strikeout": "Strikeouts",
    "walk": "Walks",
    "b_rbi": "RBIs",
    "b_total_bases": "Total Bases",
    "b_lob": "Left On Base",
    "b_hit_by_mouse": "HBP",  # safety: never used; ignore if not present
    "b_hit_by_pitch": "HBP",
    "b_sac_fly": "Sacrifice Flies",
    "b_sac_bunt": "Sacrifice Bunts",
    "b_gnd_into_dp": "GIDP",
    "b_gnd_into_tp": "Grounded Into Triple Play",
    "b_gnd_rule_double": "Ground-Rule Doubles",
    "b_reached_on_error": "Reached on Error",
    "b_reached_on_int": "Reached on Interference",
    "b_walkoff": "Walk-offs",

    # Plate-discipline / pitch result counts
    "b_ball": "Balls",
    "b_total_ball": "Balls (Total)",
    "b_called_strike": "Called Strikes",
    "b_swinging_strike": "Swinging Strikes",
    "b_total_swinging_strike": "Swinging Strikes (Total)",
    "b_total_strike": "Strikes (Total)",
    "b_total_pitches": "Pitches Seen",
    "b_pitchout": "Pitchouts",
    "b_catcher_interf": "Catcher’s Interference",
    "b_interference": "Batter Interference",
    "b_intent_ball": "Intentional Balls",
    "b_intent_walk": "IBB",
    "b_pinch_hit": "Pinch-Hit PA",
    "b_pinch_run": "Pinch-Run",
    "b_played_dh": "Games at DH",
    "b_game": "Games (Batting)",
    "b_hit_into_play": "Balls Put In Play",
    "b_hit_ground": "Groundball Hits",
    "b_hit_fly": "Flyball Hits",
    "b_hit_line_drive": "Line-Drive Hits",
    "b_hit_popup": "Popup Hits",
    "b_out_fly": "Fly Outs",
    "b_out_ground": "Ground Outs",
    "b_out_line_drive": "Lineouts",
    "b_out_popup": "Popup Outs",

    # Rates / % (discipline & contact quality)
    "bb_percent": "BB%",
    "k_percent": "K%",
    "hard_hit_percent": "Hard-Hit %",
    "sweet_spot_percent": "Sweet-Spot %",
    "barrel_batted_rate": "Barrel %",
    "solidcontact_percent": "Solid Contact %",
    "flareburner_percent": "Flare/Burner %",
    "poorlyunder_percent": "Under %",
    "poorlytopped_percent": "Topped %",
    "poorlyweak_percent": "Weak %",
    "whiff_percent": "Whiff %",
    "swing_percent": "Swing %",
    "z_swing_percent": "Z-Swing %",
    "z_swing_miss_percent": "Z-Whiff %",
    "oz_swing_percent": "O-Swing %",
    "oz_swing_miss_percent": "O-Whiff %",
    "oz_contact_percent": "O-Contact %",
    "iz_contact_percent": "Z-Contact %",
    "f_strike_percent": "First-Pitch Strike %",
    "meatball_percent": "Meatball %",
    "meatball_swing_percent": "Meatball Swing %",
    "in_zone_percent": "In-Zone %",
    "out_zone_percent": "Out-of-Zone %",
    "edge_percent": "Edge %",
    "pull_percent": "Pull %",
    "straightaway_percent": "Straightaway %",
    "opposite_percent": "Opposite %",
    "groundballs_percent": "Groundball %",
    "flyballs_percent": "Flyball %",
    "linedrives_percent": "Line-Drive %",
    "popups_percent": "Popup %",

    # Pitching (pitching_stats table)
    "p_era": "ERA",
    "p_win": "Wins",
    "p_loss": "Losses",
    "p_save": "Saves",
    "p_blown_save": "Blown Saves",
    "p_hold": "Holds",
    "p_quality_start": "Quality Starts",
    "p_complete_game": "Complete Games",
    "p_shutout": "Shutouts",
    "p_formatted_ip": "Innings Pitched",
    "p_game": "Games Pitched",
    "p_opp_batting_avg": "Opponent Batting Avg",
    "p_opp_on_base_avg": "Opponent OBP",
    "p_earned_run": "Earned Runs",
    "ff_avg_speed": "Avg Fastball Velo (4-seam)",
    "fastball_avg_speed": "Avg Fastball Velo",
    "fastball_avg_spin": "Avg Fastball Spin",

    # Swing/bat metrics
    "avg_swing_speed": "Avg Swing Speed",
    "avg_swing_length": "Avg Swing Length",
    "fast_swing_rate": "Fast Swing %",
    "blasts_contact": "Blasts per Contact",
    "blasts_swing": "Blasts per Swing",
    "squared_up_contact": "Squared-Up Contact %",
    "squared_up_swing": "Squared-Up Swing %",
    "swords": "Swords",
    "attack_angle": "Attack Angle (°)",
    "attack_direction": "Attack Direction (°)",
    "ideal_angle_rate": "Ideal LA %",
    "vertical_swing_path": "Vertical Swing Path (°)",

    # BBE quality & x
    "exit_velocity_avg": "Avg Exit Velocity",
    "launch_angle_avg": "Avg Launch Angle",
    "barrel": "Barrels",

    # Zone aggregates / counts
    "out_zone": "Out-of-Zone Pitches",
    "in_zone": "In-Zone Pitches",
    "in_zone_swing": "Z-Swings",
    "in_zone_swing_miss": "Z-Whiffs",
    "out_zone_swing": "O-Swings",
    "out_zone_swing_miss": "O-Whiffs",
    "edge": "Edge Pitches",

    # Pitches seen by type
    "pitch_count": "Pitches Seen",
    "pitch_count_fastball": "Fastballs Seen",
    "pitch_count_breaking": "Breaking Balls Seen",
    "pitch_count_offspeed": "Offspeed Seen",

    # Batted-ball distribution (counts)
    "batted_ball": "Batted Balls",
    "groundballs": "Groundballs",
    "flyballs": "Flyballs",
    "linedrives": "Line Drives",
    "popups": "Popups",

    # Running / stealing
    "r_total_stolen_base": "Stolen Bases",
    "r_total_caught_stealing": "Caught Stealing",
    "r_stolen_base_pct": "SB %",
    "r_total_pickoff": "Total Pickoffs",
    "r_run": "Runs",
    "r_caught_stealing_2b": "CS 2B",
    "r_caught_stealing_3b": "CS 3B",
    "r_caught_stealing_home": "CS Home",
    "r_stolen_base_2b": "SB 2B",
    "r_stolen_base_3b": "SB 3B",
    "r_stolen_base_home": "SB Home",
    "r_defensive_indiff": "Defensive Indifference",
    "r_interference": "Runner Interference",
    "r_pickoff_1b": "Pickoff 1B",
    "r_pickoff_2b": "Pickoff 2B",
    "r_pickoff_3b": "Pickoff 3B",

    # Catching / pop-time related (labels stay descriptive)
    "pop_2b_sba_count": "SBA (2B) – Count",
    "pop_2b_sba": "SBA (2B)",
    "pop_2b_sb": "SB Allowed (2B)",
    "pop_2b_cs": "CS (2B)",
    "pop_3b_sba_count": "SBA (3B) – Count",
    "pop_3b_sba": "SBA (3B)",
    "pop_3b_sb": "SB Allowed (3B)",
    "pop_3b_cs": "CS (3B)",
    "exchange_2b_3b_sba": "Exchange — 2B/3B SB Attempts",
    "maxeff_arm_2b_3b_sba": "Max-Effort Arm — 2B/3B SBA",

    # OAA / defense stars
    "n_outs_above_average": "OAA",
    "n_fieldout_5stars": "5★ Field Outs",
    "n_opp_5stars": "5★ Opportunities",
    "n_5star_percent": "5★ Conversion %",
    "n_fieldout_4stars": "4★ Field Outs",
    "n_opp_4stars": "4★ Opportunities",
    "n_4star_percent": "4★ Conversion %",
    "n_fieldout_3stars": "3★ Field Outs",
    "n_opp_3stars": "3★ Opportunities",
    "n_3star_percent": "3★ Conversion %",
    "n_fieldout_2stars": "2★ Field Outs",
    "n_opp_2stars": "2★ Opportunities",
    "n_2star_percent": "2★ Conversion %",
    "n_fieldout_1stars": "1★ Field Outs",
    "n_opp_1stars": "1★ Opportunities",
    "n_1star_percent": "1★ Conversion %",

    # Route/footwork relatives
    "rel_league_reaction_distance": "Rel to Lg: Reaction Dist",
    "rel_league_burst_distance": "Rel to Lg: Burst Dist",
    "rel_league_routing_distance": "Rel to Lg: Routing Dist",
    "rel_league_bootup_distance": "Rel to Lg: Boot-up Dist",
    "f_bootup_distance": "Boot-up Distance",

    # Speed
    "n_bolts": "Bolts",
    "hp_to_1b": "Home-to-1B (s)",
    "sprint_speed": "Sprint Speed (ft/s)",

    # Useful basics
    "player_age": "Age",
    "player_id": "Player ID",
    "year": "Year",

    # Bat-tracking marts (mart_bat_tracking_season / mart_batter_pitch_season);
    # avg_swing_length / fast_swing_rate / swords already labeled above.
    "avg_bat_speed": "Avg Bat Speed (mph)",
    "blast_rate": "Blast Rate",
    "squared_up_rate": "Squared-Up Rate",
    "competitive_swings": "Competitive Swings",
    "batter_run_value": "Batter Run Value",
    "whiff_rate": "Whiff Rate",
    "chase_rate": "Chase Rate",
    "contact_rate": "Contact Rate",
    "zone_rate": "Zone Rate",
    "avg_exit_velo": "Avg Exit Velo (mph)",
    "hard_hit_rate": "Hard-Hit Rate",
    "barrel_rate": "Barrel Rate",
    "avg_launch_angle": "Avg Launch Angle (°)",
    "season": "Season",
}

# ---- Rate stats where "qualified" leaderboards should auto-apply MLB PA threshold
# Curated list + a general rule for any *_percent stat.
RATE_QUAL_STATS = {
    # Traditional batting rates
    "batting_avg", "on_base_percent", "slg_percent", "on_base_plus_slg",
    "woba", "isolated_power", "babip",
    # Expected & contact quality rates
    "xba", "xslg", "xobp", "xiso", "xwoba", "wobacon", "xwobacon",
    # Plate discipline / % rates
    "k_percent", "bb_percent", "whiff_percent", "swing_percent",
    "z_swing_percent", "z_swing_miss_percent",
    "oz_swing_percent", "oz_swing_miss_percent",
    "oz_contact_percent", "iz_contact_percent",
    "f_strike_percent", "meatball_percent", "meatball_swing_percent",
    # Contact quality % rates
    "hard_hit_percent", "sweet_spot_percent", "barrel_batted_rate",
    "pull_percent", "opposite_percent", "straightaway_percent",
    "groundballs_percent", "flyballs_percent", "linedrives_percent", "popups_percent",
    # Baserunning %
    "r_stolen_base_pct",
}

def is_rate_stat(stat: str) -> bool:
    # Treat *_percent slugs and the curated list above as rate stats
    # that need PA qualification by default (Rule 9.22).
    return isinstance(stat, str) and (stat in RATE_QUAL_STATS or stat.endswith("_percent"))

def stat_label(slug: str) -> str:
    """
    Smart, compact human label:
      - uses STAT_LABELS when provided,
      - snake_case -> Title Case,
      - trailing 'Percent' -> '%',
      - keeps common acronyms tidy.
    """
    if not isinstance(slug, str) or not slug:
        return str(slug)
    if slug in STAT_LABELS:
        return STAT_LABELS[slug]

    # generic: snake_case -> Title Case
    parts = [p for p in slug.split("_") if p]
    if not parts:
        return slug
    base = " " .join(w.capitalize() for w in parts)
    if base.endswith(" Percent"):
        base = base[: -len(" Percent")] + " %"
    # Light acronym polish
    base = (base
            .replace("Woba", "wOBA")
            .replace("Wobacon", "wOBAcon")
            .replace("Xwoba", "xwOBA")
            .replace("Xba", "xBA")
            .replace("Xslg", "xSLG")
            .replace("Xobp", "xOBP")
            .replace("Xiso", "xISO")
            .replace("Bb ", "BB ")
            .replace("K Percent", "K %"))
    return base


def label_map_for(stats) -> dict:
    return {str(s): stat_label(str(s)) for s in (stats or [])}


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

    # --- special virtuals first ---
    if stat == "on_base_plus_slg":
        # Compute OPS if not a physical column: OBP + SLG
        obp_col = getattr(BattingStats, "on_base_percent", None)
        slg_col = getattr(BattingStats, "slg_percent", None)

        if obp_col is None and "on_base_percent" in table_columns(db):
            obp_col = literal_column("on_base_percent")
        if slg_col is None and "slg_percent" in table_columns(db):
            slg_col = literal_column("slg_percent")

        if obp_col is not None and slg_col is not None:
            return (obp_col + slg_col).label("on_base_plus_slg")

    # regular ORM attribute
    col = getattr(BattingStats, stat, None)
    if col is not None:
        return col
    # raw DB column
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
    cols = table_columns(db)
    if "plate_appearances" in cols:
        return "plate_appearances"
    if "pa" in cols:
        return "pa"
    if getattr(BattingStats, "plate_appearances", None) is not None:
        return "plate_appearances"
    return None


_GAMES_BY_YEAR = {  # shortened season
    2020: 60,
}
_DEFAULT_SCHEDULED_GAMES = 162


def _scheduled_games(year: int) -> int:
    return int(_GAMES_BY_YEAR.get(int(year), _DEFAULT_SCHEDULED_GAMES))


def _qualified_pa_threshold(year: int) -> int:
    return int(round(3.1 * _scheduled_games(year)))


def _qualified_pa_threshold_range(start_year: int, end_year: int) -> int:
    yrs = range(int(start_year), int(end_year) + 1)
    total_sched = sum(_scheduled_games(y) for y in yrs)
    return int(round(3.1 * total_sched))


def _auto_min_pa_if_rate_stat(stat: str, year: int, min_pa: int or None) -> int or None:
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
    """
    Player-vs-player view. **Do not hide** under-qualified rate seasons; instead
    include the values and attach warnings so the UI can badge them.
    """
    col = resolve_stat_column(db, stat)
    if year and (start_year or end_year):
        raise ValueError("Provide either 'year' OR 'start_year'+'end_year', not both.")

    is_single_year = bool(year)
    meta = {"warnings": [], "label_map": label_map_for([stat])}
    names_map = names_for_ids(db, player_ids)
    names_in_order = [names_map.get(pid, str(pid)) for pid in player_ids]

    # qualification prep (we only WARN; we do not filter points)
    pa_name = _pa_column_name(db)
    want_qual = is_rate_stat(stat) and (pa_name is not None)
    pa_col = resolve_stat_column(db, pa_name) if want_qual else literal_column("0")

    q = (
        db.query(
            BattingStats.player_id,
            BattingStats.full_name,
            BattingStats.year,
            col.label("v"),
            pa_col.label("pa"),
        )
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

    # Keep values; only warn if under-qualified
    filtered = []
    for pid, name, y, v, pa in rows:
        if v is None:
            continue
        if want_qual:
            thresh = _qualified_pa_threshold(y)
            if pa is None or int(pa) < int(thresh):
                meta["warnings"].append({
                    "type": "unqualified_rate_season",
                    "player_id": pid, "player": name, "year": int(y),
                    "stat": stat, "pa": int(pa or 0), "needed_pa": int(thresh),
                })
        filtered.append((pid, name, y, float(v)))

    if is_single_year:
        returned_pids = {pid for (pid, _nm, _y, _v) in filtered}
        missing_pids = [pid for pid in player_ids if pid not in returned_pids]
        for pid in missing_pids:
            meta["warnings"].append(
                {"type": "missing_value", "player_id": pid, "player": names_map.get(pid, str(pid)),
                 "year": year, "stat": stat, "reason": "no value for that year"}
            )
        data = [{"x": name, "y": v} for (_pid, name, _y, v) in filtered]
        meta["title"] = f"{' vs '.join(names_in_order)} — {stat_label(stat)} ({year})"
        return {"chart_type": "bar", "series": [{"id": stat, "data": data}], "meta": meta}

    by_player = defaultdict(list)
    seen_pid_with_data = set()
    for pid, name, y, v in filtered:
        by_player[name].append({"x": int(y), "y": float(v)})
        seen_pid_with_data.add(pid)

    for pid in player_ids:
        if pid not in seen_pid_with_data:
            meta["warnings"].append(
                {"type": "no_data_in_range", "player_id": pid, "player": names_map.get(pid, str(pid)),
                 "start_year": start_year, "end_year": end_year, "stat": stat}
            )

    series = [{"id": name, "data": pts} for name, pts in by_player.items()]
    meta["x_years"] = list(range(int(start_year), int(end_year) + 1))
    meta["title"] = f"{' vs '.join(names_in_order)} — {stat_label(stat)} ({start_year}–{end_year})"
    return {"chart_type": "line", "series": series, "meta": meta}


# ----------------- 1) leaderboard (bar) -----------------
def leaderboard(db, stat, year=None, limit=10, min_pa=None, order="desc"):
    col = resolve_stat_column(db, stat)
    year = year or latest_year(db)

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
        meta["warnings"] = [{"type": "missing_pa_column", "wanted_min_pa": int(effective_min_pa)}]

    return {"chart_type": "bar", "series": [{"id": stat, "data": data}], "meta": meta}


# ----------------- 1b) leaderboard across a range (bar) -----------------
def leaderboard_range(db, stat, start_year, end_year, limit=10, agg="sum", order="desc", min_pa=None):
    col = resolve_stat_column(db, stat)
    start_year, end_year = int(start_year), int(end_year)

    # auto-qualify rate stats when averaging across a span
    effective_min_pa = min_pa
    if str(agg).lower() == "avg" and is_rate_stat(stat) and min_pa is None:
        effective_min_pa = _qualified_pa_threshold_range(start_year, end_year)

    pa_name = _pa_column_name(db)
    pa_sum = func.sum(resolve_stat_column(db, pa_name)) if (pa_name and effective_min_pa) else None

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

    if effective_min_pa and pa_sum is not None:
        q = q.having(pa_sum >= int(effective_min_pa))

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
    if effective_min_pa and pa_sum is not None:
        meta["qualifier"] = {
            "min_pa_total": int(effective_min_pa),
            "rule": "MLB 3.1 PA per scheduled game (Rule 9.22) across span",
            "pa_column": pa_name,
        }
    return {"chart_type": "bar", "series": [{"id": f"{stat} ({agg_label})", "data": data}], "meta": meta}

# ----------------- 1c) leaderboard by year (facet of bars) -----------------
def leaderboard_by_year(db, stat, start_year, end_year, limit=10, order="desc", min_pa=None):
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
    """
    Single-player timeline. **Do not drop** under-qualified rate seasons; include
    the values and attach warnings in meta so the UI can badge them.
    """
    col = resolve_stat_column(db, stat)
    if not start_year or not end_year:
        end_year = end_year or latest_year(db)
        start_year = start_year or end_year - 6

    pa_name = _pa_column_name(db)
    want_qual = is_rate_stat(stat) and (pa_name is not None)
    pa_col = resolve_stat_column(db, pa_name) if want_qual else literal_column("0")

    rows = (
        db.query(BattingStats.year, col.label("v"), pa_col.label("pa"))
        .filter(BattingStats.player_id == player_id)
        .filter(BattingStats.year.between(start_year, end_year))
        .order_by(BattingStats.year.asc())
        .all()
    )

    pts = []
    warnings = []
    for y, v, pa in rows:
        if v is None:
            continue
        if want_qual:
            need = _qualified_pa_threshold(int(y))
            if pa is None or int(pa) < int(need):
                warnings.append({
                    "type": "unqualified_rate_season",
                    "player_id": int(player_id),
                    "year": int(y),
                    "stat": stat,
                    "pa": int(pa or 0),
                    "needed_pa": int(need),
                })
        pts.append({"x": int(y), "y": float(v)})

    name = db.query(BattingStats.full_name).filter(BattingStats.player_id == player_id).first()
    label = name[0] if name else str(player_id)
    meta = {
        "x_years": list(range(int(start_year), int(end_year) + 1)),
        "title": f"{label} — {stat_label(stat)} ({start_year}–{end_year})",
        "label_map": label_map_for([stat]),
    }
    if warnings:
        meta["warnings"] = warnings
    return {"chart_type": "line", "series": [{"id": label, "data": pts}], "meta": meta}


# ----------------- 3) rolling mean (line) -----------------
def rolling_mean(db, player_id, stat, window=3, start_year=None, end_year=None):
    col = resolve_stat_column(db, stat)
    if not start_year or not end_year:
        end_year = end_year or latest_year(db)
        start_year = start_year or end_year - 8

    # Keep behavior here unchanged (can be relaxed similarly if desired)
    want_qual = is_rate_stat(stat) and (_pa_column_name(db) is not None)
    pa_col = resolve_stat_column(db, _pa_column_name(db)) if want_qual else literal_column("0")

    rows = (
        db.query(BattingStats.year, col.label("v"), pa_col.label("pa"))
        .filter(BattingStats.player_id == player_id)
        .filter(BattingStats.year.between(start_year, end_year))
        .order_by(BattingStats.year.asc())
        .all()
    )

    years = []
    vals = []
    for y, v, pa in rows:
        if v is None:
            continue
        if want_qual:
            if pa is None or int(pa) < _qualified_pa_threshold(int(y)):
                continue
        years.append(y)
        vals.append(float(v))

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

    # Keep behavior here unchanged (can be relaxed similarly if desired)
    want_qual = is_rate_stat(stat) and (_pa_column_name(db) is not None)
    pa_col = resolve_stat_column(db, _pa_column_name(db)) if want_qual else literal_column("0")

    rows = (
        db.query(BattingStats.year, col.label("v"), pa_col.label("pa"))
        .filter(BattingStats.player_id == player_id)
        .filter(BattingStats.year.between(start_year, end_year))
        .order_by(BattingStats.year.asc())
        .all()
    )

    years = []
    vals = []
    for y, v, pa in rows:
        if v is None:
            continue
        if want_qual:
            if pa is None or int(pa) < _qualified_pa_threshold(int(y)):
                continue
        years.append(y)
        vals.append(float(v))

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

    # auto-qualification for rate stats (leaderboard context)
    eff_min = _auto_min_pa_if_rate_stat(stat, year, min_pa)

    pa_name = _pa_column_name(db)
    pa_col = resolve_stat_column(db, pa_name) if (pa_name and eff_min) else None

    q = db.query(BattingStats.player_id, BattingStats.full_name, col.label("v")).filter(BattingStats.year == year)
    if pa_col is not None:
        q = q.filter(pa_col >= int(eff_min))
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

    # if rate stat and no min_pa supplied, enforce MLB threshold per year (leaderboard context)
    auto_enforce = is_rate_stat(stat) and (_pa_column_name(db) is not None) and (min_pa is None)
    pa_col = resolve_stat_column(db, _pa_column_name(db)) if (_pa_column_name(db) and (min_pa or auto_enforce)) else None
    need_start = _qualified_pa_threshold(year_start) if auto_enforce else (min_pa or None)
    need_end = _qualified_pa_threshold(year_end) if auto_enforce else (min_pa or None)

    q = (
        db.query(BattingStats.player_id, BattingStats.full_name, BattingStats.year, col.label("v"),
                 (pa_col.label("pa") if pa_col is not None else literal_column("0").label("pa")))
        .filter(BattingStats.year.in_([year_start, year_end]))
    )

    rows = q.all()
    if not rows:
        meta = {
            "title": f"Most improved — {stat_label(stat)} ({year_start}→{year_end})",
            "label_map": label_map_for([stat]),
        }
        return {"chart_type": "bar", "series": [{"id": "Δ", "data": []}], "meta": meta}

    df = pd.DataFrame(rows, columns=["player_id", "full_name", "year", "v", "pa"])

    # enforce PA thresholds per season if needed
    if pa_col is not None and (need_start or need_end):
        keep = []
        for pid, g in df.groupby("player_id"):
            ok_start = True
            ok_end = True
            if year_start in g["year"].values:
                pa_s = int(g[g["year"] == year_start]["pa"].fillna(0).values[0])
                if need_start and pa_s < int(need_start):
                    ok_start = False
            if year_end in g["year"].values:
                pa_e = int(g[g["year"] == year_end]["pa"].fillna(0).values[0])
                if need_end and pa_e < int(need_end):
                    ok_end = False
            if ok_start and ok_end:
                keep.append(g)
        df = pd.concat(keep, ignore_index=True) if keep else pd.DataFrame(columns=df.columns)

    if df.empty:
        meta = {"title": f"Most improved — {stat_label(stat)} ({year_start}→{year_end})", "label_map": label_map_for([stat])}
        return {"chart_type": "bar", "series": [{"id": "Δ", "data": []}], "meta": meta}

    pivot = df.pivot_table(index=["player_id", "full_name"], columns="year", values="v", aggfunc="mean")
    pivot = pivot.dropna(subset=[year_start, year_end], how="any")
    pivot["delta"] = pivot[year_end] - pivot[year_start]
    top = pivot.sort_values("delta", ascending=False).head(int(limit))

    data = [{"x": name, "y": float(d)} for (_, name), d in zip(top.index, top["delta"].tolist())]
    meta = {"title": f"Most improved — {stat_label(stat)} ({year_start}→{year_end})", "label_map": label_map_for([stat])}
    return {"chart_type": "bar", "series": [{"id": f"Δ {stat} {year_start}->{year_end}", "data": data}], "meta": meta}


# ----------------- 7) rate per PA (bar) -----------------
def rate_per_pa(db, player_ids, numerator_stat, year, per=600, pa_col="plate_appearances"):
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

    # auto-qualification for rate stats
    eff_min = _auto_min_pa_if_rate_stat(stat, year, min_pa)

    pa_name = _pa_column_name(db)
    pa_col = resolve_stat_column(db, pa_name) if (pa_name and eff_min) else None

    q = db.query(col.label("v")).filter(BattingStats.year == year)
    if pa_col is not None:
        q = q.filter(pa_col >= int(eff_min))
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
    want_qual = is_rate_stat(stat) and (_pa_column_name(db) is not None)
    pa_col = resolve_stat_column(db, _pa_column_name(db)) if want_qual else literal_column("0")

    rows = (
        db.query(col.label("v"), pa_col.label("pa"))
        .filter(BattingStats.player_id == pid, BattingStats.year.in_(yrs))
        .all()
    )
    vals = []
    for v, pa in rows:
        if v is None:
            continue
        if want_qual:
            # need per-year threshold; we don't have year in this small query, so requery year too
            pass
    # Re-run with year so we can check thresholds
    rows = (
        db.query(BattingStats.year, col.label("v"), pa_col.label("pa"))
        .filter(BattingStats.player_id == pid, BattingStats.year.in_(yrs))
        .all()
    )
    for y, v, pa in rows:
        if v is None:
            continue
        if want_qual and (pa is None or int(pa) < _qualified_pa_threshold(int(y))):
            continue
        vals.append(float(v))
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
                "label_map": label_map_for([s for s in stats]),
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

                    # For player compare views: keep value even if under-qualified; warn only.
                    if v is not None and is_rate_stat(s) and pa_val is not None:
                        need = _qualified_pa_threshold(year)
                        if pa_val < need:
                            warnings.append({
                                "type": "unqualified_rate_season",
                                "player_id": pid, "player": labels[pid], "stat": s, "year": year,
                                "pa": int(pa_val), "needed_pa": int(need),
                            })
                            # keep v

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
