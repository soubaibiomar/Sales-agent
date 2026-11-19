"""
Observability, Telemetry & Reliability API Router.
Exposes endpoints for system health, AI model metrics, voice pipeline benchmarks,
correlated trace spans, and operational alert management.
(Controls 05-07, 28, 42-43, 70; Invariants 4, 9)
"""
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext
from src.backend.core.observability import DependencyHealthChecker, MetricsCollector
from src.backend.core.alerting import AlertingService
from src.ai.model_observability import ModelObservabilityTracker
from src.ai.voice.voice_observability import VoiceObservabilityHarness

router = APIRouter(prefix="/observability", tags=["Observability"])


@router.get("/health")
async def get_system_health():
    """Returns deep health checks across PostgreSQL, Redis, MinIO, Ollama, and GPU VRAM."""
    return await DependencyHealthChecker.check_all_dependencies()


@router.get("/ai-metrics")
async def get_ai_metrics(
    ctx: SecurityContext = Depends(get_security_context)
):
    """Returns aggregated AI model telemetry, TTFT distributions, token burn, and recent execution turns."""
    tracker = ModelObservabilityTracker()
    return tracker.get_aggregated_model_metrics(tenant_id=ctx.tenant_id)


@router.get("/voice-metrics")
async def get_voice_metrics():
    """Returns voice turn latency profiles, VAD/ASR/TTS benchmarks, and barge-in stats."""
    return VoiceObservabilityHarness.run_benchmark_suite(iterations=10)


@router.get("/traces")
async def get_recent_traces(
    limit: int = Query(50, ge=1, le=200),
    ctx: SecurityContext = Depends(get_security_context)
):
    """Returns recent correlated OpenTelemetry trace spans with bounded cardinality."""
    collector = MetricsCollector()
    all_traces = collector.get_recent_traces(limit=limit)
    # Filter by tenant_id for multi-tenant isolation
    tenant_traces = [t for t in all_traces if t.get("tenant_id") in (ctx.tenant_id, "system")]
    return {
        "tenant_id": ctx.tenant_id,
        "count": len(tenant_traces),
        "traces": tenant_traces
    }


@router.get("/alerts")
async def get_system_alerts(
    limit: int = Query(50, ge=1, le=100),
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns active and historical system reliability alerts."""
    service = AlertingService(db, ctx.tenant_id)
    alerts = await service.get_active_alerts(limit=limit)
    return {
        "tenant_id": ctx.tenant_id,
        "active_alerts_count": len(alerts),
        "alerts": alerts
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Transitions an active alert to ACKNOWLEDGED state."""
    service = AlertingService(db, ctx.tenant_id)
    alert = await service.acknowledge_alert(alert_id, user_id=ctx.user_id)
    await db.commit()
    return {
        "status": "SUCCESS",
        "alert_id": alert_id,
        "new_status": alert.status if alert else "NOT_FOUND"
    }


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Transitions an active or acknowledged alert to RESOLVED state."""
    service = AlertingService(db, ctx.tenant_id)
    alert = await service.resolve_alert(alert_id, user_id=ctx.user_id)
    await db.commit()
    return {
        "status": "SUCCESS",
        "alert_id": alert_id,
        "new_status": alert.status if alert else "NOT_FOUND"
    }
