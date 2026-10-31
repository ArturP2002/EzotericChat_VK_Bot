"""Подключение SQLAlchemy и создание таблиц при старте."""

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        connect_args = {}
        # Тесты могут подставить sqlite:///:memory:
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def create_session() -> Session:
    """Новая сессия БД. Всегда берёт актуальную фабрику после get_engine()."""
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_columns(engine)


def _ensure_columns(engine) -> None:
    """create_all не добавляет колонки в уже существующие таблицы."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "pending_text" in columns:
        return
    dialect = engine.dialect.name
    stmt = "ALTER TABLE users ADD COLUMN pending_text TEXT"
    logger.info("Добавляю колонку users.pending_text (%s)", dialect)
    with engine.begin() as conn:
        conn.execute(text(stmt))


def get_session() -> Iterator[Session]:
    session = create_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
