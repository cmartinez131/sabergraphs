# backend/app/api/prompt.py
from fastapi import APIRouter, Depends, HTTPException, Request

from ..db.database import get_db
from ..agent.nl2sql import run_nl2sql  # NL→SQL planner/executor
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
from ..agent.is_baseball_prompt import is_baseball_prompt


router = APIRouter(prefix="/api", tags=["prompt"])


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


@router.post("/prompt")
async def prompt_endpoint(request: Request, db=Depends(get_db)):
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
    body = await request.json()
    text = (body or {}).get("text")
    if not text or not isinstance(text, str):
        raise HTTPException(status_code=400, detail="Provide 'text' field (string).")
    
    # ---- Non-baseball prompts: return graceful empty payload ----
    if not is_baseball_prompt(text):
        return {
            "chart_type": "bar",
            "series": [{"id": "empty", "data": []}],
            "narration": "Please enter a baseball query.",
            "meta": {"title": "No baseball data"}
        }


    qp = request.query_params
    route = (qp.get("route") or "auto").lower()
    debug = qp.get("debug") in ("1", "true", "yes")

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

    if prefer_sql or force_sql:
        try:
            result = run_nl2sql(db, text)
            result["ai_source"] = "nl2sql"

            # For season-range + 1+ named players, ensure a time-series shape with data
            if has_range and (single_pid or len(multi_hits) >= 1):
                if result.get("chart_type") not in ("line", "facet") or _payload_is_empty(result):
                    raise ValueError("NL→SQL returned wrong/empty shape for a season arc/compare")
            elif _payload_is_empty(result):
                raise ValueError("NL→SQL produced empty results")

            return result
        except Exception:
            # Instead of erroring or dropping to agent, try a deterministic SQL fallback.
            fallback = _deterministic_sql_fallback()
            if fallback:
                return fallback
            if force_sql:
                # Ensure JSON (not HTML) on hard failures in forced-SQL mode
                raise HTTPException(status_code=502, detail="NL→SQL failed and no SQL fallback matched this prompt.")

    # Classic agent route (last resort)
    try:
        result = run_prompt(db, text, debug=debug)
        result["ai_source"] = "agent"
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
