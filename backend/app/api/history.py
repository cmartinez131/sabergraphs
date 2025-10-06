# backend/app/api/history.py
"""Endpoints for saving, listing, reading, and deleting recent charts."""
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session
from uuid import uuid4
from datetime import datetime

from ..db.database import get_db
from ..db.history_models import Conversation, ChartEntry

router = APIRouter(prefix="/api/history", tags=["history"])

def _uid():
    return uuid4().hex

def _now():
    return datetime.utcnow()

def _actor(request: Request, session_id_header: str = Header(default="", alias="X-Session-Id")):
    """
    Determine the acting identity.
    - If you have auth later: extract user_id from JWT/cookie here.
    - For now: no auth, so rely on X-Session-Id.
    Returns dict like {"user_id": "u123"} or {"session_id": "abc"}.
    """
    sid = (session_id_header or "").strip()
    if not sid:
        raise HTTPException(400, "Missing X-Session-Id")
    return {"session_id": sid}

@router.post("/log")
async def log_history(request: Request, db: Session = Depends(get_db), actor=Depends(_actor)):
    """
    Body: { "prompt": str, "payload": { chart_type, series?, meta?, narration?, facets? }, "conversation_id"?: str, "title"?: str }
    Creates or appends to a conversation owned by this actor (user or session).
    """
    body = await request.json()
    prompt = (body or {}).get("prompt") or ""
    payload = (body or {}).get("payload") or {}
    conv_id = (body or {}).get("conversation_id") or ""
    title = (body or {}).get("title") or ""

    if not prompt or not isinstance(prompt, str):
        raise HTTPException(400, "Missing 'prompt'")
    if not isinstance(payload, dict) or not payload.get("chart_type"):
        raise HTTPException(400, "Missing/invalid 'payload'")

    # Load or create conversation
    conv = None
    if conv_id:
        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        if not conv:
            raise HTTPException(404, "conversation_id not found")
        # ownership check
        if "user_id" in actor and (conv.user_id != actor["user_id"]):
            raise HTTPException(403, "Forbidden")
        if "session_id" in actor and (conv.session_id != actor["session_id"]):
            raise HTTPException(403, "Forbidden")
    else:
        conv = Conversation(
            id=_uid(),
            title=(title.strip() or payload.get("meta", {}).get("title") or prompt[:80]),
            created_at=_now(), updated_at=_now(),
            user_id=actor.get("user_id"),
            session_id=actor.get("session_id")
        )
        db.add(conv)
        db.flush()  # get conv.id

    # Add entry
    entry = ChartEntry(
        id=_uid(),
        conversation_id=conv.id,
        prompt=prompt,
        chart_type=str(payload.get("chart_type")),
        payload=payload,
        created_at=_now()
    )
    conv.updated_at = _now()
    db.add(entry)
    db.commit()
    return {"conversation_id": conv.id, "entry_id": entry.id}

@router.get("/recent")
def recent_conversations(limit: int = 20, db: Session = Depends(get_db), actor=Depends(_actor)):
    q = db.query(Conversation)
    if "user_id" in actor:
        q = q.filter(Conversation.user_id == actor["user_id"])
    else:
        q = q.filter(Conversation.session_id == actor["session_id"])
    rows = q.order_by(Conversation.updated_at.desc()).limit(max(1, min(limit, 100))).all()
    return [
        {"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat() + "Z"}
        for c in rows
    ]

@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, db: Session = Depends(get_db), actor=Depends(_actor)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(404, "Not found")
    if "user_id" in actor and conv.user_id != actor["user_id"]:
        raise HTTPException(403, "Forbidden")
    if "session_id" in actor and conv.session_id != actor["session_id"]:
        raise HTTPException(403, "Forbidden")

    entries = (db.query(ChartEntry)
                 .filter(ChartEntry.conversation_id == conv.id)
                 .order_by(ChartEntry.created_at.asc())
                 .all())
    return {
        "id": conv.id,
        "title": conv.title,
        "updated_at": conv.updated_at.isoformat() + "Z",
        "entries": [
            {
                "id": e.id,
                "prompt": e.prompt,
                "chart_type": e.chart_type,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() + "Z",
            }
            for e in entries
        ],
    }

@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, db: Session = Depends(get_db), actor=Depends(_actor)):
    """Delete a conversation (and its entries) owned by this session/user."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(404, "Not found")
    if "user_id" in actor and conv.user_id != actor["user_id"]:
        raise HTTPException(403, "Forbidden")
    if "session_id" in actor and conv.session_id != actor["session_id"]:
        raise HTTPException(403, "Forbidden")

    db.delete(conv)  # cascades to ChartEntry via FK + relationship
    db.commit()
    return {"deleted": True, "conversation_id": conversation_id}

@router.post("/claim_session")
async def claim_session(request: Request, db: Session = Depends(get_db)):
    """
    Stub for a future authenticated flow to migrate anonymous sessions.
    """
    body = await request.json()
    session_id = (body or {}).get("session_id") or ""
    if not session_id:
        raise HTTPException(400, "Missing 'session_id'")

    user_id = None
    if not user_id:
        raise HTTPException(401, "Authentication required")

    q = db.query(Conversation).filter(Conversation.session_id == session_id)
    count = 0
    for conv in q.all():
        conv.user_id = user_id
        conv.session_id = None
        conv.updated_at = _now()
        count += 1
    db.commit()
    return {"migrated": count}
