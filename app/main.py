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
from app.routers.ws import router as ws_router
from app.routers.budget import router as budget_router
from app.routers.vault import router as vault_router
from app.routers.bootstrap import router as bootstrap_router
from app.routers.calendar import router as calendar_router

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
    # Préstamos desde TC
    "ALTER TABLE movements ADD COLUMN IF NOT EXISTS is_third_party BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS source_tc_account_id BIGINT REFERENCES accounts(id)",
    # Presupuesto mensual por categoría
    """
    CREATE TABLE IF NOT EXISTS budgets (
        id          BIGSERIAL PRIMARY KEY,
        user_id     BIGINT NOT NULL REFERENCES users(id),
        category_id BIGINT NOT NULL REFERENCES categories(id),
        monthly_amount NUMERIC(14,2) NOT NULL,
        UNIQUE (user_id, category_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_budgets_user_id ON budgets (user_id)",
    # Vault zero-knowledge
    """
    CREATE TABLE IF NOT EXISTS vault_config (
        id          BIGSERIAL PRIMARY KEY,
        user_id     BIGINT NOT NULL UNIQUE REFERENCES users(id),
        salt        TEXT NOT NULL,
        dek_wrapped TEXT NOT NULL,
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        updated_at  TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vault_items (
        id         BIGSERIAL PRIMARY KEY,
        user_id    BIGINT NOT NULL REFERENCES users(id),
        ciphertext TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_vault_items_user_id ON vault_items(user_id)",
    # Visacuotas: plan de préstamo TC + categoría propia
    "ALTER TABLE cc_installment_plans ADD COLUMN IF NOT EXISTS is_loan BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE cc_installment_plans ADD COLUMN IF NOT EXISTS loan_person_id BIGINT REFERENCES loan_people(id)",
    "ALTER TABLE cc_installment_plans ADD COLUMN IF NOT EXISTS category_id BIGINT REFERENCES categories(id)",
    # Calendario: programados, estado por fecha, notas y marca de cargas iniciales
    """
    CREATE TABLE IF NOT EXISTS scheduled_items (
        id          BIGSERIAL PRIMARY KEY,
        user_id     BIGINT NOT NULL REFERENCES users(id),
        kind        TEXT NOT NULL,
        concept     TEXT NOT NULL,
        amount      NUMERIC(14,2),
        currency    TEXT NOT NULL DEFAULT 'GTQ',
        start_date  DATE,
        recurrence  TEXT NOT NULL DEFAULT 'none',
        end_date    DATE,
        note        TEXT,
        account_id  BIGINT REFERENCES accounts(id),
        category_id BIGINT REFERENCES categories(id),
        payment_method TEXT,
        credit_card_account_id BIGINT REFERENCES accounts(id),
        is_active   BOOLEAN NOT NULL DEFAULT TRUE,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_scheduled_items_user ON scheduled_items (user_id, is_active)",
    """
    CREATE TABLE IF NOT EXISTS scheduled_occurrences (
        id          BIGSERIAL PRIMARY KEY,
        item_id     BIGINT NOT NULL REFERENCES scheduled_items(id),
        user_id     BIGINT NOT NULL REFERENCES users(id),
        due_date    DATE,
        status      TEXT NOT NULL DEFAULT 'pending',
        amount      NUMERIC(14,2),
        record_type TEXT,
        record_id   BIGINT,
        done_at     TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_scheduled_occ_user ON scheduled_occurrences (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_scheduled_occ_item ON scheduled_occurrences (item_id)",
    """
    CREATE TABLE IF NOT EXISTS calendar_notes (
        id         BIGSERIAL PRIMARY KEY,
        user_id    BIGINT NOT NULL REFERENCES users(id),
        text       TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_seeds (
        key        TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
]

async def _store_event_loop() -> None:
    import asyncio
    from app.ws.manager import set_event_loop
    set_event_loop(asyncio.get_event_loop())


def _run_startup_migrations() -> None:
    try:
        with engine.begin() as conn:
            for stmt in _STARTUP_MIGRATIONS:
                conn.execute(text(stmt))
        logger.info("Startup migrations OK (%d statements).", len(_STARTUP_MIGRATIONS))
    except Exception:
        logger.exception("Startup migration failed — check DB connection.")
        raise


def _run_calendar_seed() -> None:
    from app.calendar_seed import seed_admin_calendar
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        seed_admin_calendar(db)
    except Exception:
        db.rollback()
        logger.exception("No se pudo aplicar la carga inicial del calendario.")
    finally:
        db.close()


app = FastAPI(
    title="Bot Finanzas API",
    version="2.0.0",
    on_startup=[_store_event_loop, _run_startup_migrations, _run_calendar_seed],
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
app.include_router(ws_router)
app.include_router(admin_router)
app.include_router(budget_router)
app.include_router(vault_router)
app.include_router(bootstrap_router)
app.include_router(calendar_router)
