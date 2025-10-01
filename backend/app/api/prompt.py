# backend/app/api/prompt.py
from fastapi import APIRouter, Depends, HTTPException, Request
from ..db.database import get_db
from ..agent.prompt import run_prompt

router = APIRouter(prefix="/api", tags=["prompt"])

@router.post("/prompt")
async def prompt_endpoint(request: Request, db=Depends(get_db)):
    body = await request.json()
    text = (body or {}).get("text")
    if not text or not isinstance(text, str):
        raise HTTPException(status_code=400, detail="Provide 'text' field (string).")
    debug = request.query_params.get("debug") in ("1", "true", "yes")
    try:
        result = run_prompt(db, text, debug=debug)
        return result  # {chart_type, series, narration} (+ optional debug fields)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
