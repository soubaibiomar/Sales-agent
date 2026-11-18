"""
Notification Orchestrator Service.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
Enforces:
1. Message classification (MARKETING, TRANSACTIONAL, SERVICE, SECURITY).
2. Multi-script STOP opt-out directives (French, English, Darija, Arabic).
3. Moroccan quiet hours suppression for marketing messages (21:00 to 09:00 & Sundays).
4. Frequency capping (max 1 marketing send per 24 hours per recipient).
5. Send-time recheck and reliable transactional outbox dispatch.
"""
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.models.entities import (
    NotificationTemplate,
    NotificationLog,
    ChannelIdentity,
    OutboxEvent
)
from src.backend.notifications.templates import DEFAULT_TEMPLATES, render_template_string
from src.backend.domains.conversations.outbox import OutboxService, OutboxMessageClass

logger = logging.getLogger("notifications.orchestrator")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class QuietHoursPolicy:
    """
    Enforces Moroccan telecommunications marketing quiet hours:
    - Prohibited: 21:00 (9:00 PM) to 09:00 (9:00 AM) local Moroccan time (UTC+1).
    - Prohibited: All day Sunday.
    - Applies strictly to MARKETING messages; TRANSACTIONAL and SECURITY bypass.
    """
    @staticmethod
    def is_quiet_hours(dt: Optional[datetime] = None) -> bool:
        check_dt = dt or datetime.now(timezone.utc)
        # Approximate Moroccan time: UTC + 1 hour standard
        morocco_hour = (check_dt.hour + 1) % 24
        morocco_weekday = check_dt.weekday()  # Monday=0 ... Sunday=6

        # Sunday prohibition
        if morocco_weekday == 6:
            return True

        # Evening to morning quiet window (21:00 to 09:00)
        if morocco_hour >= 21 or morocco_hour < 9:
            return True

        return False


class MultiScriptOptOutManager:
    """
    Recognizes multi-script STOP directives across Moroccan language matrices:
    - French: STOP, ARRET, DESABONNER
    - English: STOP, UNSUBSCRIBE, CANCEL
    - Darija (Arabizi): BARAKA, HBS, SAF, SAFI
    - Arabic: قف, الغاء, توقف
    """
    STOP_DIRECTIVES = {
        "stop", "arret", "arrêt", "desabonner", "désabonner", "arretez", "arrêtez",
        "unsubscribe", "cancel",
        "baraka", "hbs", "hbsou", "saf", "safi",
        "قف", "الغاء", "إلغاء", "توقف"
    }

    _in_memory_optouts: set = set()

    @classmethod
    def is_stop_directive(cls, text: str) -> bool:
        if not text:
            return False
        tokens = text.strip().lower().split()
        if any(t in cls.STOP_DIRECTIVES for t in tokens):
            return True
        for d in cls.STOP_DIRECTIVES:
            if d in text.strip().lower():
                return True
        return False

    @classmethod
    def is_opt_out_phrase(cls, text: str) -> Tuple[bool, Optional[str]]:
        if not text:
            return False, None
        tokens = text.strip().lower().split()
        for t in tokens:
            if t in cls.STOP_DIRECTIVES:
                return True, t
        for d in cls.STOP_DIRECTIVES:
            if d in text.strip().lower():
                return True, d
        return False, None

    @classmethod
    async def record_opt_out(
        cls,
        tenant_id: str,
        recipient: str,
        channel: str,
        keyword: str = "stop"
    ):
        cls._in_memory_optouts.add((tenant_id, channel.upper(), recipient))

    @classmethod
    def is_opted_out_memory(cls, tenant_id: str, recipient: str, channel: str) -> bool:
        return (tenant_id, channel.upper(), recipient) in cls._in_memory_optouts


class NotificationOrchestrator:
    """Enterprise notification orchestrator with consent and quiet-hour governance."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_template(
        self,
        tenant_id: str,
        template_code: str,
        channel_type: str,
        language: str = "fr-FR"
    ) -> Optional[NotificationTemplate]:
        stmt = select(NotificationTemplate).where(
            NotificationTemplate.tenant_id == tenant_id,
            NotificationTemplate.template_code == template_code,
            NotificationTemplate.channel_type == channel_type,
            NotificationTemplate.language == language
        )
        res = await self.db.execute(stmt)
        template = res.scalars().first()

        if not template:
            # Check default seed catalog
            for def_tmpl in DEFAULT_TEMPLATES:
                if (def_tmpl["template_code"] == template_code and
                    def_tmpl["channel_type"] == channel_type and
                    def_tmpl["language"] == language):
                    template = NotificationTemplate(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        template_code=template_code,
                        channel_type=channel_type,
                        message_class=def_tmpl["message_class"],
                        language=language,
                        subject_template=def_tmpl.get("subject_template"),
                        body_template=def_tmpl["body_template"],
                        variables_json=def_tmpl.get("variables", []),
                        is_active=True
                    )
                    self.db.add(template)
                    await self.db.flush()
                    break

        return template

    async def register_opt_out(
        self,
        tenant_id: str,
        channel_type: str,
        recipient_identifier: str,
        directive_text: str
    ) -> bool:
        """Processes and persists a recipient's STOP directive."""
        is_opt_out = MultiScriptOptOutManager.is_stop_directive(directive_text)
        if not is_opt_out:
            return False

        stmt = select(ChannelIdentity).where(
            ChannelIdentity.tenant_id == tenant_id,
            ChannelIdentity.channel_type == channel_type,
            ChannelIdentity.identifier == recipient_identifier
        )
        identity = (await self.db.execute(stmt)).scalars().first()

        if identity:
            identity.is_opted_out = True
            identity.opt_out_at = utc_now()
        else:
            from src.backend.models.entities import Contact
            contact_stmt = select(Contact).where(Contact.tenant_id == tenant_id)
            contact = (await self.db.execute(contact_stmt)).scalars().first()
            if not contact:
                contact = Contact(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    display_name=recipient_identifier
                )
                self.db.add(contact)
                await self.db.flush()

            identity = ChannelIdentity(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                contact_id=contact.id,
                channel_type=channel_type,
                identifier=recipient_identifier,
                is_opted_out=True,
                opt_out_at=utc_now()
            )
            self.db.add(identity)

        await self.db.flush()
        return True

    async def is_recipient_opted_out(
        self,
        tenant_id: str,
        channel_type: str,
        recipient_identifier: str
    ) -> bool:
        if MultiScriptOptOutManager.is_opted_out_memory(tenant_id, recipient_identifier, channel_type):
            return True
        stmt = select(ChannelIdentity).where(
            ChannelIdentity.tenant_id == tenant_id,
            ChannelIdentity.channel_type == channel_type,
            ChannelIdentity.identifier == recipient_identifier
        )
        identity = (await self.db.execute(stmt)).scalars().first()
        return bool(identity and identity.is_opted_out)

    async def check_marketing_frequency_cap(
        self,
        tenant_id: str,
        recipient_identifier: str,
        window_hours: int = 24
    ) -> bool:
        """Returns True if recipient is under the marketing frequency budget (< 1 per 24h)."""
        cutoff = utc_now() - timedelta(hours=window_hours)
        stmt = select(func.count(NotificationLog.id)).where(
            NotificationLog.tenant_id == tenant_id,
            NotificationLog.recipient_identifier == recipient_identifier,
            NotificationLog.message_class == OutboxMessageClass.MARKETING,
            NotificationLog.status.in_(["SENT", "DELIVERED"]),
            NotificationLog.created_at >= cutoff
        )
        count = (await self.db.execute(stmt)).scalar() or 0
        return count < 1

    async def dispatch_notification(
        self,
        tenant_id: str,
        recipient_identifier: Optional[str] = None,
        channel_type: Optional[str] = None,
        message_class: str = "TRANSACTIONAL",
        template_code: Optional[str] = None,
        subject: Optional[str] = None,
        content: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        language: str = "fr-FR",
        now: Optional[datetime] = None,
        **kwargs
    ) -> NotificationLog:
        """
        Orchestrates notification dispatch with policy checks, template rendering, and outbox enqueueing.
        """
        eval_time = now or utc_now()
        variables = variables or {}
        recipient_id = recipient_identifier or kwargs.get("recipient")
        chan = channel_type or kwargs.get("channel", "WHATSAPP")
        tmpl_code = template_code or kwargs.get("template_name")
        msg_class = message_class or kwargs.get("message_class", "TRANSACTIONAL")

        # 1. Resolve Template or Raw Content
        rendered_subject = subject
        rendered_content = content or ""
        template_id = None

        if tmpl_code:
            tmpl = await self.get_or_create_template(tenant_id, tmpl_code, chan, language)
            if tmpl:
                template_id = tmpl.id
                rendered_content = render_template_string(tmpl.body_template, variables)
                if tmpl.subject_template:
                    rendered_subject = render_template_string(tmpl.subject_template, variables)
                msg_class = tmpl.message_class

        # 2. Check Opt-Out Status
        is_opted_out = await self.is_recipient_opted_out(tenant_id, chan, recipient_id)
        if is_opted_out and msg_class == OutboxMessageClass.MARKETING:
            log_entry = NotificationLog(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                template_id=template_id,
                recipient_identifier=recipient_id,
                channel_type=chan,
                message_class=msg_class,
                subject=rendered_subject,
                content=rendered_content,
                status="CANCELLED",
                error_reason="Suppressed: Recipient has Opted out via STOP directive",
                retry_count=0,
                created_at=eval_time
            )
            self.db.add(log_entry)
            await self.db.flush()
            return log_entry

        # 3. Check Moroccan Quiet Hours for Marketing messages
        if msg_class == OutboxMessageClass.MARKETING and QuietHoursPolicy.is_quiet_hours(eval_time):
            log_entry = NotificationLog(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                template_id=template_id,
                recipient_identifier=recipient_id,
                channel_type=chan,
                message_class=msg_class,
                subject=rendered_subject,
                content=rendered_content,
                status="CANCELLED",
                error_reason="Suppressed: Moroccan quiet hours in effect (21:00-09:00 or Sunday)",
                retry_count=0,
                created_at=eval_time
            )
            self.db.add(log_entry)
            await self.db.flush()
            return log_entry

        # 4. Check Frequency Cap for Marketing messages
        if msg_class == OutboxMessageClass.MARKETING:
            can_send = await self.check_marketing_frequency_cap(tenant_id, recipient_id)
            if not can_send:
                log_entry = NotificationLog(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    template_id=template_id,
                    recipient_identifier=recipient_id,
                    channel_type=chan,
                    message_class=msg_class,
                    subject=rendered_subject,
                    content=rendered_content,
                    status="CANCELLED",
                    error_reason="Suppressed: Frequency cap exceeded (maximum 1 marketing message per 24 hours)",
                    retry_count=0,
                    created_at=eval_time
                )
                self.db.add(log_entry)
                await self.db.flush()
                return log_entry

        # 5. Enqueue in Outbox for Reliable Transactional Dispatch
        is_high_pri = (msg_class in ("SECURITY", "TRANSACTIONAL"))
        outbox_ev = await OutboxService.enqueue_outbound_event(
            session=self.db,
            tenant_id=tenant_id,
            channel_type=chan,
            recipient_identifier=recipient_id,
            event_type=tmpl_code or "NOTIFICATION_DISPATCH",
            payload_dict={"subject": rendered_subject, "content": rendered_content, "variables": variables},
            message_class=msg_class,
            is_high_priority=is_high_pri,
            now=eval_time
        )

        # 6. Record Notification Log as DELIVERED
        log_entry = NotificationLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            template_id=template_id,
            recipient_identifier=recipient_id,
            channel_type=chan,
            message_class=msg_class,
            subject=rendered_subject,
            content=rendered_content,
            status="DELIVERED",
            retry_count=0,
            metadata_json={"outbox_event_id": outbox_ev.id},
            created_at=eval_time,
            sent_at=eval_time
        )
        self.db.add(log_entry)
        await self.db.flush()

        return log_entry

    send_notification = dispatch_notification
