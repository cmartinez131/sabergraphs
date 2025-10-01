# backend/app/main.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.analytics import router as analytics_router
from .api.prompt import router as prompt_router

app = FastAPI(title="Sabermetric AI API")

# CORS: configure via env for prod. Example:
# CORS_ALLOW_ORIGINS="https://your-frontend.vercel.app,https://yourdomain.com"
_raw = os.getenv("CORS_ALLOW_ORIGINS", "")
_allow_origins = [o.strip() for o in _raw.split(",") if o.strip()]
if not _allow_origins:
    # Safe default for quick bring-up; tighten in production by setting CORS_ALLOW_ORIGINS
    _allow_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "Running (FastAPI)"}

@app.get("/health")
def health():
    return {"status": "ok"}

# include routers
app.include_router(analytics_router)
app.include_router(prompt_router)
