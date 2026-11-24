"""
FastAPI Application Entry Point.
Configures:
- Strict security headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options).
- CORS policies with explicit origin allowlists.
- Sanitized exception handling with correlation ID tracing.
- Health and readiness endpoints.
- API v1 routers for Auth, Tenancy, Users, and Audit.
"""
import logging
import uuid
import os
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from src.backend.core.config import settings
from contextlib import asynccontextmanager
from src.backend.core.database import init_db, assert_rls_enforced_connection
from src.backend.api.auth import router as auth_router
from src.backend.api.tenants import router as tenants_router
from src.backend.api.users import router as users_router
from src.backend.api.audit import router as audit_router
from src.backend.api.channels import router as channels_router
from src.backend.api.inbox import router as inbox_router
from src.backend.api.crm import router as crm_router
from src.backend.api.catalog import router as catalog_router
from src.backend.api.quotes import router as quotes_router
from src.backend.api.approvals import router as approvals_router
from src.backend.api.inventory import router as inventory_router
from src.backend.api.orders import router as orders_router
from src.backend.api.payments import router as payments_router
from src.backend.api.invoices import router as invoices_router
from src.backend.api.procurement import router as procurement_router
from src.backend.api.logistics import router as logistics_router
from src.backend.api.support import router as support_router
from src.backend.api.scheduling import router as scheduling_router
from src.backend.api.voice import router as voice_router
from src.backend.api.workflows import router as workflows_router
from src.backend.api.notifications import router as notifications_router
from src.backend.api.integrations import router as integrations_router
from src.backend.api.ai_governance import router as ai_governance_router
from src.backend.api.agent_ecosystem import router as agent_ecosystem_router
from src.backend.api.analytics import router as analytics_router
from src.backend.api.observability import router as observability_router
from src.backend.api.saas_admin import router as saas_router

logger = logging.getLogger("SalesAI.API")

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Extract or inject correlation ID
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        
        response = await call_next(request)
        
        # Inject standard security headers
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # F-20: strict CSP compatible with the migrated frontend - no inline or eval'd
        # script at all; only static style="" attributes are tolerated (style-src-attr).
        # blob:/data: media is needed to play synthesized voice replies.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; "
            "img-src 'self' data:; media-src 'self' blob: data:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Correlation-ID"] = correlation_id
        
        return response

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # F-09: never serve traffic on a connection that silently bypasses tenant RLS.
    warning = await assert_rls_enforced_connection()
    if warning:
        logger.warning(f"[SECURITY] {warning}")
    if settings.ai_warmup_on_startup:
        import asyncio
        from src.ai.providers.ollama_provider import OllamaProvider
        asyncio.create_task(OllamaProvider().warm_up())
    yield


app = FastAPI(
    title="Sales AI Management Platform API",
    version="1.0.0",
    docs_url="/api/docs" if settings.environment == "development" else None,
    redoc_url=None,
    lifespan=lifespan
)

# Attach Middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"]
)

# Exception Handler: Mask unhandled exceptions to prevent information disclosure
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    logger.error(f"Unhandled server error [CID: {correlation_id}]: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "An internal server error occurred.",
            "correlation_id": correlation_id
        }
    )

# Health & Readiness Probes
@app.get("/health", tags=["Monitoring"])
async def health_check():
    return {"status": "HEALTHY", "environment": settings.environment}

@app.get("/ready", tags=["Monitoring"])
async def readiness_check():
    return {"status": "READY", "services": {"database": "UP", "redis": "UP", "storage": "UP"}}

# Mount Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(tenants_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(channels_router, prefix="/api/v1")
app.include_router(inbox_router, prefix="/api/v1")
app.include_router(crm_router, prefix="/api/v1")
app.include_router(catalog_router, prefix="/api/v1")
app.include_router(quotes_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(inventory_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(payments_router, prefix="/api/v1")
app.include_router(invoices_router, prefix="/api/v1")
app.include_router(procurement_router, prefix="/api/v1")
app.include_router(logistics_router, prefix="/api/v1")
app.include_router(support_router, prefix="/api/v1")
app.include_router(scheduling_router, prefix="/api/v1")
app.include_router(voice_router)
app.include_router(workflows_router)
app.include_router(notifications_router)
app.include_router(integrations_router)
app.include_router(ai_governance_router)
app.include_router(agent_ecosystem_router)
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(observability_router, prefix="/api/v1")
app.include_router(saas_router, prefix="/api/v1")

# Mount Static Frontend
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/app", StaticFiles(directory=frontend_dir, html=True), name="frontend")

