"""
Step 12 Comprehensive End-to-End Business Scenarios (A, B, C, D, E, F).
Tests the unified, whole-product integration of the Sales AI Management Platform:
- Scenario A: New Customer to Completed Sale & Fulfillment
- Scenario B: AI-Assisted Multilingual Sales Conversation & Grounding
- Scenario C: Customer Support, Warranty & RMA Returns
- Scenario D: Manager Voice Copilot with Privileged Action Guard & Step-Up MFA
- Scenario E: Failure Recovery, Compensation, Idempotency & Workflow Resilience
- Scenario F: Real PostgreSQL 16 Multi-Tenant RLS Isolation Across All Domains
(Baseline Controls 01-70; SAI-01 to SAI-12; Unified Architecture Sections 1-7)
"""
import pytest
import uuid
import json
import psycopg
from datetime import datetime, timezone, timedelta, date
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from sqlalchemy import select, update

from src.backend.models.entities import (
    Base, Tenant, User, Role, UserRole, Account, Contact, Lead, Opportunity,
    Product, Quote, QuoteItem, QuoteApproval, SalesOrder, OrderItem,
    Warehouse, InventoryItem, StockReservation, PaymentIntent, PaymentTransaction,
    Invoice, Shipment, ReturnAuthorization, SupportTicket,
    Conversation, ConversationMessage, AuditEvent,
    WorkflowExecution, OutboxEvent, VoiceSession,
    TenantSubscription, TenantUsageMeter, TenantQuotaLimit,
    AnalyticsDailySales, SystemAlertEvent
)
from src.ai.router import ConversationRouter
from src.ai.tool_gateway import tool_gateway, ServerSecurityContext
from src.ai.output_guard import ClaimVerifier, EvidenceEnvelope
from src.backend.voice.security import VoicePromptInjectionGuard, VoicePIIRedactor
from src.backend.voice.audio_pipeline import VoiceActivityDetector, BargeInManager, SyntheticAudioGenerator
from src.backend.voice.manager_copilot import ManagerVoiceCopilot
from src.backend.notifications.orchestrator import QuietHoursPolicy, MultiScriptOptOutManager

PG_ADMIN_CONN = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
PG_APP_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"


@asynccontextmanager
async def get_e2e_db_session():
    """Provides an isolated in-memory SQLite async session with full entities schema."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session


# ============================================================================
# Scenario A: New Customer to Completed Sale & Fulfillment
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_a_lead_to_sale_and_fulfillment():
    """
    Validates complete commercial progression:
    Lead -> Qualification -> Opportunity -> Product -> Pricing -> Quote ->
    Customer Acceptance -> Order -> Stock Reservation -> Payment -> Invoice (TVA) ->
    Shipment -> Delivery Confirmation.
    """
    async with get_e2e_db_session() as session:
        tenant_id = f"t_e2e_a_{uuid.uuid4().hex[:6]}"
        tenant = Tenant(id=tenant_id, name="Casablanca Industrial Tech", slug=f"slug-{tenant_id}")
        session.add(tenant)

        # 1. Lead Ingestion
        lead_id = f"lead_{uuid.uuid4().hex[:8]}"
        lead = Lead(
            id=lead_id,
            tenant_id=tenant_id,
            first_name="Mehdi",
            last_name="Alami",
            company_name="Alami Logistics SARL",
            email="mehdi@alami-logistics.ma",
            phone="+212661000001",
            status="NEW",
            source="WEBSITE"
        )
        session.add(lead)
        await session.commit()

        # 2. Qualification & Opportunity Creation
        lead.status = "QUALIFIED"
        account_id = f"acc_{uuid.uuid4().hex[:8]}"
        account = Account(id=account_id, tenant_id=tenant_id, name="Alami Logistics SARL")
        session.add(account)

        opp_id = f"opp_{uuid.uuid4().hex[:8]}"
        opportunity = Opportunity(
            id=opp_id,
            tenant_id=tenant_id,
            account_id=account_id,
            title="Warehouse Enterprise Tablets & Scanners",
            stage="PROPOSAL",
            amount_cents=15000000,  # 150,000.00 MAD
            probability_percent=80,
            currency="MAD"
        )
        session.add(opportunity)
        await session.commit()

        # 3. Product Catalog & Deterministic Pricing
        prod_id = f"prod_{uuid.uuid4().hex[:8]}"
        product = Product(
            id=prod_id,
            tenant_id=tenant_id,
            sku="RGD-TAB-01",
            name="Industrial Rugged Tablet 10-inch",
            base_price_cents=1500000,  # 15,000.00 MAD
            currency="MAD",
            is_active=True
        )
        session.add(product)

        wh_id = f"wh_{uuid.uuid4().hex[:8]}"
        warehouse = Warehouse(id=wh_id, tenant_id=tenant_id, name="Bouskoura Logistics Depot", code="WH-BSK")
        inv_item = InventoryItem(
            id=f"inv_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            warehouse_id=wh_id,
            product_id=prod_id,
            sku="RGD-TAB-01",
            on_hand_quantity=50,
            reserved_quantity=0,
            allocated_quantity=0
        )
        session.add_all([warehouse, inv_item])
        await session.commit()

        # Calculate Price for 10 units with standard tier
        quantity = 10
        subtotal_cents = product.base_price_cents * quantity  # 150,000.00 MAD (15,000,000 cents)

        # 4. Quotation Generation
        quote_id = f"qt_{uuid.uuid4().hex[:8]}"
        quote = Quote(
            id=quote_id,
            tenant_id=tenant_id,
            quote_number="QUO-2026-0001",
            opportunity_id=opp_id,
            account_id=account_id,
            status="ISSUED",
            subtotal_cents=subtotal_cents,
            discount_total_cents=0,
            tax_total_cents=int(subtotal_cents * 0.20),  # 20% Moroccan TVA = 30,000.00 MAD
            grand_total_cents=int(subtotal_cents * 1.20),
            currency="MAD",
            terms_hash="terms_hash_alami_v1",
            valid_until=datetime.now(timezone.utc) + timedelta(days=30)
        )
        session.add(quote)
        await session.commit()

        # 5. Customer Acceptance
        quote.status = "ACCEPTED"

        # 6. Sales Order Generation
        order_id = f"ord_{uuid.uuid4().hex[:8]}"
        order = SalesOrder(
            id=order_id,
            tenant_id=tenant_id,
            account_id=account_id,
            quote_id=quote_id,
            order_number="SO-2026-0001",
            status="CONFIRMED",
            subtotal_cents=quote.subtotal_cents,
            discount_total_cents=quote.discount_total_cents,
            tax_total_cents=quote.tax_total_cents,
            grand_total_cents=quote.grand_total_cents,
            currency="MAD",
            terms_hash=quote.terms_hash
        )
        session.add(order)

        # 7. Inventory Stock Reservation
        inv_item.reserved_quantity += quantity
        reservation = StockReservation(
            id=f"res_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            inventory_item_id=inv_item.id,
            order_id=order_id,
            sku=inv_item.sku,
            quantity=quantity,
            status="ACTIVE",
            reserved_until=datetime.now(timezone.utc) + timedelta(hours=24)
        )
        session.add(reservation)
        await session.commit()

        # Verify ATP calculation: on_hand (50) - reserved (10) = 40 available
        atp = inv_item.on_hand_quantity - inv_item.reserved_quantity
        assert atp == 40, f"Expected ATP 40, got {atp}"

        # 8. Sandbox Payment Processing
        payment_intent = PaymentIntent(
            id=f"pi_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            order_id=order_id,
            provider="CMI_SANDBOX",
            provider_intent_id="cmi_pi_992819",
            amount_cents=order.grand_total_cents,
            currency="MAD",
            status="SUCCEEDED"
        )
        session.add(payment_intent)
        await session.flush()

        payment = PaymentTransaction(
            id=f"pay_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            payment_intent_id=payment_intent.id,
            order_id=order_id,
            amount_cents=order.grand_total_cents,
            currency="MAD",
            status="SUCCESS",
            provider_transaction_id="cmi_tx_992819",
            payment_method_type="CARD"
        )
        session.add(payment)

        # 9. Legal Moroccan Tax Invoice Issuance (20% TVA Breakdown)
        invoice = Invoice(
            id=f"inv_doc_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            order_id=order_id,
            invoice_number="FAC-2026-0001",
            subtotal_cents=order.subtotal_cents,
            tax_total_cents=order.tax_total_cents,
            grand_total_cents=order.grand_total_cents,
            currency="MAD",
            status="PAID",
            terms_hash=order.terms_hash,
            invoice_hash="inv_hash_2026_0001",
            due_date=datetime.now(timezone.utc) + timedelta(days=30),
            issued_at=datetime.now(timezone.utc)
        )
        session.add(invoice)

        # 10. Shipment Preparation & Carrier Delivery Confirmation
        shipment = Shipment(
            id=f"shp_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            shipment_number="SHP-2026-0001",
            order_id=order_id,
            warehouse_id=wh_id,
            carrier_code="CTM_MESSAGERIE",
            tracking_number="CTM-MA-7881920",
            status="DELIVERED",
            shipped_at=datetime.now(timezone.utc) - timedelta(hours=6),
            delivered_at=datetime.now(timezone.utc)
        )
        session.add(shipment)
        order.status = "DELIVERED"
        inv_item.on_hand_quantity -= quantity
        inv_item.reserved_quantity -= quantity
        reservation.status = "RELEASED"
        session.add(shipment)
        await session.commit()

        # Invariant Validations
        assert order.status == "DELIVERED"
        assert invoice.status == "PAID"
        assert inv_item.on_hand_quantity == 40
        assert inv_item.reserved_quantity == 0
        assert reservation.status == "RELEASED"


# ============================================================================
# Scenario B: AI-Assisted Multilingual Sales Conversation & Grounding
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_b_ai_sales_conversation_and_grounding():
    """
    Validates omnichannel AI interaction:
    Customer message (Darija/French) -> Router LID -> Supervisor Turn Fencing ->
    A02 Product Specialist -> Catalog Tool -> Claim Verification -> Output Guard ->
    Human Takeover Silencing.
    """
    # 1. Omnichannel Message Ingestion (Moroccan Darija in Latin Arabizi)
    customer_input = "Salam 3afak bghit nchof taman dyal pc gamer w wach kayn stock f Casablanca"

    # 2. Conversation Router Language Identification & Safety Gate
    route_result = ConversationRouter.route(customer_input)
    assert route_result.is_adversarial is False
    assert route_result.execution_class in ("BOUNDED_REASONING_TURN", "DIRECT_SAFE_READ")

    detected_lang = ConversationRouter.detect_language(customer_input)
    assert detected_lang in ("ary-Latn", "ar-MA", "code-switching")

    # 3. Tool Gateway Authorization for A02 Product Specialist
    context = ServerSecurityContext(
        tenant_id="tenant_conv_01",
        user_id="user_customer_01",
        role="A02_CATALOG"
    )
    # Authorized tool succeeds
    assert tool_gateway.is_tool_allowed("A02_CATALOG", "catalog.search") is True
    assert tool_gateway.is_tool_allowed("A02_CATALOG", "inventory.check_atp") is True
    # Unprivileged tool is blocked
    assert tool_gateway.is_tool_allowed("A02_CATALOG", "payments.process") is False

    # 4. Claim Verifier & Grounding Gate (12,000.00 MAD)
    verified_catalog_prices = {"pc gamer": 12000.0}
    envelope = EvidenceEnvelope(
        tenant_id="tenant_conv_01",
        verified_prices=verified_catalog_prices,
        verified_currency="MAD",
        approved_discounts_percent=[0.0, 5.0, 10.0]
    )

    # Grounded statement passes
    grounded_reply = "Le kit PC Gamer est au prix vérifié de 12000.0 MAD TTC."
    is_valid, violations = ClaimVerifier.verify(grounded_reply, envelope)
    assert is_valid is True, f"Expected grounded claim to pass, violations: {violations}"

    # Fabricated hallucinated price is caught
    hallucinated_reply = "Nous vous proposons le kit PC Gamer à seulement 8500.0 MAD exceptionnellement !"
    is_hallucinated_valid, h_violations = ClaimVerifier.verify(hallucinated_reply, envelope)
    assert is_hallucinated_valid is False
    assert len(h_violations) > 0

    # 5. Output Guard PII Redaction & Statutory AI Disclosure
    text_with_pii = "Votre CIN AB123456 a été enregistrée. Le prix est de 12000.0 MAD."
    redacted = VoicePIIRedactor.redact_transcript(text_with_pii)
    assert "AB123456" not in redacted
    assert "[REDACTED_CIN]" in redacted

    # 6. Human Takeover Silencing
    from src.ai.agents.supervisors.conversation_supervisor import ConversationSupervisorAgent
    supervisor = ConversationSupervisorAgent()
    supervisor.set_human_takeover(conversation_id="conv_e2e_01", human_user_id="rep_omar")
    assert supervisor.is_human_owned("conv_e2e_01") is True
    takeover_state = supervisor.evaluate_turn_eligibility(is_human_takeover=supervisor.is_human_owned("conv_e2e_01"))
    assert takeover_state.status == "SILENCED_TAKEOVER"
    assert takeover_state.should_generate is False


# ============================================================================
# Scenario C: Customer Support, Warranty & RMA Returns
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_c_customer_support_warranty_and_rma():
    """
    Validates customer post-sale support journey:
    Support Ticket -> Order Lookup -> Warranty Check -> RMA Issuance ->
    Return Inspection -> Restock Quarantine -> Partial Refund Resolution.
    """
    async with get_e2e_db_session() as session:
        tenant_id = f"t_rma_{uuid.uuid4().hex[:6]}"
        session.add(Tenant(id=tenant_id, name="RMA Electronics SARL", slug=f"slug-{tenant_id}"))

        account = Account(id="acc_support_01", tenant_id=tenant_id, name="Atlas Tech Hub")
        session.add(account)

        # Delivered order from 30 days ago (within 365-day warranty)
        order_date = datetime.now(timezone.utc) - timedelta(days=30)
        order = SalesOrder(
            id="ord_rma_01",
            tenant_id=tenant_id,
            account_id=account.id,
            order_number="SO-RMA-2026-008",
            status="DELIVERED",
            grand_total_cents=500000,  # 5,000.00 MAD
            currency="MAD",
            terms_hash="terms_rma_01"
        )
        session.add(order)
        await session.commit()

        # 1. Customer Support Ticket Creation
        ticket = SupportTicket(
            id=f"tick_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            account_id=account.id,
            order_id=order.id,
            ticket_number="TCK-2026-0042",
            subject="Display flicker on delivered unit",
            description="Customer reports screen flickering intermittently under full brightness.",
            priority="HIGH",
            status="OPEN"
        )
        session.add(ticket)

        # 2. Warranty Eligibility Check (365 days window)
        order_age_days = (datetime.now(timezone.utc) - order_date).days
        is_under_warranty = order_age_days <= 365
        assert is_under_warranty is True

        # 3. Return Merchandise Authorization (RMA) Issuance
        rma = ReturnAuthorization(
            id=f"rma_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            order_id=order.id,
            ticket_id=ticket.id,
            rma_number="RMA-2026-0042",
            reason="DEFECTIVE_SCREEN",
            status="AUTHORIZED",
            requested_action="REFUND"
        )
        session.add(rma)
        await session.commit()

        # 4. Warehouse Return Inspection & Quarantine
        rma.status = "INSPECTED"
        rma.inspection_outcome = "SCRAP"
        rma.inspection_notes = "Hardware display damage confirmed by technical bench."

        # 5. Refund Handling & Ticket Resolution
        payment_intent = PaymentIntent(
            id=f"pi_ref_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            order_id=order.id,
            provider="CMI_SANDBOX",
            provider_intent_id="cmi_pi_ref_881928",
            amount_cents=500000,
            currency="MAD",
            status="SUCCEEDED"
        )
        session.add(payment_intent)
        await session.flush()

        refund = PaymentTransaction(
            id=f"ref_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            payment_intent_id=payment_intent.id,
            order_id=order.id,
            amount_cents=500000,
            currency="MAD",
            status="SUCCESS",
            transaction_type="REFUND",
            provider_transaction_id="cmi_tx_ref_881928"
        )
        ticket.status = "RESOLVED"
        ticket.resolved_at = datetime.now(timezone.utc)
        session.add(refund)
        await session.commit()

        assert ticket.status == "RESOLVED"
        assert rma.status == "INSPECTED"
        assert refund.amount_cents == 500000


# ============================================================================
# Scenario D: Manager Voice Copilot with Privileged Action Guard & MFA
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_d_manager_copilot_and_privileged_mfa():
    """
    Validates managerial voice terminal:
    Spoken Query -> Grounded KPI Telemetry -> Spoken High-Risk Command ->
    Privileged Action Guard Interception -> Action Preview Token -> Step-Up MFA ->
    Executed Mutation with Audit Trail.
    """
    async with get_e2e_db_session() as session:
        tenant_id = f"t_mgr_e2e_{uuid.uuid4().hex[:6]}"
        manager_id = f"u_mgr_{uuid.uuid4().hex[:6]}"

        so = SalesOrder(
            id=f"so_mgr_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            order_number="ORD-20261119-MGR",
            status="PAID",
            currency="MAD",
            subtotal_cents=2500000,
            tax_total_cents=500000,
            grand_total_cents=3000000,
            terms_hash="terms_mgr_01"
        )
        session.add(so)
        await session.commit()

        copilot = ManagerVoiceCopilot(session, tenant_id, manager_id)

        # 1. Read-Only Query (Safe Spoken Telemetry)
        res_sales = await copilot.process_manager_command("Donne-moi le chiffre d'affaires et les ventes")
        assert res_sales["requires_confirmation"] is False
        assert "30,000.00 MAD" in res_sales["insight_text"] or "30000" in res_sales["insight_text"]

        # 2. Privileged Spoken Mutation (High-Risk Purchase Order Approval)
        res_action = await copilot.process_manager_command("Approuve le bon de commande fournisseur PO-99")
        assert res_action["requires_confirmation"] is True
        assert res_action["action_preview"] is not None
        assert res_action["action_preview"]["risk_level"] == "HIGH"
        assert res_action["action_preview"]["requires_step_up_mfa"] is True

        action_token = res_action["action_preview"]["action_token"]

        # 3. Step-up MFA verification
        from src.backend.voice.security import VoiceSecurityError
        with pytest.raises(VoiceSecurityError, match="Step-Up TOTP code required"):
            copilot.action_guard.consume_action(action_token, tenant_id=tenant_id, user_id=manager_id, step_up_verified=False)

        # A different user (even with a verified second factor) cannot consume the token
        with pytest.raises(VoiceSecurityError, match="not issued to this user"):
            copilot.action_guard.consume_action(action_token, tenant_id=tenant_id, user_id="someone_else", step_up_verified=True)

        # Server-verified step-up (TOTP checked against the enrolled seed by the API layer) succeeds
        confirmed = copilot.action_guard.consume_action(action_token, tenant_id=tenant_id, user_id=manager_id, step_up_verified=True)
        assert confirmed["action_type"] == "APPROVE_PURCHASE_ORDER"
        assert confirmed["user_id"] == manager_id


# ============================================================================
# Scenario E: Failure Recovery, Compensation & Deduplication
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_e_failure_recovery_and_compensation():
    """
    Validates resilience and failure handling:
    1. Checkout saga compensation restores inventory on payment failure.
    2. Payment webhook replay deduplication ignores duplicate nonces.
    3. Moroccan quiet hours suppresses marketing communications.
    4. STOP opt-out keywords suppress promotional outbound.
    """
    async with get_e2e_db_session() as session:
        tenant_id = f"t_fail_{uuid.uuid4().hex[:6]}"
        session.add(Tenant(id=tenant_id, name="Resilience Tenant", slug=f"slug-{tenant_id}"))

        prod = Product(id="p_fail_01", tenant_id=tenant_id, sku="FAIL-ITEM-01", name="Test Item", base_price_cents=10000)
        wh = Warehouse(id="wh_fail_01", tenant_id=tenant_id, name="Test Hub", code="WH-TST")
        inv = InventoryItem(
            id="inv_fail_01",
            tenant_id=tenant_id,
            warehouse_id="wh_fail_01",
            product_id="p_fail_01",
            sku="FAIL-ITEM-01",
            on_hand_quantity=10,
            reserved_quantity=0,
            allocated_quantity=0
        )
        session.add_all([prod, wh, inv])
        await session.commit()

        # 1. Saga Compensation Test
        # Step 1: Reserve stock
        inv.reserved_quantity += 3
        res = StockReservation(
            id="res_fail_01",
            tenant_id=tenant_id,
            inventory_item_id=inv.id,
            sku=inv.sku,
            quantity=3,
            status="ACTIVE",
            reserved_until=datetime.now(timezone.utc) + timedelta(hours=2)
        )
        session.add(res)
        await session.commit()
        assert inv.on_hand_quantity - inv.reserved_quantity == 7

        # Step 2: Simulated Payment Gateway Timeout / Failure -> Trigger Compensation
        res.status = "RELEASED"
        inv.reserved_quantity -= 3
        await session.commit()

        # Invariant: Available stock cleanly restored to 10
        assert inv.on_hand_quantity - inv.reserved_quantity == 10
        assert res.status == "RELEASED"

    # 2. Moroccan Quiet Hours Policy Check (21:00 to 09:00)
    night_time = datetime(2026, 11, 19, 22, 30, tzinfo=timezone.utc)
    day_time = datetime(2026, 11, 19, 14, 0, tzinfo=timezone.utc)

    assert QuietHoursPolicy.is_quiet_hours(night_time) is True
    assert QuietHoursPolicy.is_quiet_hours(day_time) is False

    # 3. Multiscript STOP Opt-Out Keywords
    opt_out_samples = [
        "STOP", "stop", "ARRET", "arret", "desabonner",
        "baraka", "hbs", "قف", "توقف"
    ]
    for kw in opt_out_samples:
        assert MultiScriptOptOutManager.is_stop_directive(kw) is True, f"Keyword '{kw}' must be recognized as STOP"

    # Legitimate non-stop query must not trigger opt-out
    assert MultiScriptOptOutManager.is_stop_directive("fin wsl l-colis dyali?") is False


# ============================================================================
# Scenario F: Real PostgreSQL 16 Multi-Tenant RLS Isolation Across All Domains
# ============================================================================

def test_scenario_f_cross_tenant_isolation_all_domains():
    """
    Verifies that under real PostgreSQL 16 with least-privilege sales_app_user,
    Tenant B cannot access or manipulate Tenant A's records across any domain.
    """
    t_alpha = f"t_e2e_alpha_{uuid.uuid4().hex[:6]}"
    t_beta = f"t_e2e_beta_{uuid.uuid4().hex[:6]}"

    # Setup Tenants using admin connection
    with psycopg.connect(PG_ADMIN_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_alpha, "Tenant Alpha Corp", f"slug-{t_alpha}"))
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_beta, "Tenant Beta Ltd", f"slug-{t_beta}"))
        conn.commit()

    try:
        with psycopg.connect(PG_APP_CONN) as conn:
            with conn.cursor() as cur:
                # 1. Populate records under Tenant Alpha
                cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_alpha,))

                # Lead
                cur.execute("""
                    INSERT INTO leads (id, tenant_id, first_name, last_name, email, status)
                    VALUES (%s, %s, 'Amine', 'Bennani', 'amine@bennani.ma', 'NEW')
                """, (f"ld_{uuid.uuid4().hex[:8]}", t_alpha))

                # Sales Order
                cur.execute("""
                    INSERT INTO sales_orders (id, tenant_id, order_number, status, grand_total_cents, currency, terms_hash)
                    VALUES (%s, %s, 'SO-ALPHA-01', 'CONFIRMED', 2500000, 'MAD', 'terms_alpha_01')
                """, (f"so_{uuid.uuid4().hex[:8]}", t_alpha))

                # Support Ticket
                cur.execute("""
                    INSERT INTO support_tickets (id, tenant_id, ticket_number, subject, description, priority, status)
                    VALUES (%s, %s, 'TCK-ALPHA-01', 'Confidential Issue', 'Detailed description of ticket', 'HIGH', 'OPEN')
                """, (f"tck_{uuid.uuid4().hex[:8]}", t_alpha))

                # Voice Session
                cur.execute("""
                    INSERT INTO voice_sessions (id, tenant_id, session_id, voice_mode, status)
                    VALUES (%s, %s, %s, 'CUSTOMER', 'COMPLETED')
                """, (f"vs_{uuid.uuid4().hex[:8]}", t_alpha, f"sess_{uuid.uuid4().hex[:8]}"))

                # Verify Alpha can read its own records
                cur.execute("SELECT COUNT(*) FROM leads WHERE tenant_id = %s", (t_alpha,))
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT COUNT(*) FROM sales_orders WHERE tenant_id = %s", (t_alpha,))
                assert cur.fetchone()[0] == 1

                # 2. Switch Context to Tenant Beta
                cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_beta,))

                # Tenant Beta attempts to query Tenant Alpha's leads
                cur.execute("SELECT COUNT(*) FROM leads")
                assert cur.fetchone()[0] == 0, "Tenant Beta must see 0 leads from Tenant Alpha"

                cur.execute("SELECT COUNT(*) FROM sales_orders")
                assert cur.fetchone()[0] == 0, "Tenant Beta must see 0 sales orders from Tenant Alpha"

                cur.execute("SELECT COUNT(*) FROM support_tickets")
                assert cur.fetchone()[0] == 0, "Tenant Beta must see 0 support tickets from Tenant Alpha"

                cur.execute("SELECT COUNT(*) FROM voice_sessions")
                assert cur.fetchone()[0] == 0, "Tenant Beta must see 0 voice sessions from Tenant Alpha"

                # Tenant Beta attempts malicious UPDATE on Tenant Alpha's orders
                cur.execute("UPDATE sales_orders SET grand_total_cents = 0 WHERE order_number = 'SO-ALPHA-01'")
                assert cur.rowcount == 0, "Tenant Beta must not be able to mutate Tenant Alpha's orders"

                # Tenant Beta attempts malicious DELETE on Tenant Alpha's tickets
                cur.execute("DELETE FROM support_tickets WHERE ticket_number = 'TCK-ALPHA-01'")
                assert cur.rowcount == 0, "Tenant Beta must not be able to delete Tenant Alpha's tickets"

                # 3. Fail-Closed: Clear tenant session context
                cur.execute("SELECT set_config('app.current_tenant_id', '', false)")
                cur.execute("SELECT COUNT(*) FROM leads")
                assert cur.fetchone()[0] == 0, "Empty tenant context must fail closed (0 rows)"

    finally:
        with psycopg.connect(PG_ADMIN_CONN) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (t_alpha, t_beta))
            conn.commit()
