import logging
import logging.config

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from sqlalchemy import text

from app.config import get_settings
from app.db.database import engine
from app.limiter import limiter
from app.routers.admin import router as admin_router
from app.routers.finance import router as finance_router
from app.routers.health import router as health_router
from app.routers.registration import router as registration_router

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
})

logger = logging.getLogger(__name__)

settings = get_settings()

# ── Migraciones incrementales al arrancar ────────────────────────────────────
# Cada sentencia usa IF NOT EXISTS / DO NOTHING para ser idempotente.
# Añade aquí cualquier ALTER TABLE futuro; nunca borres los existentes.
_STARTUP_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMPTZ",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS tab_order TEXT",
]

def _run_startup_migrations() -> None:
    try:
        with engine.begin() as conn:
            for stmt in _STARTUP_MIGRATIONS:
                conn.execute(text(stmt))
        logger.info("Startup migrations OK (%d statements).", len(_STARTUP_MIGRATIONS))
    except Exception:
        logger.exception("Startup migration failed — check DB connection.")
        raise


app = FastAPI(
    title="Bot Finanzas API",
    version="2.0.0",
    on_startup=[_run_startup_migrations],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health_router)
app.include_router(registration_router)
app.include_router(finance_router)
app.include_router(admin_router)
