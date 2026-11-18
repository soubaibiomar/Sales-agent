"""
Database session management, connection pooling, and connection-pool context leakage prevention.
Guarantees that tenant context never leaks across recycled connections.
"""
import contextvars
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import (
    create_async_engine, async_sessionmaker, AsyncSession, AsyncEngine
)
from sqlalchemy import text, event
from src.backend.core.config import settings
from src.backend.models.entities import Base

# Context variable holding active tenant ID for current execution context
current_tenant_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_tenant_id", default=None
)

def create_engine_instance(url: Optional[str] = None) -> AsyncEngine:
    db_url = url or settings.database_url
    engine_kwargs = {
        "echo": False,
        "pool_pre_ping": True,
    }
    # Only pass pool sizing for non-sqlite
    if "sqlite" not in db_url:
        engine_kwargs["pool_size"] = 10
        engine_kwargs["max_overflow"] = 20

    eng = create_async_engine(db_url, **engine_kwargs)

    @event.listens_for(eng.sync_engine, "checkin")
    def _receive_connection_checkin(dbapi_connection, connection_record):
        """
        Global defense-in-depth: guarantees that any connection returned to the pool
        has its PostgreSQL tenant context wiped, even if an unhandled crash or custom query
        set a session-level GUC parameter.
        """
        if "postgresql" in db_url:
            try:
                cur = dbapi_connection.cursor()
                cur.execute("RESET app.current_tenant_id;")
                cur.close()
            except Exception:
                pass

    return eng

engine: AsyncEngine = create_engine_instance()
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def init_db(engine_override: Optional[AsyncEngine] = None):
    """Initializes schema tables."""
    eng = engine_override or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@asynccontextmanager
async def tenant_session(
    tenant_id: str,
    session_factory: Optional[async_sessionmaker] = None
) -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager that acquires an async session, applies tenant context,
    and guarantees the session variable is wiped upon return to pool.
    Prevents connection-pool tenant context leakage (Requirement 8).
    """
    factory = session_factory or AsyncSessionLocal
    token = current_tenant_id_ctx.set(tenant_id)
    session: AsyncSession = factory()
    
    try:
        # Check dialect
        bind = session.bind or engine
        dialect_name = bind.dialect.name
        
        if dialect_name == "postgresql":
            # Set transactional local session variable in PostgreSQL using injection-safe set_config
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)}
            )
        
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        # Guarantee session variable is reset and context variable restored
        try:
            bind = session.bind or engine
            if bind.dialect.name == "postgresql":
                await session.execute(text("RESET app.current_tenant_id"))
        except Exception:
            pass
        finally:
            await session.close()
            current_tenant_id_ctx.reset(token)

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection helper for FastAPI endpoints."""
    active_tenant = current_tenant_id_ctx.get()
    async with AsyncSessionLocal() as session:
        if active_tenant:
            bind = session.bind or engine
            if bind.dialect.name == "postgresql":
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(active_tenant)}
                )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            if session.bind and getattr(session.bind.dialect, "name", None) == "postgresql":
                try:
                    await session.execute(text("RESET app.current_tenant_id"))
                except Exception:
                    pass
