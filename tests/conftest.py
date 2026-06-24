"""
Configuración global de tests.

Las variables de entorno deben setearse ANTES de cualquier import de app.*
para que get_settings() (lru_cache) las tome correctamente.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN_NOT_REAL")
os.environ.setdefault("CRON_SECRET", "test-secret")
os.environ.setdefault("ADMIN_SECRET", "test-admin-secret")

# Limpia caché por si settings ya fue importado antes (ej. reloads de pytest)
from app.config import get_settings
get_settings.cache_clear()

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import Account, Category, User, UserSetting
from app.db.session import get_db
from app.dependencies import get_current_app_user


# ── SQLite: mapear BigInteger → INTEGER para que el autoincrement funcione ────
@compiles(BigInteger, "sqlite")
def _bi_sqlite(type_, compiler, **kw):
    return "INTEGER"


# ── Engine compartido por test ────────────────────────────────────────────────
# StaticPool fuerza que todas las sesiones usen la misma conexión subyacente.
# Sin esto, cada sesión nueva abre una conexión distinta y ve una BD vacía
# (SQLite :memory: es privada por conexión).

@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    """Sesión para setup de datos en tests directos de servicio."""
    SessionFactory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


# ── Fixtures de datos ─────────────────────────────────────────────────────────

@pytest.fixture
def test_user(db):
    now = datetime.now(timezone.utc)
    user = User(
        telegram_user_id=999_999_999,
        first_name="Test",
        last_name="User",
        is_active=True,
        can_use_loans=True,
        theme_key="neutral",
    )
    db.add(user)
    db.flush()

    db.add(UserSetting(
        user_id=user.id,
        preferred_currency="GTQ",
        usd_to_gtq=7.7,
        hide_amounts_default=False,
        show_amounts_default=False,
        default_tab="movimientos",
        theme_key="default",
        created_at=now,
        updated_at=now,
    ))
    db.commit()
    return user


@pytest.fixture
def user_accounts(db, test_user):
    """Cuentas mínimas para registrar movimientos."""
    efectivo = Account(
        user_id=test_user.id, name="Efectivo",
        account_type="cash", currency="GTQ",
        is_active=True, is_system=True, sort_order=1,
    )
    ahorro = Account(
        user_id=test_user.id, name="Ahorro",
        account_type="savings", currency="GTQ",
        is_active=True, is_system=True, sort_order=2,
    )
    db.add_all([efectivo, ahorro])
    db.commit()
    return {"efectivo": efectivo, "ahorro": ahorro}


@pytest.fixture
def user_categories(db, test_user):
    """Categorías mínimas para ingresos y egresos."""
    now = datetime.now(timezone.utc)
    salario = Category(
        user_id=test_user.id, name="Salario",
        kind="ING", is_active=True, is_system=False,
        sort_order=1, created_at=now, updated_at=now,
    )
    alimentacion = Category(
        user_id=test_user.id, name="Alimentación",
        kind="EGR", is_active=True, is_system=False,
        sort_order=1, created_at=now, updated_at=now,
    )
    db.add_all([salario, alimentacion])
    db.commit()
    return {"salario": salario, "alimentacion": alimentacion}


# ── TestClient con startup handlers desactivados ──────────────────────────────
# patch("app.main._run_startup_migrations") NO funciona porque on_startup ya
# tiene la referencia directa a la función; reemplazar el nombre en el módulo
# no afecta la lista. Limpiamos los handlers directamente.

@pytest.fixture
def client(db_engine, test_user):
    """TestClient con BD SQLite y auth de Telegram mockeada."""
    from app.main import app

    # Cada request crea su propia sesión desde el mismo engine (StaticPool)
    # para evitar que objetos SQLite se usen entre threads distintos.
    SessionFactory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def override_get_db():
        session = SessionFactory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_app_user] = lambda: test_user

    # Desactivar startup handlers que conectan a PostgreSQL de producción
    saved_startup = list(app.router.on_startup)
    app.router.on_startup.clear()

    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        app.router.on_startup[:] = saved_startup
