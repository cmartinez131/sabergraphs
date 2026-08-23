# backend/app/toolkit/aligned.py
#
# Career-aligned comparisons over the player_season_index view: rookie
# season vs rookie season, and first-N-seasons trajectories. Same contract
# as the rest of the toolkit — canonical {chart_type, series, meta} payloads,
# stat access through resolve_stat_column, every user value a bound
# parameter. The season alignment (which YEAR is a player's rookie season)
# comes from the view, never from the LLM.

from sqlalchemy import and_, bindparam, or_, text as sa_text

from ..db.models import BattingStats
from .stats import label_map_for, resolve_stat_column, stat_label

ROOKIE_DEFINITION = (
    "Rookie season = last observed season entered with career AB <= 130 "
    "(MLB Rule 5.10 approximation; roster-days criterion not modeled)."
)


def season_index_rows(db, player_ids):
    """Rows from player_season_index for `player_ids` (bound, expanding)."""
    if not player_ids:
        return []
    stmt = sa_text(
        "SELECT player_id, year, season_number, prior_ab, first_observed_year, "
        "       rookie_season_year, rookie_pre_panel, is_rookie_season "
        "FROM player_season_index WHERE player_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    return db.execute(stmt, {"ids": [int(p) for p in player_ids]}).mappings().all()


def _names_for(db, player_ids):
    rows = (
        db.query(BattingStats.player_id, BattingStats.full_name)
        .filter(BattingStats.player_id.in_([int(p) for p in player_ids]))
        .distinct()
        .all()
    )
    return {int(pid): name for pid, name in rows}


def rookie_years(db, player_ids):
    """{player_id: {"year": int|None, "censored": bool}} per requested player."""
    out = {int(p): {"year": None, "censored": False} for p in player_ids}
    for r in season_index_rows(db, player_ids):
        pid = int(r["player_id"])
        if int(r["rookie_pre_panel"] or 0):
            out[pid]["censored"] = True
        if int(r["is_rookie_season"] or 0):
            out[pid]["year"] = int(r["year"])
    return out


def _stat_values(db, pairs, stats):
    """{(player_id, year): {stat: value}} for exact (player, year) pairs."""
    if not pairs:
        return {}
    cols = [resolve_stat_column(db, s) for s in stats]
    conds = [
        and_(BattingStats.player_id == int(pid), BattingStats.year == int(yr))
        for (pid, yr) in pairs
    ]
    rows = (
        db.query(BattingStats.player_id, BattingStats.year, *cols)
        .filter(or_(*conds))
        .all()
    )
    out = {}
    for row in rows:
        pid, yr, *vals = row
        out[(int(pid), int(yr))] = {
            s: (None if v is None else float(v)) for s, v in zip(stats, vals)
        }
    return out


def compare_rookie_seasons(db, player_ids, stats, notes=None):
    """Rookie season vs rookie season -> grouped bar. Each x label carries
    the player's OWN rookie year — "Aaron Judge (2017)" next to
    "Anthony Volpe (2023)" — because aligned seasons are different years."""
    stats = [s for s in (stats or []) if s] or ["home_run"]
    names = _names_for(db, player_ids)
    info = rookie_years(db, player_ids)

    plotted, skipped = [], []
    for pid in [int(p) for p in player_ids]:
        name = names.get(pid, str(pid))
        if info[pid]["censored"]:
            skipped.append(
                f"{name} debuted before the dataset begins — his rookie "
                f"season predates the covered years."
            )
        elif info[pid]["year"] is None:
            skipped.append(f"No rookie season found for {name}.")
        else:
            plotted.append((pid, name, info[pid]["year"]))

    values = _stat_values(db, [(pid, yr) for pid, _, yr in plotted], stats)
    series = []
    for stat in stats:
        data = []
        for pid, name, yr in plotted:
            v = values.get((pid, yr), {}).get(stat)
            if v is not None:
                data.append({"x": f"{name} ({yr})", "y": v})
        series.append({"id": stat, "data": data})

    lines = []
    if plotted:
        lines.append(
            "Rookie seasons compared: "
            + ", ".join(f"{name} ({yr})" for _, name, yr in plotted) + "."
        )
        lead_stat = stats[0]
        scored = [
            (name, yr, values.get((pid, yr), {}).get(lead_stat))
            for pid, name, yr in plotted
        ]
        scored = [t for t in scored if t[2] is not None]
        if len(scored) >= 2:
            scored.sort(key=lambda t: t[2], reverse=True)
            (n1, y1, v1), (n2, y2, v2) = scored[0], scored[1]
            lines.append(
                f"{n1} ({y1}) leads {stat_label(lead_stat)} at "
                f"{v1:g} vs {n2} ({y2}) at {v2:g}."
            )
    lines.extend(skipped)
    lines.extend(notes or [])

    meta = {
        "title": "Rookie Season Comparison — " + ", ".join(stat_label(s) for s in stats),
        "label_map": label_map_for(stats),
        "alignment": "rookie_season",
        "rookie_definition": ROOKIE_DEFINITION,
        "player_years": {name: yr for _, name, yr in plotted},
    }
    if skipped or notes:
        meta["warnings"] = skipped + list(notes or [])
    narration = " ".join(lines) if lines else "No rookie seasons to compare."

    # Mixed scales (21 HR next to a .209 average) make a single grouped bar
    # unreadable — multi-stat compares render as one facet per stat, each
    # with its own axis.
    if len(stats) > 1:
        facets = [
            {
                "title": stat_label(stat),
                "chart_type": "bar",
                "series": [s],
                "meta": {"label_map": label_map_for([stat]),
                         "y_label": stat_label(stat)},
            }
            for stat, s in zip(stats, series)
        ]
        return {
            "chart_type": "facet",
            "series": [],
            "facets": facets,
            "narration": narration,
            "meta": meta,
        }
    return {
        "chart_type": "bar",
        "series": series,
        "narration": narration,
        "meta": meta,
    }


def compare_first_n_seasons(db, player_ids, stat, n=3, notes=None):
    """First N observed seasons, aligned on career season number -> line.
    x = season 1..N, one series per player labeled "Name (startyear–)".
    Players whose debut predates the dataset are skipped (their observed
    season numbers would not be career season numbers)."""
    stat = stat or "home_run"
    n = max(1, int(n))
    names = _names_for(db, player_ids)
    idx = season_index_rows(db, player_ids)

    censored = {int(r["player_id"]) for r in idx if int(r["rookie_pre_panel"] or 0)}
    picked = {}  # pid -> [(season_number, year)]
    for r in idx:
        pid = int(r["player_id"])
        if pid in censored:
            continue
        if int(r["season_number"]) <= n:
            picked.setdefault(pid, []).append((int(r["season_number"]), int(r["year"])))

    pairs = [(pid, yr) for pid, lst in picked.items() for _, yr in lst]
    values = _stat_values(db, pairs, [stat])

    series, season_years = [], {}
    for pid in [int(p) for p in player_ids]:
        if pid not in picked:
            continue
        name = names.get(pid, str(pid))
        pts, yr_map = [], {}
        for sn, yr in sorted(picked[pid]):
            v = values.get((pid, yr), {}).get(stat)
            yr_map[sn] = yr
            if v is not None:
                pts.append({"x": sn, "y": v})
        start = min(yr_map.values()) if yr_map else None
        series.append({"id": f"{name} ({start}–)" if start else name, "data": pts})
        season_years[name] = yr_map

    skipped = [
        f"{names.get(pid, pid)} debuted before the dataset begins — career "
        f"season numbers unknown."
        for pid in [int(p) for p in player_ids] if pid in censored
    ]
    lines = []
    if series:
        lines.append(
            f"{stat_label(stat)} over each player's first {n} MLB seasons "
            f"(x-axis = career season number; actual years differ by player)."
        )
    lines.extend(skipped)
    lines.extend(notes or [])

    meta = {
        "title": f"{stat_label(stat)} — First {n} Seasons (career-aligned)",
        "label_map": label_map_for([stat]),
        "x_label": "Career season number",
        "y_label": stat_label(stat),
        "alignment": "career_season_number",
        "season_years": season_years,
    }
    if skipped or notes:
        meta["warnings"] = skipped + list(notes or [])
    return {
        "chart_type": "line",
        "series": series,
        "narration": " ".join(lines) if lines else "No aligned seasons to compare.",
        "meta": meta,
    }
