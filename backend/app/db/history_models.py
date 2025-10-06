# backend/app/db/history_models.py
import os
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON as JSONType  # fallback when not on Postgres

from .database import Base, engine

USE_PG = bool(os.getenv("DATABASE_URL", "").startswith(("postgres://", "postgresql://")))
JSONCol = JSONB if USE_PG else JSONType

class Conversation(Base):
    __tablename__ = "conversations"

    # UUID hex ids from your router → strings
    id = Column(String(64), primary_key=True, index=True)
    session_id = Column(String(100), index=True, nullable=True)
    user_id = Column(String(100), index=True, nullable=True)
    title = Column(String(200), nullable=False, default="Conversation")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    entries = relationship(
        "ChartEntry",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChartEntry.created_at.asc()",
    )

class ChartEntry(Base):
    __tablename__ = "chart_entries"

    id = Column(String(64), primary_key=True, index=True)
    conversation_id = Column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    prompt = Column(Text, nullable=False)
    chart_type = Column(String(32), nullable=False)
    payload = Column(JSONCol, nullable=False)  # {chart_type, series/meta/narration/facets}
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    conversation = relationship("Conversation", back_populates="entries")

def init_history_tables():
    Base.metadata.create_all(bind=engine)
