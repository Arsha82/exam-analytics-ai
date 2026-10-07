"""
Database engine and session factory.

Uses async SQLAlchemy with aiosqlite for local dev (SQLite)
and asyncpg for production (Postgres). Swap is config-driven.
"""

import asyncio
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    # Background jobs and requests write concurrently: wait for locks instead of failing.
    connect_args={"timeout": 30} if _is_sqlite else {},
)

if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        """SQLite ignores FOREIGN KEY / ON DELETE CASCADE unless asked; WAL lets reads run during writes."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields an async DB session per request."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _upgrade_to_head() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


async def init_db():
    """Bring the schema to the latest Alembic revision (runs on startup)."""
    await asyncio.to_thread(_upgrade_to_head)
