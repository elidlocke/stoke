"""Postgres connection: one async engine per process, and sessions from it."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure(url: str | None = None, *, null_pool: bool = False) -> None:
    """(Re)create the engine. Tests pass null_pool, since each test runs on its own event loop."""
    global _engine, _sessionmaker
    kwargs = {"poolclass": NullPool} if null_pool else {"pool_pre_ping": True}
    _engine = create_async_engine(url or get_settings().database_url, **kwargs)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        configure()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose() -> None:
    if _engine is not None:
        await _engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: a session for the request."""
    async with sessionmaker()() as session:
        yield session
