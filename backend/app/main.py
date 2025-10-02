# backend/app/main.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.analytics import router as analytics_router
from .api.prompt import router as prompt_router

app = FastAPI(title="Sabermetric AI API")

# ---- CORS ----
raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
if raw:
    allow_origins = [o.strip() for o in raw.split(",") if o.strip()]
    allow_credentials = True
else:
    # Default for quick bring-up; tighten by setting CORS_ALLOW_ORIGINS in prod.
    # NOTE: when using "*", credentials must be False by spec.
    allow_origins = ["*"]
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
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
