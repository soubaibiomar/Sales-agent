"""
Payment Domain Service & Sandbox Adapter.
Handles Payment Intent Lifecycle, Cryptographic Webhook HMAC Signatures,
Payment Deduplication, Independent Reconciliation, and Safe Refund Authorization.
(Controls 31, 32, 48, 57, 58, 59; SAI-07, SAI-08)
Step 05: Sprint 3 - Transact
"""
import hmac
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.backend.models.entities import (
    PaymentIntent, PaymentTransaction, RefundRequest, SalesOrder,
    InboundRawEvent, AuditEvent
)
from src.backend.domains.orders.service import OrderService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PaymentError(Exception):
    pass


class InvalidWebhookSignatureError(PaymentError):
    pass


class DuplicateWebhookEventError(PaymentError):
    pass


class PaymentFailedError(PaymentError):
    pass


class RefundExceedsPaidAmountError(PaymentError):
    pass


class UnauthorizedRefundError(PaymentError):
    pass


class PaymentService:
    def __init__(self, db: AsyncSession, order_service: Optional[OrderService] = None):
        self.db = db
        self.order_service = order_service or OrderService(db)

    @staticmethod
    def verify_webhook_signature(
        raw_payload: str,
        signature: str,
        secret: str
    ) -> bool:
        """
        Cryptographically verifies HMAC-SHA256 signature for inbound payment webhooks.
        Rejects tampered or unauthenticated payloads (Control 31).
        """
        if not signature or not secret:
            return False

        computed = hmac.new(
            secret.encode("utf-8"),
            raw_payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(computed.lower(), signature.lower())

    async def create_payment_intent(
        self,
        tenant_id: str,
        order_id: str,
        provider: str = "STRIPE_SANDBOX",
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> PaymentIntent:
        # Idempotency check
        if idempotency_key:
            stmt = select(PaymentIntent).where(
                and_(
                    PaymentIntent.tenant_id == tenant_id,
                    PaymentIntent.idempotency_key == idempotency_key
                )
            )
            res = await self.db.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                return existing

        order_stmt = select(SalesOrder).where(
            and_(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        )
        order_res = await self.db.execute(order_stmt)
        order = order_res.scalar_one_or_none()
        if not order:
            raise PaymentError(f"Order {order_id} not found")

        if order.status not in ("PENDING_PAYMENT", "PAYMENT_AUTHORIZED"):
            raise PaymentError(f"Cannot create payment intent for order in status {order.status}")

        provider_intent_id = f"pi_test_{uuid.uuid4().hex[:16]}"
        client_secret = f"{provider_intent_id}_secret_{uuid.uuid4().hex[:8]}"

        intent = PaymentIntent(
            tenant_id=tenant_id,
            order_id=order.id,
            provider=provider.upper(),
            provider_intent_id=provider_intent_id,
            client_secret=client_secret,
            amount_cents=order.grand_total_cents,
            currency=order.currency,
            status="REQUIRES_PAYMENT_METHOD",
            idempotency_key=idempotency_key,
            metadata_json=json.dumps(metadata or {})
        )
        self.db.add(intent)
        await self.db.flush()
        return intent

    async def confirm_payment_intent(
        self,
        tenant_id: str,
        intent_id: str,
        payment_method_token: str = "tok_sandbox_valid_card",
        payment_method_type: str = "CARD",
        idempotency_key: Optional[str] = None
    ) -> PaymentTransaction:
        # Lock intent
        stmt = select(PaymentIntent).where(
            and_(PaymentIntent.id == intent_id, PaymentIntent.tenant_id == tenant_id)
        ).with_for_update()
        res = await self.db.execute(stmt)
        intent = res.scalar_one_or_none()
        if not intent:
            raise PaymentError("Payment intent not found")

        if intent.status == "SUCCEEDED":
            # Idempotent return of existing successful transaction
            tx_stmt = select(PaymentTransaction).where(
                and_(
                    PaymentTransaction.payment_intent_id == intent.id,
                    PaymentTransaction.tenant_id == tenant_id,
                    PaymentTransaction.status == "SUCCESS"
                )
            )
            tx_res = await self.db.execute(tx_stmt)
            existing_tx = tx_res.scalar_one_or_none()
            if existing_tx:
                return existing_tx

        # Evaluate sandbox token
        if payment_method_token == "tok_sandbox_fail_card":
            intent.status = "FAILED"
            tx = PaymentTransaction(
                tenant_id=tenant_id,
                payment_intent_id=intent.id,
                order_id=intent.order_id,
                transaction_type="CAPTURE",
                amount_cents=intent.amount_cents,
                currency=intent.currency,
                provider_transaction_id=f"tx_fail_{uuid.uuid4().hex[:12]}",
                payment_method_type=payment_method_type,
                status="FAILED",
                raw_response_json='{"error": "card_declined", "code": "insufficient_funds"}'
            )
            self.db.add(tx)
            await self.db.flush()
            raise PaymentFailedError("Payment card was declined in sandbox simulation")

        # Success path
        provider_tx_id = f"tx_{uuid.uuid4().hex[:16]}"
        receipt_url = f"https://payments.sales-ai.local/receipts/{provider_tx_id}.pdf"

        intent.status = "SUCCEEDED"
        tx = PaymentTransaction(
            tenant_id=tenant_id,
            payment_intent_id=intent.id,
            order_id=intent.order_id,
            transaction_type="CAPTURE",
            amount_cents=intent.amount_cents,
            currency=intent.currency,
            provider_transaction_id=provider_tx_id,
            payment_method_type=payment_method_type,
            status="SUCCESS",
            receipt_url=receipt_url,
            raw_response_json='{"status": "succeeded", "captured": true}'
        )
        self.db.add(tx)

        # Transition order to PAID and commit stock holds
        order_stmt = select(SalesOrder).where(SalesOrder.id == intent.order_id).with_for_update()
        order_res = await self.db.execute(order_stmt)
        order = order_res.scalar_one()

        await self.order_service.mark_order_paid(
            tenant_id=tenant_id,
            order_id=order.id,
            expected_version=order.version,
            transaction_id=provider_tx_id
        )

        await self.db.flush()
        return tx

    async def process_webhook_event(
        self,
        tenant_id: str,
        provider: str,
        raw_payload_str: str,
        signature: str,
        webhook_secret: str,
        timestamp: Optional[int] = None,
        require_timestamp: bool = False,
        tolerance_seconds: int = 300,
        require_amount_match: bool = False
    ) -> Dict[str, Any]:
        """
        Processes verified inbound payment webhook callbacks.
        Guarantees deduplication, cryptographic signature verification,
        and authoritative state transition (Controls 31, 32, 59).
        """
        # 1. Cryptographic HMAC verification
        # F-02: when a timestamp is used it is part of the signed message ("<ts>.<body>"),
        # so it cannot be altered, and stale deliveries are rejected.
        if require_timestamp and timestamp is None:
            raise InvalidWebhookSignatureError("Missing signed webhook timestamp")
        if timestamp is not None:
            import time as _time
            if abs(int(_time.time()) - int(timestamp)) > tolerance_seconds:
                raise InvalidWebhookSignatureError("Webhook timestamp outside tolerance window (replay protection)")
            signed_message = f"{int(timestamp)}.{raw_payload_str}"
        else:
            signed_message = raw_payload_str
        if not self.verify_webhook_signature(signed_message, signature, webhook_secret):
            raise InvalidWebhookSignatureError("Inbound webhook HMAC signature verification failed")

        payload = json.loads(raw_payload_str)
        event_id = payload.get("event_id") or payload.get("id")
        event_type = payload.get("event_type") or payload.get("type")

        if not event_id:
            raise PaymentError("Missing event identifier in payment webhook")

        # 2. Replay Deduplication via inbound_raw_events
        dedup_stmt = select(InboundRawEvent).where(
            and_(
                InboundRawEvent.tenant_id == tenant_id,
                InboundRawEvent.channel_type == f"PAYMENT_{provider.upper()}",
                InboundRawEvent.provider_event_id == event_id
            )
        )
        dedup_res = await self.db.execute(dedup_stmt)
        if dedup_res.scalar_one_or_none():
            return {"status": "duplicate_ignored", "event_id": event_id}

        raw_event = InboundRawEvent(
            tenant_id=tenant_id,
            channel_type=f"PAYMENT_{provider.upper()}",
            provider_event_id=event_id,
            payload_json=raw_payload_str,
            signature_verified=True,
            processing_status="PROCESSED"
        )
        self.db.add(raw_event)

        # 3. Handle Event Types
        if event_type == "payment_intent.succeeded":
            provider_intent_id = payload.get("provider_intent_id") or payload.get("data", {}).get("id")
            stmt = select(PaymentIntent).where(
                and_(
                    PaymentIntent.tenant_id == tenant_id,
                    PaymentIntent.provider_intent_id == provider_intent_id
                )
            ).with_for_update()
            res = await self.db.execute(stmt)
            intent = res.scalar_one_or_none()
            if intent and require_amount_match:
                # F-02: the provider-reported amount/currency must match the intent exactly.
                data_obj = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
                data_obj = data_obj.get("object", data_obj) if isinstance(data_obj.get("object"), dict) else data_obj
                reported_amount = payload.get("amount_cents", data_obj.get("amount"))
                reported_currency = (payload.get("currency") or data_obj.get("currency") or "").upper()
                if reported_amount is None or int(reported_amount) != int(intent.amount_cents):
                    raise PaymentError("Webhook amount does not match the payment intent amount")
                if reported_currency and reported_currency != (intent.currency or "").upper():
                    raise PaymentError("Webhook currency does not match the payment intent currency")
            if intent and intent.status != "SUCCEEDED":
                intent.status = "SUCCEEDED"
                provider_tx_id = f"tx_wh_{uuid.uuid4().hex[:12]}"

                tx = PaymentTransaction(
                    tenant_id=tenant_id,
                    payment_intent_id=intent.id,
                    order_id=intent.order_id,
                    transaction_type="CAPTURE",
                    amount_cents=intent.amount_cents,
                    currency=intent.currency,
                    provider_transaction_id=provider_tx_id,
                    payment_method_type="WEBHOOK_CAPTURED",
                    status="SUCCESS",
                    receipt_url=f"https://payments.sales-ai.local/receipts/{provider_tx_id}.pdf",
                    raw_response_json=raw_payload_str
                )
                self.db.add(tx)

                order_stmt = select(SalesOrder).where(SalesOrder.id == intent.order_id).with_for_update()
                order_res = await self.db.execute(order_stmt)
                order = order_res.scalar_one()

                await self.order_service.mark_order_paid(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    expected_version=order.version,
                    transaction_id=provider_tx_id
                )

        elif event_type == "payment_intent.payment_failed":
            provider_intent_id = payload.get("provider_intent_id") or payload.get("data", {}).get("id")
            stmt = select(PaymentIntent).where(
                and_(
                    PaymentIntent.tenant_id == tenant_id,
                    PaymentIntent.provider_intent_id == provider_intent_id
                )
            ).with_for_update()
            res = await self.db.execute(stmt)
            intent = res.scalar_one_or_none()
            if intent:
                intent.status = "FAILED"

        await self.db.flush()
        return {"status": "processed", "event_id": event_id, "event_type": event_type}

    async def create_refund_request(
        self,
        tenant_id: str,
        order_id: str,
        amount_cents: int,
        reason: str,
        requested_by_user_id: Optional[str] = None,
        idempotency_key: Optional[str] = None
    ) -> RefundRequest:
        if amount_cents <= 0:
            raise PaymentError("Refund amount must be greater than zero")

        # Lock the order so concurrent refund requests are serialised (F-03).
        order_stmt = select(SalesOrder).where(
            and_(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        ).with_for_update()
        order_res = await self.db.execute(order_stmt)
        order = order_res.scalar_one_or_none()
        if not order:
            raise PaymentError("Order not found")

        # Idempotency: replaying the same key returns the original request; reusing it
        # for different terms is rejected (F-03).
        if idempotency_key:
            existing = (await self.db.execute(select(RefundRequest).where(and_(
                RefundRequest.tenant_id == tenant_id,
                RefundRequest.idempotency_key == idempotency_key
            )))).scalars().first()
            if existing:
                if existing.order_id == order.id and existing.amount_cents == amount_cents:
                    return existing
                raise PaymentError("Idempotency key already used for a different refund request")

        if order.payment_status not in ("PAID", "PARTIALLY_REFUNDED"):
            raise PaymentError(f"Cannot refund order with payment_status {order.payment_status}. Must be PAID.")

        if amount_cents > order.grand_total_cents:
            raise RefundExceedsPaidAmountError(
                f"Refund amount {amount_cents} cents exceeds order total {order.grand_total_cents} cents"
            )

        # Cumulative ceiling: open + completed refunds can never exceed the paid amount (F-03).
        already_committed = await self._committed_refund_cents(tenant_id, order.id)
        if already_committed + amount_cents > order.grand_total_cents:
            raise RefundExceedsPaidAmountError(
                f"Refund amount {amount_cents} cents plus existing refunds {already_committed} cents "
                f"exceeds order total {order.grand_total_cents} cents"
            )

        refund = RefundRequest(
            tenant_id=tenant_id,
            order_id=order.id,
            amount_cents=amount_cents,
            currency=order.currency,
            reason=reason,
            status="REQUESTED",
            requested_by_user_id=requested_by_user_id,
            idempotency_key=idempotency_key
        )
        self.db.add(refund)
        await self.db.flush()
        return refund

    async def _committed_refund_cents(
        self, tenant_id: str, order_id: str,
        statuses: tuple = ("REQUESTED", "APPROVED", "COMPLETED")
    ) -> int:
        from sqlalchemy import func
        total = (await self.db.execute(
            select(func.coalesce(func.sum(RefundRequest.amount_cents), 0)).where(and_(
                RefundRequest.tenant_id == tenant_id,
                RefundRequest.order_id == order_id,
                RefundRequest.status.in_(statuses)
            ))
        )).scalar()
        return int(total or 0)

    async def approve_and_process_refund(
        self,
        tenant_id: str,
        refund_id: str,
        approved_by_user_id: str,
        step_up_mfa_verified: bool = False
    ) -> RefundRequest:
        # Step-up MFA authorization enforcement (Control 15, SAI-08)
        if not step_up_mfa_verified:
            raise UnauthorizedRefundError("Step-up MFA verification required to approve financial refunds")

        stmt = select(RefundRequest).where(
            and_(RefundRequest.id == refund_id, RefundRequest.tenant_id == tenant_id)
        ).with_for_update()
        res = await self.db.execute(stmt)
        refund = res.scalar_one_or_none()
        if not refund:
            raise PaymentError("Refund request not found")

        if refund.status != "REQUESTED":
            return refund

        # Four-eyes principle: the requester can never approve their own refund (F-03).
        if refund.requested_by_user_id and refund.requested_by_user_id == approved_by_user_id:
            raise UnauthorizedRefundError("Segregation of duties: a refund cannot be approved by its requester")

        # Defence in depth: re-check the cumulative ceiling at approval time.
        order_lock = (await self.db.execute(
            select(SalesOrder).where(SalesOrder.id == refund.order_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        )).scalar_one()
        completed = await self._committed_refund_cents(tenant_id, refund.order_id, statuses=("COMPLETED",))
        if completed + refund.amount_cents > order_lock.grand_total_cents:
            raise RefundExceedsPaidAmountError(
                f"Approving would refund {completed + refund.amount_cents} cents, "
                f"exceeding order total {order_lock.grand_total_cents} cents"
            )

        # NOTE: no payment provider is integrated; the provider refund id below is still
        # simulated. A real provider refund call must happen before COMPLETED in production.
        provider_refund_id = f"re_{uuid.uuid4().hex[:16]}"
        refund.status = "COMPLETED"
        refund.approved_by_user_id = approved_by_user_id
        refund.provider_refund_id = provider_refund_id

        # Record refund transaction
        tx = PaymentTransaction(
            tenant_id=tenant_id,
            payment_intent_id=refund.payment_intent_id or refund.id,
            order_id=refund.order_id,
            transaction_type="REFUND",
            amount_cents=refund.amount_cents,
            currency=refund.currency,
            provider_transaction_id=provider_refund_id,
            payment_method_type="REFUND",
            status="SUCCESS",
            raw_response_json=f'{{"refund_id": "{provider_refund_id}", "status": "succeeded"}}'
        )
        self.db.add(tx)

        # Update order status
        order_stmt = select(SalesOrder).where(SalesOrder.id == refund.order_id).with_for_update()
        order_res = await self.db.execute(order_stmt)
        order = order_res.scalar_one()

        # Only a full refund refunds the order; partial refunds are tracked as such.
        total_refunded = completed + refund.amount_cents
        if total_refunded >= order.grand_total_cents:
            order.payment_status = "REFUNDED"
            order.status = "REFUNDED"
        else:
            order.payment_status = "PARTIALLY_REFUNDED"
        order.version += 1

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=approved_by_user_id,
            event_type="REFUND_PROCESSED",
            resource_type="REFUND_REQUEST",
            resource_id=refund.id,
            action="REFUND",
            status="SUCCESS",
            payload_json=f'{{"amount_cents": {refund.amount_cents}, "provider_refund_id": "{provider_refund_id}"}}'
        )
        self.db.add(audit)
        await self.db.flush()
        return refund
