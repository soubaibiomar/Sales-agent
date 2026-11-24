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
                # The RESET opens a transaction on non-autocommit drivers (psycopg 3);
                # end it so the pooled connection is returned idle, not INTRANS.
                dbapi_connection.commit()
            except Exception:
                try:
                    dbapi_connection.rollback()
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

def _dialect_name(session: AsyncSession) -> str:
    bind = session.bind or engine
    return getattr(bind.dialect, "name", "")


async def bind_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """
    Binds a server-verified tenant to the current execution context and to the current
    PostgreSQL transaction. The GUC is transaction-local, so callers must re-bind after
    every COMMIT if they keep using the same session.
    Only call with a tenant established server-side (verified JWT, verified webhook
    signature, verified session token) - never with client-supplied identifiers.
    """
    current_tenant_id_ctx.set(tenant_id)
    if _dialect_name(session) == "postgresql":
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)}
        )


async def resolve_login_tenants(session: AsyncSession, email: str, tenant_id: Optional[str] = None) -> list:
    """
    Pre-authentication lookup (F-09). Under FORCE RLS the application role cannot see
    `users` without a tenant context, so PostgreSQL deployments resolve the candidate
    tenant(s) through the narrowly-scoped SECURITY DEFINER function
    `auth_resolve_login_tenants` (migration 011), which returns only tenant ids of
    active users with that email. Other dialects (SQLite tests) have no RLS.
    """
    if _dialect_name(session) == "postgresql":
        res = await session.execute(
            text("SELECT tenant_id FROM auth_resolve_login_tenants(:email, :tenant_id)"),
            {"email": email, "tenant_id": tenant_id}
        )
        return [row[0] for row in res.all()]
    from src.backend.models.entities import User
    from sqlalchemy import select
    stmt = select(User.tenant_id).where(User.email == email, User.is_active.is_(True))
    if tenant_id:
        stmt = stmt.where(User.tenant_id == tenant_id)
    res = await session.execute(stmt)
    return [row[0] for row in res.all()]


async def assert_rls_enforced_connection(eng: Optional[AsyncEngine] = None) -> Optional[str]:
    """
    F-09 startup guard: superusers and BYPASSRLS roles silently ignore Row-Level Security,
    even with FORCE ROW LEVEL SECURITY. Refuse such connections outside development;
    in development return a warning string so the operator is told explicitly.
    """
    eng = eng or engine
    if eng.dialect.name != "postgresql":
        if not settings.is_development:
            raise RuntimeError("Non-PostgreSQL database configured outside development: tenant RLS unavailable.")
        return f"Database dialect '{eng.dialect.name}' has no Row-Level Security (development only)."
    async with eng.connect() as conn:
        row = (await conn.execute(text(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ))).one()
    if row.rolsuper or row.rolbypassrls:
        msg = (f"Database role '{row.current_user}' bypasses Row-Level Security "
               f"(superuser={row.rolsuper}, bypassrls={row.rolbypassrls}). Use the least-privileged application role.")
        if not settings.is_development:
            raise RuntimeError(msg)
        return msg
    return None


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
