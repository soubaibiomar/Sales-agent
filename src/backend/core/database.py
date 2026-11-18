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
from sqlalchemy import text
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

    return create_async_engine(db_url, **engine_kwargs)

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
            # Set transactional local session variable in PostgreSQL
            await session.execute(
                text("SET LOCAL app.current_tenant_id = :tenant_id"),
                {"tenant_id": tenant_id}
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
                    text("SET LOCAL app.current_tenant_id = :tenant_id"),
                    {"tenant_id": active_tenant}
                )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            if active_tenant and session.bind and session.bind.dialect.name == "postgresql":
                try:
                    await session.execute(text("RESET app.current_tenant_id"))
                except Exception:
                    pass
