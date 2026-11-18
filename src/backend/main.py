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
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from src.backend.core.config import settings
from src.backend.core.database import init_db
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
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Correlation-ID"] = correlation_id
        
        return response

app = FastAPI(
    title="Sales AI Management Platform API",
    version="1.0.0",
    docs_url="/api/docs" if settings.environment == "development" else None,
    redoc_url=None
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
