# backend/app/main.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.analytics import router as analytics_router
from .api.prompt import router as prompt_router
from .api.history import router as history_router

app = FastAPI(title="Sabermetric AI API")

# ---- CORS ----
raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
if raw:
    allow_origins = [o.strip() for o in raw.split(",") if o.strip()]
    allow_credentials = True
else:
    # Default for quick bring-up; tighten by setting CORS_ALLOW_ORIGINS in prod.
    # NOTE: with "*" credentials must be False (per spec).
    allow_origins = ["*"]
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],  # includes X-Session-Id, Authorization, etc.
)

# ---- Health ----
@app.get("/")
def root():
    return {"message": "Running (FastAPI)"}

@app.get("/health")
def health():
    return {"status": "ok"}

# ---- Routers ----
app.include_router(analytics_router)
app.include_router(prompt_router)
app.include_router(history_router)

# ---- Startup: ensure history tables exist (dev-friendly; idempotent) ----
@app.on_event("startup")
def _init_tables():
    # Import here so an install without history models still boots other routes.
    try:
        from .db.history_models import init_history_tables
        init_history_tables()
        print("[startup] history tables ensured.")
    except Exception as e:
        # Don't crash the app if auto-init fails (e.g., DB not reachable yet).
        print(f"[startup] history table init warning: {e}")
