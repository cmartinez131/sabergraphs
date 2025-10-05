# backend/app/api/prompt.py
from fastapi import APIRouter, Depends, HTTPException, Request
from ..db.database import get_db
from ..agent.prompt import run_prompt  # your existing planner → toolkit flow
from ..agent.nl2sql import run_nl2sql  # new: NL→SQL planner/executor

router = APIRouter(prefix="/api", tags=["prompt"])

@router.post("/prompt")
async def prompt_endpoint(request: Request, db=Depends(get_db)):
    """
    Option A (simple): Try NL→SQL first for ad-hoc filters/joins.
    - If NL→SQL is unsafe or fails, fall back to the existing agent planner.
    - If the user clearly asks for a projection/forecast, skip NL→SQL and go straight to the agent.

    Optional query params:
      - route=agent → force the classic agent route
      - route=sql   → force NL→SQL (errors bubble up)
      - route=auto  → default (try NL→SQL, else fallback)
      - debug=1     → include debug fields from the agent route when used
    """
    body = await request.json()
    text = (body or {}).get("text")
    if not text or not isinstance(text, str):
        raise HTTPException(status_code=400, detail="Provide 'text' field (string).")

    qp = request.query_params
    route = (qp.get("route") or "auto").lower()
    debug = qp.get("debug") in ("1", "true", "yes")

    # Light heuristic: skip NL→SQL for forecast-y prompts
    t = " ".join(text.lower().split())
    wants_forecast = any(k in t for k in ("project", "predict", "forecast", "next season", "over the next"))

    try_sql = (route == "sql") or (route == "auto" and not wants_forecast)

    if try_sql:
        try:
            result = run_nl2sql(db, text)
            # mark source for transparency
            result["ai_source"] = "nl2sql"
            return result
        except Exception:
            # Only fall back in auto-mode; in forced SQL mode we surface the error
            if route == "sql":
                raise

    # Classic agent route
    try:
        result = run_prompt(db, text, debug=debug)
        result["ai_source"] = "agent"
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
