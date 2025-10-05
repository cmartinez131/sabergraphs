# backend/app/api/prompt.py
from fastapi import APIRouter, Depends, HTTPException, Request

from ..db.database import get_db
from ..agent.nl2sql import run_nl2sql  # NL→SQL planner/executor
from ..agent.prompt import (  # classic agent pipeline (planner → toolkit)
    run_prompt,
    resolve_single_player_id,
    all_player_names,
    extract_years,
)

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

    Default behavior (route=auto):
      • Try NL→SQL first for ad-hoc filters/joins.
      • If NL→SQL fails or is skipped, fall back to the classic agent pipeline.
      • Explicit forecasts (“project / predict / forecast / next season / over the next …”)
        skip NL→SQL and go straight to the agent.

    Query params:
      • route=agent → force the classic agent route
      • route=sql   → force NL→SQL (errors bubble up)
      • route=auto  → try NL→SQL first, else fall back (default)
      • debug=1     → include planner/args metadata from the agent route
    """
    body = await request.json()
    text = (body or {}).get("text")
    if not text or not isinstance(text, str):
        raise HTTPException(status_code=400, detail="Provide 'text' field (string).")

    qp = request.query_params
    route = (qp.get("route") or "auto").lower()
    debug = qp.get("debug") in ("1", "true", "yes")

    # Skip NL→SQL for forecast-y prompts
    tnorm = " ".join(text.lower().split())
    wants_forecast = any(k in tnorm for k in ("project", "predict", "forecast", "next season", "over the next"))

    try_sql = (route == "sql") or (route == "auto" and not wants_forecast)

    # IMPORTANT UX GUARD:
    # If the prompt includes a year range AND
    #   (a) clearly names exactly one player (career arc), OR
    #   (b) clearly names two or more players (multi-line compare),
    # use the classic agent route which guarantees per-season series (for one or many players).
    if try_sql:
        years = extract_years(text) or []
        has_range = len(years) >= 2
        if has_range:
            single_pid = _detect_single_player_id(db, text)
            multi_hits = _players_mentioned(db, text)
            if single_pid or len(multi_hits) >= 2:
                try_sql = False  # force the agent route for this shape of request

    if try_sql:
        try:
            result = run_nl2sql(db, text)
            result["ai_source"] = "nl2sql"
            return result
        except Exception:
            # Only fall back in auto-mode; in forced SQL mode we surface the error.
            if route == "sql":
                raise

    # Classic agent route
    try:
        result = run_prompt(db, text, debug=debug)
        result["ai_source"] = "agent"
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
