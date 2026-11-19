"""
System Monitoring, Alerting & Reliability Engine.
Evaluates operational thresholds (API failures, DLQ backlogs, VRAM exhaustion, quota bounds)
and manages the alert lifecycle (ACTIVE, ACKNOWLEDGED, RESOLVED).
(Controls 05-07, 28, 42-43; Invariants 4, 7)
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from src.backend.models.entities import SystemAlertEvent, generate_uuid

logger = logging.getLogger("SalesAI.Alerting")


class AlertRule:
    def __init__(
        self,
        rule_id: str,
        name: str,
        source: str,
        severity: str,
        threshold: float,
        description_template: str
    ):
        self.rule_id = rule_id
        self.name = name
        self.source = source
        self.severity = severity
        self.threshold = threshold
        self.description_template = description_template

    def evaluate(self, current_value: float) -> bool:
        return current_value >= self.threshold


class AlertingService:
    # Standard operational alert rules
    STANDARD_RULES = [
        AlertRule("API_5XX_RATE", "High API Error Rate", "API", "CRITICAL", 5.0, "API 5xx error rate at {value:.1f}% (threshold: 5.0%)"),
        AlertRule("API_LATENCY_P95", "High P95 Latency", "API", "WARNING", 1000.0, "API p95 latency at {value:.0f}ms (threshold: 1000ms)"),
        AlertRule("WORKFLOW_DLQ_BACKLOG", "Workflow Dead-Letter Backlog", "WORKER", "CRITICAL", 20.0, "Workflow DLQ backlog contains {value:.0f} failed executions"),
        AlertRule("LLM_ERROR_RATE", "Model Inference Errors", "LLM", "CRITICAL", 3.0, "LLM inference error spike: {value:.0f} errors observed"),
        AlertRule("VOICE_SESSION_DROP", "Voice Session Failure Rate", "VOICE", "WARNING", 10.0, "Voice call drop rate at {value:.1f}%"),
        AlertRule("VRAM_EXHAUSTION", "GPU VRAM Utilization High", "LLM", "WARNING", 88.0, "GPU VRAM utilization at {value:.1f}% (threshold: 88%)")
    ]

    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def trigger_alert(
        self,
        alert_id: str,
        severity: str,
        source: str,
        title: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SystemAlertEvent:
        """Creates or updates an active alert event."""
        stmt = select(SystemAlertEvent).where(
            and_(
                SystemAlertEvent.tenant_id == self.tenant_id,
                SystemAlertEvent.alert_id == alert_id,
                SystemAlertEvent.status == "ACTIVE"
            )
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.description = description
            existing.metadata_json = metadata or {}
            await self.session.flush()
            return existing

        alert = SystemAlertEvent(
            id=generate_uuid(),
            tenant_id=self.tenant_id,
            alert_id=alert_id,
            severity=severity,
            source=source,
            title=title,
            description=description,
            metadata_json=metadata or {},
            status="ACTIVE",
            created_at=datetime.now(timezone.utc)
        )
        self.session.add(alert)
        await self.session.flush()
        logger.warning(f"Alert [{severity}] triggered for tenant {self.tenant_id}: {title}")
        return alert

    async def acknowledge_alert(self, alert_pk_id: str, user_id: str) -> Optional[SystemAlertEvent]:
        """Transitions an active alert to ACKNOWLEDGED state."""
        stmt = select(SystemAlertEvent).where(
            and_(
                SystemAlertEvent.tenant_id == self.tenant_id,
                SystemAlertEvent.id == alert_pk_id
            )
        )
        alert = (await self.session.execute(stmt)).scalar_one_or_none()
        if alert and alert.status == "ACTIVE":
            alert.status = "ACKNOWLEDGED"
            alert.acknowledged_by = user_id
            alert.acknowledged_at = datetime.now(timezone.utc)
            await self.session.flush()
            logger.info(f"Alert {alert_pk_id} acknowledged by user {user_id}")
            return alert
        return alert

    async def resolve_alert(self, alert_pk_id: str, user_id: Optional[str] = None) -> Optional[SystemAlertEvent]:
        """Transitions an alert to RESOLVED state."""
        stmt = select(SystemAlertEvent).where(
            and_(
                SystemAlertEvent.tenant_id == self.tenant_id,
                SystemAlertEvent.id == alert_pk_id
            )
        )
        alert = (await self.session.execute(stmt)).scalar_one_or_none()
        if alert and alert.status != "RESOLVED":
            alert.status = "RESOLVED"
            alert.resolved_at = datetime.now(timezone.utc)
            await self.session.flush()
            logger.info(f"Alert {alert_pk_id} resolved.")
            return alert
        return alert

    async def get_active_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns active and acknowledged alerts for the tenant dashboard."""
        stmt = select(SystemAlertEvent).where(
            and_(
                SystemAlertEvent.tenant_id == self.tenant_id,
                SystemAlertEvent.status.in_(["ACTIVE", "ACKNOWLEDGED"])
            )
        ).order_by(
            SystemAlertEvent.created_at.desc()
        ).limit(limit)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": a.id,
                "alert_id": a.alert_id,
                "severity": a.severity,
                "source": a.source,
                "title": a.title,
                "description": a.description,
                "status": a.status,
                "created_at": a.created_at.isoformat(),
                "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
                "metadata": a.metadata_json
            }
            for a in rows
        ]

    async def evaluate_operational_metrics(self, current_metrics: Dict[str, float]) -> List[SystemAlertEvent]:
        """Evaluates operational metrics dictionary against standard rules and triggers alerts."""
        triggered = []
        for rule in self.STANDARD_RULES:
            val = current_metrics.get(rule.rule_id)
            if val is not None and rule.evaluate(val):
                desc = rule.description_template.format(value=val)
                alert = await self.trigger_alert(
                    alert_id=rule.rule_id,
                    severity=rule.severity,
                    source=rule.source,
                    title=rule.name,
                    description=desc,
                    metadata={"current_value": val, "threshold": rule.threshold}
                )
                triggered.append(alert)
        return triggered
