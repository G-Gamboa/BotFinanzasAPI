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
from app.routers.betting import router as betting_router
from app.routers.health import router as health_router
from app.routers.registration import router as registration_router
from app.routers.dashboard import router as dashboard_router
from app.routers.catalogs import router as catalogs_router
from app.routers.accounts import router as accounts_router
from app.routers.categories import router as categories_router
from app.routers.loan_people import router as loan_people_router
from app.routers.movements import router as movements_router
from app.routers.debts import router as debts_router
from app.routers.history import router as history_router
from app.routers.savings import router as savings_router
from app.routers.preferences import router as preferences_router
from app.routers.tc import router as tc_router

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
    # Betting tracker (admin-only, aislado de finanzas)
    """
    CREATE TABLE IF NOT EXISTS betting_bets (
        id         BIGSERIAL PRIMARY KEY,
        fecha      VARCHAR   NOT NULL,
        deporte    VARCHAR   NOT NULL,
        partido    VARCHAR   NOT NULL,
        pick       VARCHAR   NOT NULL,
        cuota      NUMERIC(8,2)  NOT NULL,
        stake      NUMERIC(10,2) NOT NULL,
        estado     VARCHAR   NOT NULL DEFAULT 'pendiente',
        ganancia   NUMERIC(10,2),
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS betting_config (
        id           INTEGER PRIMARY KEY DEFAULT 1,
        bank_inicial NUMERIC(10,2) NOT NULL DEFAULT 750,
        meta         NUMERIC(10,2) NOT NULL DEFAULT 20000,
        CONSTRAINT betting_config_singleton CHECK (id = 1)
    )
    """,
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
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health_router)
app.include_router(registration_router)
app.include_router(dashboard_router)
app.include_router(catalogs_router)
app.include_router(accounts_router)
app.include_router(categories_router)
app.include_router(loan_people_router)
app.include_router(movements_router)
app.include_router(debts_router)
app.include_router(history_router)
app.include_router(savings_router)
app.include_router(preferences_router)
app.include_router(tc_router)
app.include_router(admin_router)
app.include_router(betting_router)
