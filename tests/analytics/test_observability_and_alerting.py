"""
Unit & Integration Tests for Observability, Telemetry & Alerting Engine (Step 11).
Validates OpenTelemetry-compatible TraceContext propagation, StructuredLogFormatter,
bounded-cardinality MetricsCollector, DependencyHealthChecker,
and AlertingService lifecycle management (ACTIVE -> ACKNOWLEDGED -> RESOLVED).
"""
import uuid
import json
import logging
import asyncio
import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.backend.models.entities import Base
from src.backend.core.observability import (
    TraceContext,
    StructuredLogFormatter,
    MetricsCollector,
    DependencyHealthChecker
)
from src.backend.core.alerting import AlertRule, AlertingService


@pytest.fixture(scope="module")
def alert_async_session():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_alerts_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _init_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_init_tables())

    return session_factory


def test_trace_context_propagation():
    """
    Validates trace context initialization, retrieval, and explicit propagation.
    """
    ctx = TraceContext.init_trace(tenant_id="t-telemetry-01", correlation_id="req-999")

    assert ctx["tenant_id"] == "t-telemetry-01"
    assert ctx["correlation_id"] == "req-999"
    assert len(ctx["trace_id"]) == 32
    assert len(ctx["span_id"]) == 16

    current = TraceContext.get_current_context()
    assert current["trace_id"] == ctx["trace_id"]
    assert current["span_id"] == ctx["span_id"]
    assert current["tenant_id"] == "t-telemetry-01"


def test_structured_json_log_formatter():
    """
    Validates that StructuredLogFormatter emits valid JSON with correlated OpenTelemetry IDs.
    """
    TraceContext.init_trace(tenant_id="t-log-test", correlation_id="corr-123")
    formatter = StructuredLogFormatter()

    record = logging.LogRecord(
        name="SalesAI.Test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Transaction processing complete",
        args=(),
        exc_info=None
    )

    formatted_log = formatter.format(record)
    parsed = json.loads(formatted_log)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "SalesAI.Test"
    assert parsed["message"] == "Transaction processing complete"
    assert parsed["tenant_id"] == "t-log-test"
    assert parsed["correlation_id"] == "corr-123"
    assert "timestamp" in parsed


def test_metrics_collector_bounded_cardinality():
    """
    Validates metrics registration, latency sampling, and bounded memory capacity.
    """
    collector = MetricsCollector()

    # Counter
    collector.increment_counter("sales.orders.created", value=1, labels={"status": "confirmed"})
    collector.increment_counter("sales.orders.created", value=2, labels={"status": "confirmed"})

    summary = collector.get_metrics_summary()
    assert any("sales.orders.created" in k for k in summary["counters"])

    # Latency sampling and ring-buffer bounding (max 500 samples per metric)
    for i in range(550):
        collector.record_latency("api.turn.latency", float(i), labels={"service": "voice"})

    key = ("api.turn.latency", json.dumps({"service": "voice"}, sort_keys=True))
    assert len(collector._latencies[key]) == 500, "Latency buffer must be bounded at 500 samples"

    # Distributed trace span recording (bounded at 200)
    for i in range(220):
        collector.record_trace_span(
            component="ModelGateway",
            operation="generate_response",
            duration_ms=45.2,
            status="OK"
        )
    assert len(collector._recent_traces) == 200, "Recent traces list must be bounded at 200 items"


def test_alert_rule_evaluation():
    """
    Validates AlertRule threshold condition evaluation.
    """
    rule = AlertRule(
        rule_id="API_5XX_RATE",
        name="High API Error Rate",
        source="API",
        severity="CRITICAL",
        threshold=5.0,
        description_template="API 5xx error rate at {value:.1f}%"
    )

    assert rule.evaluate(4.9) is False
    assert rule.evaluate(5.0) is True
    assert rule.evaluate(12.5) is True


@pytest.mark.asyncio
async def test_alerting_lifecycle_state_transitions(alert_async_session):
    """
    Validates full alert lifecycle in DB:
    ACTIVE -> ACKNOWLEDGED -> RESOLVED.
    """
    async with alert_async_session() as session:
        tenant_id = f"t_alt_{uuid.uuid4().hex[:6]}"
        service = AlertingService(session=session, tenant_id=tenant_id)

        # 1. Trigger Alert
        alert = await service.trigger_alert(
            alert_id="ALT-VRAM-001",
            severity="WARNING",
            source="LLM",
            title="GPU VRAM High Utilization",
            description="VRAM reached 89.2% utilization",
            metadata={"current_value": 89.2, "threshold_value": 88.0}
        )
        assert alert.alert_id == "ALT-VRAM-001"
        assert alert.status == "ACTIVE"
        assert alert.severity == "WARNING"

        # 2. Acknowledge Alert
        ack_alert = await service.acknowledge_alert(alert.id, user_id="sre_user_01")
        assert ack_alert is not None
        assert ack_alert.status == "ACKNOWLEDGED"

        # 3. Resolve Alert
        res_alert = await service.resolve_alert(alert.id)
        assert res_alert is not None
        assert res_alert.status == "RESOLVED"
