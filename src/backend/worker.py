"""
Platform background worker (inspection finding F-19).

Before this module nothing ever ran outside HTTP requests and tests: outbox events were
never relayed and expired stock reservations were never released. This process runs the
periodic durable jobs, per tenant, under Row-Level Security:

  * outbox relay      - OutboxService.dispatch_pending_events (SKIP LOCKED leases + fencing
                        tokens, so several worker processes can run safely in parallel);
  * reservation expiry - InventoryService.expire_stale_reservations (row locks);
  * data retention   - purge expired recordings/transcripts and voice security state.

Channel delivery: no WhatsApp/email/SMS provider is integrated yet. The default dispatcher
therefore reports failure, so events retry and dead-letter instead of being marked
DELIVERED without anything being sent. Register a real dispatcher with
`PlatformWorker(dispatcher=...)` when a provider exists.

Run:  python -m src.backend.worker            (loop)
      python -m src.backend.worker --once     (single cycle, e.g. cron / tests)
"""
import argparse
import asyncio
import logging
import signal
import uuid
from typing import Awaitable, Callable, Dict, Optional

from sqlalchemy import select

from src.backend.core.database import AsyncSessionLocal, bind_tenant_context, assert_rls_enforced_connection
from src.backend.domains.conversations.outbox import OutboxService
from src.backend.domains.inventory.service import InventoryService
from src.backend.models.entities import OutboxEvent, Tenant

logger = logging.getLogger("SalesAI.Worker")

Dispatcher = Callable[[OutboxEvent], Awaitable[bool]]


async def unconfigured_channel_dispatcher(event: OutboxEvent) -> bool:
    """Fails closed: nothing is reported as delivered until a real provider is registered."""
    raise RuntimeError(f"No outbound provider configured for channel '{event.channel_type}'.")


class PlatformWorker:
    def __init__(self, session_factory=None, dispatcher: Optional[Dispatcher] = None,
                 poll_interval_seconds: float = 5.0, worker_id: Optional[str] = None):
        self.session_factory = session_factory or AsyncSessionLocal
        self.dispatcher = dispatcher or unconfigured_channel_dispatcher
        self.poll_interval = poll_interval_seconds
        self.worker_id = worker_id or f"platform_worker_{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()

    async def _active_tenants(self):
        # `tenants` is the tenant registry itself and is not tenant-scoped.
        async with self.session_factory() as s:
            return [row[0] for row in (await s.execute(select(Tenant.id).where(Tenant.is_active.is_(True)))).all()]

    async def _relay_outbox(self, tenant_id: str) -> int:
        async with self.session_factory() as s:
            events = await OutboxService.dispatch_pending_events(
                session=s, tenant_id=tenant_id, dispatcher_callable=self.dispatcher, worker_id=self.worker_id
            )
            return len(events)

    async def _expire_reservations(self, tenant_id: str) -> int:
        async with self.session_factory() as s:
            await bind_tenant_context(s, tenant_id)
            count = await InventoryService(s).expire_stale_reservations(tenant_id=tenant_id)
            await s.commit()
            return count

    async def _apply_retention(self, tenant_id: str) -> int:
        """
        F-13 / AGENTS.md section 7: purge voice recordings past their retention date (90 days),
        transcripts older than the transcript retention (365 days), and expired voice
        security state (OTP challenges, action previews, telephony nonces).
        Recording *metadata* rows are deleted here; the audio objects themselves must be
        expired by the object store lifecycle policy (no storage client is integrated yet).
        """
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import delete
        from src.backend.core.config import settings
        from src.backend.models.entities import (
            VoiceRecording, VoiceTranscript, VoiceOtpChallenge, ManagerActionPreview, TelephonyReplayNonce
        )
        now = datetime.now(timezone.utc)
        transcript_cutoff = now - timedelta(days=settings.data_retention_days_transcripts)
        audio_cutoff = now - timedelta(days=settings.data_retention_days_audio)
        purged = 0
        async with self.session_factory() as s:
            await bind_tenant_context(s, tenant_id)
            for stmt in (
                delete(VoiceRecording).where(VoiceRecording.tenant_id == tenant_id,
                                             (VoiceRecording.expires_at < now) | (VoiceRecording.created_at < audio_cutoff)),
                delete(VoiceTranscript).where(VoiceTranscript.tenant_id == tenant_id, VoiceTranscript.created_at < transcript_cutoff),
                delete(VoiceOtpChallenge).where(VoiceOtpChallenge.tenant_id == tenant_id, VoiceOtpChallenge.expires_at < now),
                delete(ManagerActionPreview).where(ManagerActionPreview.tenant_id == tenant_id, ManagerActionPreview.expires_at < now),
                delete(TelephonyReplayNonce).where(TelephonyReplayNonce.tenant_id == tenant_id, TelephonyReplayNonce.expires_at < now),
            ):
                purged += (await s.execute(stmt)).rowcount or 0
            await s.commit()
        return purged

    async def run_cycle(self) -> Dict[str, int]:
        """One pass over every active tenant. A failure in one tenant never blocks the others."""
        totals = {"tenants": 0, "outbox_processed": 0, "reservations_expired": 0, "retention_purged": 0, "errors": 0}
        for tenant_id in await self._active_tenants():
            totals["tenants"] += 1
            for key, job in (("outbox_processed", self._relay_outbox),
                             ("reservations_expired", self._expire_reservations),
                             ("retention_purged", self._apply_retention)):
                try:
                    totals[key] += await job(tenant_id)
                except Exception as exc:  # noqa: BLE001 - logged and counted, cycle continues
                    totals["errors"] += 1
                    logger.error(f"[{self.worker_id}] {key} failed for tenant {tenant_id}: {exc}")
        return totals

    async def run_forever(self) -> None:
        logger.info(f"[{self.worker_id}] started (poll {self.poll_interval}s)")
        while not self._stop.is_set():
            totals = await self.run_cycle()
            if any(totals[k] for k in ("outbox_processed", "reservations_expired", "retention_purged", "errors")):
                logger.info(f"[{self.worker_id}] cycle: {totals}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass
        logger.info(f"[{self.worker_id}] stopped")

    def stop(self) -> None:
        self._stop.set()


async def _main(once: bool, poll: float) -> None:
    warning = await assert_rls_enforced_connection()
    if warning:
        logger.warning(f"[SECURITY] {warning}")
    worker = PlatformWorker(poll_interval_seconds=poll)
    if once:
        print(await worker.run_cycle())
        return
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except (NotImplementedError, RuntimeError):
            pass  # Windows: Ctrl+C raises KeyboardInterrupt instead
    await worker.run_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sales AI platform background worker")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--poll", type=float, default=5.0, help="seconds between cycles")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(_main(args.once, args.poll), loop_factory=asyncio.SelectorEventLoop)
    except KeyboardInterrupt:
        pass
