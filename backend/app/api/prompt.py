# backend/app/api/prompt.py
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from ..db.database import get_db
from ..agent.nl2sql import build_summary, run_nl2sql  # NL→SQL planner/executor
from ..agent.prompt import (  # classic agent pipeline (planner → toolkit)
    run_prompt,
    resolve_single_player_id,
    all_player_names,
    extract_years,
    resolve_player_ids,          # new import for multi-name → ids
    canonical_stat_from_text,    # new import for stat canon from raw text
    normalize_stat,              # new import for alias-aware normalization
)
from ..toolkit.stats import career_arc, compare_players_by_season, stat_label
from ..toolkit.aligned import compare_first_n_seasons, compare_rookie_seasons
from .preflight import clarify_payload, coverage_note, gap_sentences, run_preflight
from .schemas import ChartResponse, PromptRequest


logger = logging.getLogger("app.prompt")

router = APIRouter(prefix="/api", tags=["prompt"])


def _clarified_compare(db, resolved_players, stats, years, execute_db=None):
    """Deterministic compare for clarified queries — after the user has
    clicked players AND stats, the query is fully determined; running an LLM
    would only add failure modes (the planner once answered a clarified
    Kershaw/Cole request with the agent's Hunter/Ortiz few-shot defaults).

    Builds one guarded SELECT per stat (table chosen from reflected columns:
    pitching_stats for p_-stats / all-pitcher comparisons), executes on the
    read-only role, and returns bar (single year), line (year range), or
    facets (multiple stats — mixed scales never share an axis).
    Returns None when nothing could be built so callers can fall through.
    """
    from sqlalchemy import text as sa_text
    from ..agent.nl2sql import reflect_table_columns
    from ..agent.sql_guard import SqlGuardError, guard_sql
    from ..db.database import readonly_session
    from ..toolkit.stats import label_map_for

    pitch_cols = set(reflect_table_columns(db, "pitching_stats"))
    bat_cols = set(reflect_table_columns(db, "batting_stats"))
    ids = [int(rp["player_id"]) for rp in resolved_players]
    names = {int(rp["player_id"]): rp["name"] for rp in resolved_players}
    all_pitchers = bool(resolved_players) and all(
        rp.get("role") == "pitcher" for rp in resolved_players)

    def table_for(stat):
        in_p, in_b = stat in pitch_cols, stat in bat_cols
        if in_p and not in_b:
            return "pitching_stats"
        if in_b and not in_p:
            return "batting_stats"
        if in_p and in_b:  # shared column name: role context decides
            return "pitching_stats" if all_pitchers else "batting_stats"
        return None

    id_list = ", ".join(str(i) for i in ids)
    year_clause = ""
    if len(years) == 1:
        year_clause = f" AND year = {int(years[0])}"
    elif len(years) >= 2:
        year_clause = f" AND year BETWEEN {int(min(years))} AND {int(max(years))}"
    single_year = len(years) == 1

    panels, note_lines, summary_bits = [], [], []
    for stat in stats:
        table = table_for(stat)
        if table is None:
            note_lines.append(f"No column found for {stat!r} — skipped.")
            continue
        sql = (
            f"SELECT full_name, year, {stat} FROM {table} "
            f"WHERE player_id IN ({id_list}){year_clause} "
            f"ORDER BY year ASC"
        )
        try:
            sql = guard_sql(sql)
        except SqlGuardError as e:  # identifiers come from reflection; belt+braces
            logger.warning("clarified compare rejected by guard: %s", e)
            continue
        if execute_db is not None:
            rows = execute_db.execute(sa_text(sql)).mappings().all()
        else:
            with readonly_session() as ro:
                rows = ro.execute(sa_text(sql)).mappings().all()

        label = stat_label(stat)
        seen_names = {r["full_name"] for r in rows if r[stat] is not None}
        for pid in ids:
            if names[pid] not in seen_names:
                where = f" in {int(years[0])}" if single_year else ""
                note_lines.append(f"No {label} for {names[pid]}{where}.")

        if single_year:
            data = [{"x": r["full_name"], "y": float(r[stat])}
                    for r in rows if r[stat] is not None]
            panels.append({"stat": stat, "chart_type": "bar",
                           "series": [{"id": stat, "data": data}]})
            vals = ", ".join(f"{p['x']} {p['y']:g}" for p in data)
            if vals:
                summary_bits.append(f"{label}: {vals}")
        else:
            by_player = {}
            for r in rows:
                if r[stat] is None:
                    continue
                by_player.setdefault(r["full_name"], []).append(
                    {"x": int(r["year"]), "y": float(r[stat])})
            series = [{"id": nm, "data": pts} for nm, pts in by_player.items()]
            panels.append({"stat": stat, "chart_type": "line", "series": series})
            if series:
                summary_bits.append(f"{label} by season")

    panels = [p for p in panels if any(s["data"] for s in p["series"])]
    if not panels:
        return None

    year_part = (f" — {int(years[0])}" if single_year
                 else f" — {int(min(years))}–{int(max(years))}" if years else "")
    title = (" vs ".join(names[i] for i in ids)
             + year_part + ": "
             + ", ".join(stat_label(p["stat"]) for p in panels))
    narration = " ".join(
        ["; ".join(summary_bits) + "." if summary_bits else ""] + note_lines
    ).strip()
    meta = {"title": title, "label_map": label_map_for([p["stat"] for p in panels])}
    if note_lines:
        meta["warnings"] = note_lines

    if len(panels) == 1:
        return {"chart_type": panels[0]["chart_type"],
                "series": panels[0]["series"],
                "narration": narration, "meta": meta,
                "ai_source": "deterministic"}
    return {
        "chart_type": "facet",
        "series": [],
        "facets": [
            {"title": stat_label(p["stat"]), "chart_type": p["chart_type"],
             "series": p["series"],
             "meta": {"label_map": label_map_for([p["stat"]]),
                      "y_label": stat_label(p["stat"])}}
            for p in panels
        ],
        "narration": narration, "meta": meta,
        "ai_source": "deterministic",
    }


def _detect_single_player_id(db, text: str) -> int | None:
    """
    Best-effort: return a single player_id if the prompt clearly refers to exactly one player.
    Strategy:
      1) Try resolving the whole prompt as a name (works for short queries like "Aaron Judge 2022–2025").
      2) Scan known player names and collect those mentioned in the prompt (case-insensitive).
         If exactly one hit, resolve and return its id.
    """
    try:
        t = " ".join((text or "").split()).strip()
        if not t:
            return None

        # Direct attempt (exact or fuzzy inside resolve_single_player_id)
        pid = resolve_single_player_id(db, t)
        if isinstance(pid, int):
            return pid

        # Single name present in text?
        low = t.lower()
        hits = [n for n in (all_player_names(db) or []) if n and n.lower() in low]
        if len(hits) == 1:
            pid = resolve_single_player_id(db, hits[0])
            return int(pid) if pid is not None else None
    except Exception:
        pass
    return None


def _players_mentioned(db, text: str) -> list[str]:
    """
    Return a de-duplicated list of known player names mentioned in `text` (case-insensitive substring match).
    """
    try:
        low = " ".join((text or "").lower().split())
        if not low:
            return []
        hits = []
        for name in (all_player_names(db) or []):
            if name and name.lower() in low:
                hits.append(name)
        # de-duplicate while preserving order (case-insensitive key)
        seen = set()
        uniq = []
        for n in hits:
            k = n.lower()
            if k not in seen:
                uniq.append(n)
                seen.add(k)
        return uniq
    except Exception:
        return []


@router.post("/prompt", response_model=ChartResponse)
async def prompt_endpoint(
    body: PromptRequest,
    db=Depends(get_db),
    route: Literal["auto", "sql", "agent"] = "auto",
    debug: bool = False,
):
    """
    Unified natural-language endpoint.

    Default behavior (route=auto), SQL-first:
      • Prefer NL→SQL for most prompts (leaderboards, filters, joins, single/multi-player ranges).
      • Forecast-y prompts (“project / predict / forecast / next season / over the next …”)
        go straight to the agent.
      • Smart fallback: if NL→SQL fails OR yields an empty/incorrect shape for a clear
        per-season timeline/compare, fall back to a deterministic SQL plan (no agent).

    Query params:
      • route=agent → force the classic agent route
      • route=sql   → force NL→SQL (uses deterministic SQL fallback before surfacing an error)
      • route=auto  → try NL→SQL first, else deterministic SQL fallback, else agent (default)
      • debug=1     → include planner/args metadata from the agent route
    """
    text = body.text

    # ---- Deterministic preflight: entities, stats, intent, coverage ----
    # Resolves every name mention BEFORE any LLM call; may return a
    # "clarify" payload (which player? which stats?) instead of a chart.
    pf = run_preflight(db, text, hints=body.hints)

    # ---- Non-baseball prompts: return graceful empty payload ----
    # (A recognized player name or stat is as strong a signal as the
    # keyword gate — "volpe vs lombard jr rookie season" must pass.)
    if not pf.gate_ok:
        return {
            "chart_type": "bar",
            "series": [{"id": "empty", "data": []}],
            "narration": "Please enter a baseball query.",
            "meta": {"title": "No baseball data"}
        }

    # ---- Ambiguity: ask instead of guessing ----
    if pf.questions:
        return clarify_payload(pf)

    gap_notes = gap_sentences(pf)
    cov_note = coverage_note(pf)

    def _annotate(res):
        """Append factual gap/coverage sentences to any outgoing payload."""
        notes = gap_notes + ([cov_note] if cov_note else [])
        if notes:
            res["narration"] = " ".join([res.get("narration") or ""] + notes).strip()
            meta = res.get("meta") or {}
            meta.setdefault("warnings", []).extend(notes)
            res["meta"] = meta
        return res

    # ---- Rookie / career-aligned comparisons: deterministic toolkit path ----
    # Season alignment must come from player_season_index, not from the
    # planner's world knowledge (it used to pick "Judge's rookie year" from
    # memory — right for stars, silently wrong for everyone else).
    # Scope: batting only. player_season_index derives eligibility from
    # career AB; pitcher rookie status is a 50-IP rule it cannot model.
    if (pf.rookie or pf.first_n) and (pf.ok_players or pf.gap_mentions):
        stats = pf.stats or ["home_run"]
        batting_stats_req = [s for s in stats if not s.startswith("p_")]
        rookie_notes = list(gap_notes)

        batting_ids = []
        for m in pf.ok_players:
            c = m.resolved
            # Role-based: NL-era pitchers have token batting rows, but a
            # "rookie season" comparison of Kershaw's 50-AB batting lines
            # is never what anyone means.
            if c.role == "pitcher":
                rookie_notes.append(
                    f"{c.name} is a pitcher — rookie-season alignment "
                    f"currently covers batting stats. "
                    f"Try \"{c.name} ERA by season\" instead."
                )
            else:
                batting_ids.append(c.player_id)

        if not batting_stats_req:
            # An all-pitching rookie ask ("compare X and Y ERA in their
            # rookie seasons") — say what's unsupported instead of faking it.
            msg = (
                "Rookie-season alignment currently covers batting stats only "
                "— pitcher rookie eligibility (the 50-inning rule) isn't "
                "modeled yet. Try a season query instead, e.g. "
                "\"ERA by season\" for each pitcher."
            )
            return {
                "chart_type": "bar",
                "series": [{"id": "empty", "data": []}],
                "narration": " ".join([msg] + rookie_notes),
                "meta": {"title": "Pitcher rookie comparison not supported",
                         "warnings": [msg] + rookie_notes},
                "ai_source": "preflight",
            }

        if batting_ids:
            if pf.first_n:
                res = compare_first_n_seasons(
                    db, batting_ids, batting_stats_req[0], n=pf.first_n,
                    notes=rookie_notes)
            else:
                res = compare_rookie_seasons(
                    db, batting_ids, batting_stats_req, notes=rookie_notes)
            res["ai_source"] = "toolkit"
            return res
        # Every named player is unchartable — explain, don't guess.
        return {
            "chart_type": "bar",
            "series": [{"id": "empty", "data": []}],
            "narration": " ".join(rookie_notes) or "No chartable players found.",
            "meta": {"title": "No data for those players",
                     "warnings": rookie_notes},
            "ai_source": "preflight",
        }

    # ---- Requested years entirely outside coverage: say so plainly ----
    if pf.years and pf.max_year and all(y > pf.max_year for y in pf.years):
        return {
            "chart_type": "bar",
            "series": [{"id": "empty", "data": []}],
            "narration": " ".join([cov_note] + gap_notes),
            "meta": {"title": "Outside data coverage",
                     "coverage": {"batting_stats": [pf.min_year, pf.max_year]}},
            "ai_source": "preflight",
        }

    # Resolved-entity hints for the SQL planner: verified ids, so the
    # planner filters on player_id instead of fuzzy ILIKE fragments; the
    # role steers pitchers to pitching_stats.
    resolved_players = [
        {"name": m.resolved.name, "player_id": int(m.resolved.player_id),
         "first_year": m.resolved.first_year, "last_year": m.resolved.last_year,
         "role": m.resolved.role}
        for m in pf.ok_players
    ]

    # Skip NL→SQL for forecast-y prompts
    tnorm = " ".join(text.lower().split())
    wants_forecast = any(k in tnorm for k in ("project", "predict", "forecast", "next season", "over the next"))

    # --- helpers ---
    def _payload_is_empty(res: dict) -> bool:
        if not isinstance(res, dict):
            return True
        if (res.get("chart_type") or "").lower() == "facet":
            facets = res.get("facets") or []
            if not facets:
                return True
            for f in facets:
                for s in (f or {}).get("series") or []:
                    if isinstance(s, dict) and s.get("data"):
                        return False
            return True
        series = res.get("series") or []
        if not series:
            return True
        return not any(isinstance(s, dict) and s.get("data") for s in series)

    def _canonical_stat(db_, txt: str) -> str | None:
        # Prefer precise canon from raw text; otherwise try common aliases
        s = canonical_stat_from_text(db_, txt)
        if s:
            return s
        t = " ".join((txt or "").lower().split())
        if "k%" in t or "strikeout percentage" in t or "k percent" in t or "k pct" in t:
            s = normalize_stat(db_, "k_percent")
            if s:
                return s
        return normalize_stat(db_, txt)

    # Hints for deterministic fallbacks
    years = extract_years(text) or []
    has_range = len(years) >= 2
    single_pid = _detect_single_player_id(db, text)
    multi_hits = _players_mentioned(db, text)

    def _deterministic_sql_fallback():
        """
        Build the obvious per-season query directly (no agent),
        so season-range prompts like “K% by season for Ronald Acuna Jr. 2019–2023”
        always return a line series.
        """
        if not has_range:
            return None
        stat = _canonical_stat(db, text) or "k_percent"
        start_year, end_year = int(years[0]), int(years[1])

        # Single player arc
        if single_pid:
            res = career_arc(db, single_pid, stat, start_year, end_year)
            res["ai_source"] = "sql_fallback"
            return res

        # Multi-player compare (names present in text)
        if multi_hits:
            pids = resolve_player_ids(db, multi_hits)
            if pids:
                res = compare_players_by_season(db, pids, stat, start_year=start_year, end_year=end_year)
                res["ai_source"] = "sql_fallback"
                return res
        return None

    # --- prefer NL→SQL unless explicitly agent or forecast ---
    prefer_sql = (route != "agent") and not wants_forecast
    force_sql = (route == "sql")

    def _payload_blob(res):
        # Narration/title included: a Marcel forecast names the player in
        # prose ("Aaron Judge is forecast to…"), not in its series ids.
        blob_parts = [str(res.get("narration") or ""),
                      str((res.get("meta") or {}).get("title") or "")]
        for s in res.get("series") or []:
            blob_parts.append(str(s.get("id") or ""))
            for p in (s.get("data") or []):
                blob_parts.append(str(p.get("x") or ""))
        return " ".join(blob_parts).lower()

    def _all_resolved_present(res):
        """Every preflight-resolved player must appear in the payload —
        a compare that silently drops a named player is a wrong answer."""
        if len(resolved_players) < 2:
            return True
        blob = _payload_blob(res)
        return all(
            rp["name"].split()[-1].lower() in blob for rp in resolved_players
        )

    def _none_resolved_present(res):
        """True when a payload contains NONE of the resolved players — the
        signature of a fabricated answer (e.g. the classic agent's
        Hunter/Ortiz few-shot defaults leaking into a Kershaw/Cole query)."""
        if not resolved_players:
            return False
        blob = _payload_blob(res)
        return not any(
            rp["name"].split()[-1].lower() in blob for rp in resolved_players
        )

    # ---- Clarified queries are fully determined: build the SQL ourselves ----
    # The user clicked the players AND the stats; involving the planner here
    # only adds failure modes. Facets keep multi-stat scales apart.
    picked_stats = list(body.hints.stats) if (body.hints and body.hints.stats) else []
    if picked_stats and resolved_players:
        res = _clarified_compare(db, resolved_players, picked_stats, pf.years)
        if res is not None:
            return _annotate(res)

    if prefer_sql or force_sql:
        try:
            result = run_nl2sql(db, text, resolved_players=resolved_players,
                                forced_stats=pf.stats)
            result["ai_source"] = "nl2sql"

            # For season-range + 1+ named players, ensure a time-series shape with data
            if has_range and (single_pid or len(multi_hits) >= 1):
                if result.get("chart_type") not in ("line", "facet") or _payload_is_empty(result):
                    raise ValueError("NL→SQL returned wrong/empty shape for a season arc/compare")
            elif _payload_is_empty(result):
                raise ValueError("NL→SQL produced empty results")

            if not _all_resolved_present(result):
                raise ValueError(
                    "NL→SQL result dropped a resolved player from a comparison")

            # The user picked stats explicitly (clarify chips) — the planner
            # may not pad the chart with extra columns at other scales, and
            # a result containing NONE of the picked stats is a wrong answer
            # (the planner substituted), never something to display.
            picked = set((body.hints.stats or [])) if body.hints else set()
            if picked:
                kept = [s for s in result.get("series") or []
                        if str(s.get("id")) in picked]
                if kept:
                    result["series"] = kept
                    # The narration was built from the unfiltered series —
                    # rebuild it so it describes what's actually charted.
                    result["narration"] = build_summary(
                        result.get("chart_type"), kept, x_key="",
                        y_key=sorted(picked), prompt_text=text)
                else:
                    labels = ", ".join(stat_label(s) for s in sorted(picked))
                    return _annotate({
                        "chart_type": "bar",
                        "series": [{"id": "empty", "data": []}],
                        "narration": (
                            f"Couldn't build a {labels} chart for this "
                            f"question — the data may not cover it (e.g. a "
                            f"season with no pitching appearances). Try "
                            f"asking directly, like "
                            f"\"<player> {labels.split(',')[0]} by season\"."
                        ),
                        "meta": {"title": "Requested stat unavailable"},
                        "ai_source": "preflight",
                    })

            return _annotate(result)
        except Exception as e:
            # Instead of erroring or dropping to agent, try a deterministic SQL fallback.
            # Log it: a silently-masked NL→SQL failure is how B1 went unnoticed.
            logger.info("NL2SQL path failed (%s); trying deterministic fallback", e)
            fallback = _deterministic_sql_fallback()
            if fallback:
                return _annotate(fallback)
            if force_sql:
                # Ensure JSON (not HTML) on hard failures in forced-SQL mode
                raise HTTPException(status_code=502, detail="NL→SQL failed and no SQL fallback matched this prompt.")

    # Classic agent route (last resort)
    try:
        result = run_prompt(db, text, debug=debug)
        result["ai_source"] = "agent"
        # The agent's rule fallback substitutes demo players when it cannot
        # parse a query — never show that for a query with known players.
        if _none_resolved_present(result):
            who = ", ".join(rp["name"] for rp in resolved_players)
            return _annotate({
                "chart_type": "bar",
                "series": [{"id": "empty", "data": []}],
                "narration": (
                    f"I couldn't build that chart for {who}. Try naming the "
                    f"stat directly — e.g. \"{resolved_players[0]['name']} "
                    f"ERA by season\" or \"compare ... home runs in 2024\"."
                ),
                "meta": {"title": "Couldn't build that comparison"},
                "ai_source": "preflight",
            })
        return _annotate(result)
    except Exception:
        logger.exception("Agent route failed")
        raise HTTPException(status_code=500, detail="Internal server error.")
