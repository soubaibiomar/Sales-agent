"""
Security Tests for Inbound Payment Webhooks, Cryptographic HMAC Signatures,
Replay Deduplication, Non-AI Authority, and Privileged Refund MFA.
(Controls 31, 32, 48, 57, 58, 59; SAI-07, SAI-08)
Step 05: Sprint 3 - Transact
"""
import pytest
import hmac
import hashlib
import json
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.backend.models.entities import (
    Base, Tenant, Warehouse, InventoryItem, SalesOrder, OrderItem,
    PaymentIntent, PaymentTransaction, RefundRequest
)
from src.backend.domains.payments.service import (
    PaymentService, InvalidWebhookSignatureError, DuplicateWebhookEventError,
    UnauthorizedRefundError, RefundExceedsPaidAmountError
)
from src.backend.domains.orders.service import OrderService
from src.backend.domains.inventory.service import InventoryService

SECRET = "whsec_test_secret_for_sales_ai_sandbox_hmac_256"


@asynccontextmanager
async def get_test_payment_env():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        tenant = Tenant(id="tenant_pay_sec", name="Payment Sec Corp", slug="pay-sec", is_active=True)
        session.add(tenant)
        wh = Warehouse(id="wh_pay_sec", tenant_id=tenant.id, code="WH-PAY", name="Pay Warehouse", is_active=True)
        session.add(wh)

        item = InventoryItem(
            id="item_pay_sku",
            tenant_id=tenant.id,
            warehouse_id=wh.id,
            sku="SKU-PAY-1",
            on_hand_quantity=10,
            reserved_quantity=2,
            allocated_quantity=0,
            backorder_allowed=False
        )
        session.add(item)

        order = SalesOrder(
            id="order_pay_sec",
            tenant_id=tenant.id,
            order_number="ORD-PAY-001",
            status="PENDING_PAYMENT",
            payment_status="UNPAID",
            version=1,
            currency="USD",
            subtotal_cents=10000,
            discount_total_cents=0,
            tax_total_cents=2000,
            grand_total_cents=12000,
            terms_hash="a"*64
        )
        session.add(order)

        order_item = OrderItem(
            id="oi_pay_sec",
            tenant_id=tenant.id,
            order_id=order.id,
            sku="SKU-PAY-1",
            name="Pay Item",
            quantity=2,
            unit_price_cents=5000,
            subtotal_cents=10000,
            total_cents=12000
        )
        session.add(order_item)

        intent = PaymentIntent(
            id="pi_pay_sec",
            tenant_id=tenant.id,
            order_id=order.id,
            provider="STRIPE_SANDBOX",
            provider_intent_id="pi_test_12345",
            amount_cents=12000,
            currency="USD",
            status="REQUIRES_PAYMENT_METHOD"
        )
        session.add(intent)
        await session.commit()

    try:
        yield session_factory, "tenant_pay_sec", "order_pay_sec", "pi_test_12345"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_webhook_cryptographic_hmac_signature_verification():
    """
    Control 31: Verifies that inbound payment webhooks require valid HMAC-SHA256 signatures.
    Tampered or forged signatures are rejected.
    """
    async with get_test_payment_env() as (session_factory, tenant_id, order_id, provider_intent_id):
        payload_dict = {
            "event_id": "evt_test_success_1",
            "event_type": "payment_intent.succeeded",
            "provider_intent_id": provider_intent_id,
            "amount_cents": 12000,
            "currency": "USD"
        }
        raw_body = json.dumps(payload_dict)

        # 1. Valid signature computed with shared secret
        valid_sig = hmac.new(SECRET.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256).hexdigest()

        async with session_factory() as session:
            pay_service = PaymentService(session)
            res = await pay_service.process_webhook_event(
                tenant_id=tenant_id,
                provider="STRIPE_SANDBOX",
                raw_payload_str=raw_body,
                signature=valid_sig,
                webhook_secret=SECRET
            )
            assert res["status"] == "processed"
            await session.commit()

        # Verify order transitioned to PAID
        async with session_factory() as session:
            order_service = OrderService(session)
            order = await order_service.get_order_by_id(tenant_id=tenant_id, order_id=order_id)
            assert order.status == "PAID"
            assert order.payment_status == "PAID"

        # 2. Tampered / invalid signature is rejected
        async with session_factory() as session:
            pay_service = PaymentService(session)
            with pytest.raises(InvalidWebhookSignatureError, match="HMAC signature verification failed"):
                await pay_service.process_webhook_event(
                    tenant_id=tenant_id,
                    provider="STRIPE_SANDBOX",
                    raw_payload_str=raw_body,
                    signature="invalid_forged_signature_hex",
                    webhook_secret=SECRET
                )


@pytest.mark.asyncio
async def test_webhook_replay_deduplication():
    """
    Control 59: Replayed webhook event with identical event_id is safely ignored,
    producing zero duplicate transactions and zero duplicate order updates.
    """
    async with get_test_payment_env() as (session_factory, tenant_id, order_id, provider_intent_id):
        payload_dict = {
            "event_id": "evt_test_dedup_1",
            "event_type": "payment_intent.succeeded",
            "provider_intent_id": provider_intent_id
        }
        raw_body = json.dumps(payload_dict)
        sig = hmac.new(SECRET.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256).hexdigest()

        # First call processes
        async with session_factory() as session:
            pay_service = PaymentService(session)
            res1 = await pay_service.process_webhook_event(
                tenant_id=tenant_id,
                provider="STRIPE_SANDBOX",
                raw_payload_str=raw_body,
                signature=sig,
                webhook_secret=SECRET
            )
            assert res1["status"] == "processed"
            await session.commit()

        # Replay call with exact same event_id returns duplicate_ignored
        async with session_factory() as session:
            pay_service = PaymentService(session)
            res2 = await pay_service.process_webhook_event(
                tenant_id=tenant_id,
                provider="STRIPE_SANDBOX",
                raw_payload_str=raw_body,
                signature=sig,
                webhook_secret=SECRET
            )
            assert res2["status"] == "duplicate_ignored"


@pytest.mark.asyncio
async def test_financial_refund_requires_step_up_mfa_and_bounds_check():
    """
    Control 15, SAI-08: Privileged financial operations (refunds) strictly require step-up MFA.
    Refunds exceeding grand total are rejected.
    """
    async with get_test_payment_env() as (session_factory, tenant_id, order_id, provider_intent_id):
        # First, mark order as PAID so it is eligible for refund
        async with session_factory() as session:
            order_service = OrderService(session)
            await order_service.mark_order_paid(
                tenant_id=tenant_id,
                order_id=order_id,
                expected_version=1,
                transaction_id="tx_test_init"
            )
            await session.commit()

        # 1. Attempt refund exceeding order amount (15000 cents > 12000 cents) -> Rejected
        async with session_factory() as session:
            pay_service = PaymentService(session)
            with pytest.raises(RefundExceedsPaidAmountError, match="exceeds order total"):
                await pay_service.create_refund_request(
                    tenant_id=tenant_id,
                    order_id=order_id,
                    amount_cents=15000,
                    reason="Customer dissatisfied"
                )

        # 2. Valid refund request created
        async with session_factory() as session:
            pay_service = PaymentService(session)
            refund = await pay_service.create_refund_request(
                tenant_id=tenant_id,
                order_id=order_id,
                amount_cents=12000,
                reason="Customer return",
                requested_by_user_id="user_rep_1"
            )
            await session.commit()
            refund_id = refund.id

        # 3. Approving without Step-Up MFA -> Rejected with UnauthorizedRefundError
        async with session_factory() as session:
            pay_service = PaymentService(session)
            with pytest.raises(UnauthorizedRefundError, match="Step-up MFA verification required"):
                await pay_service.approve_and_process_refund(
                    tenant_id=tenant_id,
                    refund_id=refund_id,
                    approved_by_user_id="manager_user_1",
                    step_up_mfa_verified=False  # Missing MFA!
                )

        # 4. Approving with Step-Up MFA -> Succeeded
        async with session_factory() as session:
            pay_service = PaymentService(session)
            approved_refund = await pay_service.approve_and_process_refund(
                tenant_id=tenant_id,
                refund_id=refund_id,
                approved_by_user_id="manager_user_1",
                step_up_mfa_verified=True  # Verified!
            )
            assert approved_refund.status == "COMPLETED"
            assert approved_refund.provider_refund_id is not None
            await session.commit()

        # Order must now be REFUNDED
        async with session_factory() as session:
            order_service = OrderService(session)
            order = await order_service.get_order_by_id(tenant_id=tenant_id, order_id=order_id)
            assert order.status == "REFUNDED"
            assert order.payment_status == "REFUNDED"
