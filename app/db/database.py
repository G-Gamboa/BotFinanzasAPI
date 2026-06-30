from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    # psycopg3 crea prepared statements por conexión; con connection pooling
    # la misma conexión puede reutilizarse y el statement ya existirá → error.
    # prepare_threshold=None desactiva la preparación automática.
    connect_args={"prepare_threshold": None},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
