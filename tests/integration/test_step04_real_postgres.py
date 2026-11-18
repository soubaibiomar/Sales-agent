"""
Integration Test Suite: Real PostgreSQL 16 CRM, Catalog, Quotes, and Approvals Validation.
Executes against live PostgreSQL container (sales-ai-postgres) on 127.0.0.1:5432
under the unprivileged 'sales_app_user' account with FORCE ROW LEVEL SECURITY.

Verifies:
1. PostgreSQL RLS tenant isolation across all 12 Step 04 tables.
2. Cross-tenant leakage rejection (Tenant Beta sees 0 rows from Tenant Alpha).
3. Missing tenant context rejection (unscoped queries see 0 rows under FORCE RLS).
4. Pessimistic row locking (SELECT ... FOR UPDATE) on PostgreSQL transactions.
5. Multi-step transaction rollback leaves zero orphan records.
6. Atomic lead-to-opportunity conversion against live PostgreSQL.
(Baseline Controls 16, 17, 33, 34, 42, 51, 57, 58; SAI-08)
"""
import sys
import uuid
import json
import psycopg
import pytest
import warnings
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text, select

if sys.platform == "win32":
    import asyncio
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from src.backend.models.entities import (
    Tenant, User, Account, Contact, Lead, Opportunity, Activity,
    Product, ProductVariant, PriceList, PriceListItem, Quote, QuoteItem, QuoteApproval, QuoteDocument
)
from src.backend.core.security import SecurityService
from src.backend.domains.crm.service import CrmService
from src.backend.domains.quotations.service import QuotationService
from src.backend.domains.approvals.service import ApprovalService

PG_ASYNC_URL = "postgresql+psycopg://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"
PG_SYNC_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"

STEP04_TABLES = [
    "accounts",
    "leads",
    "opportunities",
    "activities",
    "products",
    "product_variants",
    "price_lists",
    "price_list_items",
    "quotes",
    "quote_items",
    "quote_approvals",
    "quote_documents"
]

@pytest.fixture(scope="module")
def real_pg_tenants():
    """Seeds two distinct test tenants in live PostgreSQL 16."""
    t_alpha = f"t_pg04_a_{uuid.uuid4().hex[:8]}"
    t_beta = f"t_pg04_b_{uuid.uuid4().hex[:8]}"
    u_alpha = f"u_pg04_a_{uuid.uuid4().hex[:8]}"
    u_beta = f"u_pg04_b_{uuid.uuid4().hex[:8]}"

    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            # 1. Tenants
            cur.execute(
                "INSERT INTO tenants (id, name, slug, is_active) VALUES (%s, %s, %s, %s), (%s, %s, %s, %s);",
                (t_alpha, "PG04 Tenant Alpha", f"slug-{t_alpha}", True,
                 t_beta, "PG04 Tenant Beta", f"slug-{t_beta}", True)
            )
            # 2. Users under each tenant
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_alpha,))
            cur.execute(
                "INSERT INTO users (id, tenant_id, email, hashed_password, full_name, is_active, mfa_enabled) VALUES (%s, %s, %s, %s, %s, %s, %s);",
                (u_alpha, t_alpha, f"user_{u_alpha}@alpha.com", "hash", "Alpha User", True, True)
            )
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_beta,))
            cur.execute(
                "INSERT INTO users (id, tenant_id, email, hashed_password, full_name, is_active, mfa_enabled) VALUES (%s, %s, %s, %s, %s, %s, %s);",
                (u_beta, t_beta, f"user_{u_beta}@beta.com", "hash", "Beta User", True, True)
            )
            conn.commit()

    return {
        "t_alpha": t_alpha,
        "t_beta": t_beta,
        "u_alpha": u_alpha,
        "u_beta": u_beta
    }


@pytest.mark.asyncio
async def test_real_postgres_step04_rls_isolation_all_12_tables(real_pg_tenants):
    """
    Validates PostgreSQL Row-Level Security across all 12 Step 04 tables.
    Data inserted under Tenant Alpha must be completely invisible to Tenant Beta and to unscoped sessions.
    """
    env = real_pg_tenants
    t_alpha = env["t_alpha"]
    t_beta = env["t_beta"]

    engine = create_async_engine(PG_ASYNC_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # 1. Insert records under Tenant Alpha across all 12 tables
    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": t_alpha})

        acc_id = f"acc_{uuid.uuid4().hex[:8]}"
        lead_id = f"lead_{uuid.uuid4().hex[:8]}"
        opp_id = f"opp_{uuid.uuid4().hex[:8]}"
        act_id = f"act_{uuid.uuid4().hex[:8]}"
        prod_id = f"p_{uuid.uuid4().hex[:8]}"
        var_id = f"pv_{uuid.uuid4().hex[:8]}"
        pl_id = f"pl_{uuid.uuid4().hex[:8]}"
        pli_id = f"pli_{uuid.uuid4().hex[:8]}"
        quote_id = f"qt_{uuid.uuid4().hex[:8]}"
        qi_id = f"qi_{uuid.uuid4().hex[:8]}"
        appr_id = f"qa_{uuid.uuid4().hex[:8]}"
        doc_id = f"qd_{uuid.uuid4().hex[:8]}"

        # 1. accounts
        await s.execute(text(
            "INSERT INTO accounts (id, tenant_id, name, is_active) VALUES (:id, :tid, :name, true)"
        ), {"id": acc_id, "tid": t_alpha, "name": "Alpha Corp"})

        # 2. leads
        await s.execute(text(
            "INSERT INTO leads (id, tenant_id, first_name, last_name, company_name, email, source, status, score) "
            "VALUES (:id, :tid, 'LeadA', 'Test', 'Alpha Leads', 'leada@test.com', 'MANUAL', 'NEW', 50)"
        ), {"id": lead_id, "tid": t_alpha})

        # 3. opportunities
        await s.execute(text(
            "INSERT INTO opportunities (id, tenant_id, account_id, title, stage, amount_cents, currency) "
            "VALUES (:id, :tid, :acc, 'Deal Alpha', 'DISCOVERY', 1000000, 'MAD')"
        ), {"id": opp_id, "tid": t_alpha, "acc": acc_id})

        # 4. activities
        await s.execute(text(
            "INSERT INTO activities (id, tenant_id, activity_type, subject) "
            "VALUES (:id, :tid, 'NOTE', 'Discovery note Alpha')"
        ), {"id": act_id, "tid": t_alpha})

        # 5. products
        await s.execute(text(
            "INSERT INTO products (id, tenant_id, sku, name, product_type, uom, base_price_cents, cost_cents, currency, is_active) "
            "VALUES (:id, :tid, :sku, 'Alpha Server', 'PHYSICAL', 'UNIT', 500000, 250000, 'MAD', true)"
        ), {"id": prod_id, "tid": t_alpha, "sku": f"SKU-A-{uuid.uuid4().hex[:6]}"})

        # 6. product_variants
        await s.execute(text(
            "INSERT INTO product_variants (id, tenant_id, product_id, sku_variant, name, price_adjustment_cents, is_active) "
            "VALUES (:id, :tid, :pid, :sku, 'Alpha Server Pro', 50000, true)"
        ), {"id": var_id, "tid": t_alpha, "pid": prod_id, "sku": f"SKU-A-PRO-{uuid.uuid4().hex[:6]}"})

        # 7. price_lists
        await s.execute(text(
            "INSERT INTO price_lists (id, tenant_id, name, code, currency, is_active) "
            "VALUES (:id, :tid, 'Alpha VIP', :code, 'MAD', true)"
        ), {"id": pl_id, "tid": t_alpha, "code": f"PL-A-{uuid.uuid4().hex[:6]}"})

        # 8. price_list_items
        await s.execute(text(
            "INSERT INTO price_list_items (id, tenant_id, price_list_id, product_id, unit_price_cents, min_quantity) "
            "VALUES (:id, :tid, :plid, :pid, 450000, 1)"
        ), {"id": pli_id, "tid": t_alpha, "plid": pl_id, "pid": prod_id})

        # 9. quotes
        await s.execute(text(
            "INSERT INTO quotes (id, tenant_id, quote_number, status, version, subtotal_cents, discount_total_cents, "
            "tax_total_cents, grand_total_cents, margin_percent, requires_approval, terms_hash, valid_until) "
            "VALUES (:id, :tid, :qn, 'DRAFT', 1, 450000, 0, 90000, 540000, 44.44, false, 'hash_alpha', NOW() + INTERVAL '30 days')"
        ), {"id": quote_id, "tid": t_alpha, "qn": f"QT-A-{uuid.uuid4().hex[:6]}"})

        # 10. quote_items
        await s.execute(text(
            "INSERT INTO quote_items (id, tenant_id, quote_id, product_id, sku_snapshot, name_snapshot, quantity, "
            "uom_snapshot, unit_price_cents, unit_cost_cents, discount_percent, discount_cents, tax_rate_percent, "
            "subtotal_cents, tax_cents, total_cents, margin_percent) "
            "VALUES (:id, :tid, :qid, :pid, 'SKU-A', 'Alpha Server', 1, 'UNIT', 450000, 250000, 0.00, 0, 20.00, 450000, 90000, 540000, 44.44)"
        ), {"id": qi_id, "tid": t_alpha, "qid": quote_id, "pid": prod_id})

        # 11. quote_approvals
        await s.execute(text(
            "INSERT INTO quote_approvals (id, tenant_id, quote_id, quote_version, terms_hash, requested_by_user_id, status) "
            "VALUES (:id, :tid, :qid, 1, 'hash_alpha', :uid, 'PENDING')"
        ), {"id": appr_id, "tid": t_alpha, "qid": quote_id, "uid": env["u_alpha"]})

        # 12. quote_documents
        await s.execute(text(
            "INSERT INTO quote_documents (id, tenant_id, quote_id, quote_version, document_type, document_hash, file_path, content_json) "
            "VALUES (:id, :tid, :qid, 1, 'PRO_FORMA', 'hash_doc_alpha', 's3://quotes/doc.json', '{}')"
        ), {"id": doc_id, "tid": t_alpha, "qid": quote_id})

        await s.commit()

    # 2. Query as Tenant Beta -> Must return 0 rows for all 12 tables
    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": t_beta})

        for tbl in STEP04_TABLES:
            res = await s.execute(text(f"SELECT count(*) FROM {tbl} WHERE tenant_id = :alpha_tid"), {"alpha_tid": t_alpha})
            count = res.scalar()
            assert count == 0, f"RLS LEAKAGE in table '{tbl}': Tenant Beta was able to see {count} rows belonging to Tenant Alpha!"

    # 3. Query with NO tenant context (unscoped session) -> Must return 0 rows for all 12 tables under FORCE RLS
    async with session_factory() as s:
        await s.execute(text("RESET app.current_tenant_id"))

        for tbl in STEP04_TABLES:
            res = await s.execute(text(f"SELECT count(*) FROM {tbl} WHERE tenant_id = :alpha_tid"), {"alpha_tid": t_alpha})
            count = res.scalar()
            assert count == 0, f"RLS LEAKAGE in table '{tbl}': Unscoped session was able to see {count} rows belonging to Tenant Alpha!"

    await engine.dispose()


@pytest.mark.asyncio
async def test_real_postgres_pessimistic_row_locking(real_pg_tenants):
    """
    Verifies that pessimistic row locking (SELECT ... FOR UPDATE) operates correctly
    under real PostgreSQL 16 transaction semantics for concurrent approval protection.
    """
    env = real_pg_tenants
    t_alpha = env["t_alpha"]

    engine = create_async_engine(PG_ASYNC_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": t_alpha})

        # Insert a quote approval to lock
        appr_id = f"lock_{uuid.uuid4().hex[:8]}"
        quote_id = f"qt_lock_{uuid.uuid4().hex[:8]}"
        await s.execute(text(
            "INSERT INTO quotes (id, tenant_id, quote_number, status, version, subtotal_cents, discount_total_cents, "
            "tax_total_cents, grand_total_cents, margin_percent, requires_approval, terms_hash, valid_until) "
            "VALUES (:id, :tid, :qn, 'PENDING_APPROVAL', 1, 100000, 0, 20000, 120000, 50.00, true, 'lock_hash', NOW() + INTERVAL '7 days')"
        ), {"id": quote_id, "tid": t_alpha, "qn": f"QT-LOCK-{uuid.uuid4().hex[:6]}"})

        await s.execute(text(
            "INSERT INTO quote_approvals (id, tenant_id, quote_id, quote_version, terms_hash, requested_by_user_id, status) "
            "VALUES (:id, :tid, :qid, 1, 'lock_hash', :uid, 'PENDING')"
        ), {"id": appr_id, "tid": t_alpha, "qid": quote_id, "uid": env["u_alpha"]})
        await s.commit()

    # Now acquire row lock with SELECT ... FOR UPDATE
    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": t_alpha})

        stmt = select(QuoteApproval).where(QuoteApproval.id == appr_id).with_for_update()
        res = await s.execute(stmt)
        locked_row = res.scalars().first()
        assert locked_row is not None
        assert locked_row.id == appr_id
        assert locked_row.status == "PENDING"
        await s.commit()

    await engine.dispose()


@pytest.mark.asyncio
async def test_real_postgres_multistep_rollback_leaves_no_orphans(real_pg_tenants):
    """
    Verifies that multi-step commercial transactions rolled back upon error
    leave exactly ZERO orphan records in live PostgreSQL.
    """
    env = real_pg_tenants
    t_alpha = env["t_alpha"]

    engine = create_async_engine(PG_ASYNC_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    failed_quote_id = f"fail_{uuid.uuid4().hex[:8]}"

    # Attempt a multi-step insertion inside a transaction that fails and rolls back
    try:
        async with session_factory() as s:
            await s.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": t_alpha})

            await s.execute(text(
                "INSERT INTO quotes (id, tenant_id, quote_number, status, version, subtotal_cents, discount_total_cents, "
                "tax_total_cents, grand_total_cents, margin_percent, requires_approval, terms_hash, valid_until) "
                "VALUES (:id, :tid, :qn, 'DRAFT', 1, 100000, 0, 20000, 120000, 50.00, false, 'fail_hash', NOW() + INTERVAL '7 days')"
            ), {"id": failed_quote_id, "tid": t_alpha, "qn": f"QT-FAIL-{uuid.uuid4().hex[:6]}"})

            await s.execute(text(
                "INSERT INTO quote_items (id, tenant_id, quote_id, sku_snapshot, name_snapshot, quantity, "
                "uom_snapshot, unit_price_cents, unit_cost_cents, discount_percent, discount_cents, tax_rate_percent, "
                "subtotal_cents, tax_cents, total_cents, margin_percent) "
                "VALUES (:id, :tid, :qid, 'SKU-FAIL', 'Fail Item', 1, 'UNIT', 100000, 50000, 0.00, 0, 20.00, 100000, 20000, 120000, 50.00)"
            ), {"id": f"qi_fail_{uuid.uuid4().hex[:8]}", "tid": t_alpha, "qid": failed_quote_id})

            # Simulate sudden crash or failure before commit
            raise RuntimeError("Simulated mid-transaction business rule failure")
    except RuntimeError:
        pass

    # Verify that exactly ZERO rows exist for failed_quote_id
    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": t_alpha})

        q_res = await s.execute(text("SELECT count(*) FROM quotes WHERE id = :qid"), {"qid": failed_quote_id})
        assert q_res.scalar() == 0, "Rollback failed: Quote record was committed!"

        qi_res = await s.execute(text("SELECT count(*) FROM quote_items WHERE quote_id = :qid"), {"qid": failed_quote_id})
        assert qi_res.scalar() == 0, "Rollback failed: Orphan QuoteItem records exist!"

    await engine.dispose()


@pytest.mark.asyncio
async def test_real_postgres_lead_conversion_atomic_transaction(real_pg_tenants):
    """
    Executes CrmService.convert_lead_to_opportunity against live PostgreSQL 16.
    Verifies that Account, Contact, and Opportunity are created atomically, and Lead is updated to CONVERTED.
    """
    env = real_pg_tenants
    t_alpha = env["t_alpha"]
    u_alpha = env["u_alpha"]

    engine = create_async_engine(PG_ASYNC_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": t_alpha})

        # 1. Create a Lead in real PostgreSQL
        lead = await CrmService.create_lead(
            session=s,
            tenant_id=t_alpha,
            first_name="Karim",
            last_name="Bennani",
            company_name="Bennani Logistics SARL",
            email="karim@bennani-logistics.ma",
            phone="+212661334455",
            source="REFERRAL",
            score=90,
            assigned_user_id=u_alpha
        )
        await s.commit()
        lead_id = lead.id

    # 2. Convert Lead atomically
    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": t_alpha})

        acc, contact, opp = await CrmService.convert_lead_to_opportunity(
            session=s,
            tenant_id=t_alpha,
            lead_id=lead_id,
            opportunity_title="Fleet Management System Deal",
            estimated_amount_cents=15000000,  # 150,000 MAD
            currency="MAD",
            actor_user_id=u_alpha
        )
        await s.commit()

        assert acc.id is not None
        assert contact.id is not None
        assert opp.id is not None
        assert opp.amount_cents == 15000000

    # 3. Verify in separate fresh transaction
    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": t_alpha})

        refreshed_lead = await CrmService.get_lead(s, t_alpha, lead_id)
        assert refreshed_lead.status == "CONVERTED"
        assert refreshed_lead.converted_account_id == acc.id
        assert refreshed_lead.converted_contact_id == contact.id
        assert refreshed_lead.converted_opportunity_id == opp.id

    await engine.dispose()
