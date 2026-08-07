# backend/app/main.py
import logging
import os
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.analytics import router as analytics_router
from .api.prompt import router as prompt_router
from .api.history import router as history_router
from .api.backtest import router as backtest_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("app")

app = FastAPI(title="Sabermetric AI API")


# Unhandled errors: full traceback stays server-side; clients get a generic body.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


# Request-model validation errors: keep the API's historical 400 + single
# human-readable detail string (Pydantic's default is a 422 with an error array).
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    def _fmt(err):
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        msg = err.get("msg", "Invalid value")
        return f"{loc}: {msg}" if loc else msg

    detail = "; ".join(_fmt(e) for e in exc.errors()) or "Invalid request."
    return JSONResponse(status_code=400, content={"detail": detail})

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
app.include_router(backtest_router)

# ---- Startup: ensure history tables + read-only role exist (idempotent) ----
@app.on_event("startup")
def _init_tables():
    # Provision the SELECT-only role the NL->SQL path executes through.
    # Idempotent; also provisioned for fresh volumes by db/init/01-readonly-role.sh.
    try:
        from .db.database import ensure_readonly_role
        ensure_readonly_role()
        logger.info("[startup] read-only NL->SQL role ensured.")
    except Exception:
        # NL->SQL fails closed (falls back to deterministic SQL / agent)
        # until the role exists, so don't crash the app.
        logger.warning("[startup] read-only role init failed", exc_info=True)

    # Import here so an install without history models still boots other routes.
    try:
        from .db.history_models import init_history_tables
        init_history_tables()
        logger.info("[startup] history tables ensured.")
    except Exception:
        # Don't crash the app if auto-init fails (e.g., DB not reachable yet).
        logger.warning("[startup] history table init failed", exc_info=True)
