"""
Contract Tests for CRM and Catalog APIs.
Tests HTTP endpoints, authentication, schema validation, tier resolution, and lead conversion.
(Baseline Controls 16, 17, 33, 34, 42, 51)
"""
import pytest
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from datetime import timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.backend.main import app
from src.backend.models.entities import (
    Base, Tenant, User, Role, UserRole, Account, Lead, Opportunity, Activity, Product, ProductVariant, PriceList, PriceListItem
)
from src.backend.core.security import SecurityService
from src.backend.core.database import get_db_session

TEST_DB = "sqlite+aiosqlite:///:memory:"

@asynccontextmanager
async def get_crm_catalog_test_env():
    engine = create_async_engine(
        TEST_DB,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t1 = Tenant(id="t_crm_01", name="CRM Tenant Alpha", slug="crm-tenant-alpha")
        t2 = Tenant(id="t_crm_02", name="CRM Tenant Beta", slug="crm-tenant-beta")
        session.add_all([t1, t2])

        rep = User(
            id="u_rep_crm",
            tenant_id="t_crm_01",
            email="rep@crm.com",
            hashed_password=SecurityService.hash_password("RepPass123!"),
            full_name="CRM Sales Rep",
            is_active=True,
            is_verified=True
        )
        session.add(rep)
        await session.commit()

    async def override_get_db():
        async with session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db

    import src.backend.core.auth_middleware as mw
    import src.backend.core.database as db_mod
    orig_factory = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = session_factory
    mw.AsyncSessionLocal = session_factory

    rep_token, _, _ = SecurityService.create_access_token(
        user_id="u_rep_crm",
        tenant_id="t_crm_01",
        email="rep@crm.com",
        roles=["sales_rep"],
        permissions=["crm:read", "crm:write", "catalog:read", "catalog:write"],
        mfa_verified=True,
        expires_delta=timedelta(minutes=30)
    )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield {
                "client": client,
                "token": rep_token,
                "tenant_id": "t_crm_01",
                "user_id": "u_rep_crm",
                "session_factory": session_factory
            }
    finally:
        db_mod.AsyncSessionLocal = orig_factory
        mw.AsyncSessionLocal = orig_factory
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_accounts_crud_and_validation():
    async with get_crm_catalog_test_env() as env:
        client = env["client"]
        headers = {"Authorization": f"Bearer {env['token']}"}

        # 1. Create Account
        payload = {
            "name": "Acme Atlas SARL",
            "account_type": "CUSTOMER",
            "tax_identifier": "MA12345678",
            "industry": "Manufacturing",
            "website": "https://acme-atlas.ma",
            "phone": "+212522112233",
            "billing_address": "123 Boulevard d'Anfa, Casablanca",
            "shipping_address": "123 Boulevard d'Anfa, Casablanca"
        }
        res = await client.post("/api/v1/crm/accounts", json=payload, headers=headers)
        assert res.status_code == 201, res.text
        data = res.json()
        account_id = data["id"]
        assert data["name"] == "Acme Atlas SARL"
        assert data["tax_identifier"] == "MA12345678"
        assert data["tenant_id"] == env["tenant_id"]

        # 2. List Accounts
        list_res = await client.get("/api/v1/crm/accounts", headers=headers)
        assert list_res.status_code == 200
        accounts = list_res.json()
        assert len(accounts) == 1
        assert accounts[0]["id"] == account_id

        # 3. Get Account by ID
        get_res = await client.get(f"/api/v1/crm/accounts/{account_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["name"] == "Acme Atlas SARL"


@pytest.mark.asyncio
async def test_leads_qualification_and_conversion():
    async with get_crm_catalog_test_env() as env:
        client = env["client"]
        headers = {"Authorization": f"Bearer {env['token']}"}

        # 1. Create Lead
        lead_payload = {
            "first_name": "Taha",
            "last_name": "El Amrani",
            "email": "taha@amrani-tech.ma",
            "phone": "+212661001122",
            "company_name": "Amrani Tech",
            "score": 85,
            "source": "WEBSITE"
        }
        create_res = await client.post("/api/v1/crm/leads", json=lead_payload, headers=headers)
        assert create_res.status_code == 201, create_res.text
        lead_data = create_res.json()
        lead_id = lead_data["id"]
        assert lead_data["first_name"] == "Taha"
        assert lead_data["score"] == 85

        # 2. List Leads
        list_res = await client.get("/api/v1/crm/leads", headers=headers)
        assert list_res.status_code == 200
        assert len(list_res.json()) == 1

        # 3. Convert Lead to Opportunity (Atomic conversion creating Account, Contact, Opp)
        convert_payload = {
            "opportunity_title": "Enterprise Cloud Migration",
            "estimated_amount_cents": 5000000,  # 50,000 MAD
            "currency": "MAD"
        }
        conv_res = await client.post(f"/api/v1/crm/leads/{lead_id}/convert", json=convert_payload, headers=headers)
        assert conv_res.status_code == 200, conv_res.text
        conv_data = conv_res.json()
        assert conv_data["status"] == "success"
        assert conv_data["converted_account_id"] is not None
        assert conv_data["converted_contact_id"] is not None
        assert conv_data["converted_opportunity_id"] is not None

        # Verify Lead state in database
        lead_check = await client.get(f"/api/v1/crm/leads/{lead_id}", headers=headers)
        assert lead_check.status_code == 200
        assert lead_check.json()["status"] == "CONVERTED"

        # Verify created Opportunity
        opp_id = conv_data["converted_opportunity_id"]
        opp_res = await client.get(f"/api/v1/crm/opportunities/{opp_id}", headers=headers)
        assert opp_res.status_code == 200
        opp_data = opp_res.json()
        assert opp_data["title"] == "Enterprise Cloud Migration"
        assert opp_data["amount_cents"] == 5000000

        # 4. Attempt Duplicate Conversion -> MUST return 409 Conflict
        dup_res = await client.post(f"/api/v1/crm/leads/{lead_id}/convert", json=convert_payload, headers=headers)
        assert dup_res.status_code == 409, f"Expected 409 for duplicate conversion, got {dup_res.status_code}"


@pytest.mark.asyncio
async def test_opportunities_and_activities():
    async with get_crm_catalog_test_env() as env:
        client = env["client"]
        headers = {"Authorization": f"Bearer {env['token']}"}

        # 1. Create Account first
        acc_res = await client.post("/api/v1/crm/accounts", json={"name": "Atlas Ventures"}, headers=headers)
        assert acc_res.status_code == 201, acc_res.text
        acc_id = acc_res.json()["id"]

        # 2. Create Opportunity
        opp_payload = {
            "title": "Industrial Automation Deal",
            "account_id": acc_id,
            "stage": "QUALIFICATION",
            "amount_cents": 12500000,  # 125,000 MAD
            "probability_percent": 40
        }
        opp_res = await client.post("/api/v1/crm/opportunities", json=opp_payload, headers=headers)
        assert opp_res.status_code == 201, opp_res.text
        opp_id = opp_res.json()["id"]

        # 3. Update Opportunity Stage
        stage_patch = {"stage": "PROPOSAL"}
        patch_res = await client.patch(f"/api/v1/crm/opportunities/{opp_id}/stage", json=stage_patch, headers=headers)
        assert patch_res.status_code == 200
        assert patch_res.json()["stage"] == "PROPOSAL"

        # 4. Log Activity
        act_payload = {
            "activity_type": "CALL",
            "subject": "Discovery Call with CTO",
            "description": "Reviewed system constraints and architecture requirements.",
            "opportunity_id": opp_id,
            "account_id": acc_id
        }
        act_res = await client.post("/api/v1/crm/activities", json=act_payload, headers=headers)
        assert act_res.status_code == 201
        assert act_res.json()["activity_type"] == "CALL"


@pytest.mark.asyncio
async def test_catalog_products_and_tier_pricing():
    async with get_crm_catalog_test_env() as env:
        client = env["client"]
        headers = {"Authorization": f"Bearer {env['token']}"}

        # 1. Create Product
        prod_payload = {
            "sku": "SRV-ROUTER-AX",
            "name": "Enterprise Security Router AX",
            "category": "HARDWARE",
            "base_price_cents": 100000,  # 1,000 MAD
            "cost_cents": 60000,         # 600 MAD (40% margin)
            "tax_rate_percent": 20.0,
            "uom": "UNIT"
        }
        prod_res = await client.post("/api/v1/catalog/products", json=prod_payload, headers=headers)
        assert prod_res.status_code == 201, prod_res.text
        prod_data = prod_res.json()
        product_id = prod_data["id"]
        assert prod_data["sku"] == "SRV-ROUTER-AX"

        # 2. Add Variant
        var_payload = {
            "sku_variant": "SRV-ROUTER-AX-PRO",
            "name": "Enterprise Security Router AX Pro (Rackmount)",
            "attributes": {"form_factor": "1U Rackmount"},
            "price_adjustment_cents": 25000,
            "cost_adjustment_cents": 15000
        }
        var_res = await client.post(f"/api/v1/catalog/products/{product_id}/variants", json=var_payload, headers=headers)
        assert var_res.status_code == 201, var_res.text
        variant_id = var_res.json()["id"]

        # 3. Create Custom Price List
        pl_payload = {
            "name": "Wholesale VIP Tier",
            "code": "WHOLESALE_VIP",
            "currency": "MAD",
            "description": "Discounted wholesale tiers"
        }
        pl_res = await client.post("/api/v1/catalog/price-lists", json=pl_payload, headers=headers)
        assert pl_res.status_code == 201, pl_res.text
        price_list_id = pl_res.json()["id"]

        # 4. Add Tier Pricing Items
        # Tier 1: 1-9 units -> 950 MAD
        item1_payload = {
            "product_id": product_id,
            "min_quantity": 1,
            "unit_price_cents": 95000
        }
        await client.post(f"/api/v1/catalog/price-lists/{price_list_id}/items", json=item1_payload, headers=headers)

        # Tier 2: 10+ units -> 850 MAD
        item2_payload = {
            "product_id": product_id,
            "min_quantity": 10,
            "unit_price_cents": 85000
        }
        await client.post(f"/api/v1/catalog/price-lists/{price_list_id}/items", json=item2_payload, headers=headers)

        # 5. Verify Tier Resolution via Domain Service
        from src.backend.domains.catalog.service import CatalogService
        async with env["session_factory"]() as s:
            tier1_price = await CatalogService.resolve_unit_price(
                session=s,
                tenant_id=env["tenant_id"],
                product_id=product_id,
                variant_id=None,
                price_list_id=price_list_id,
                quantity=5
            )
            assert tier1_price == 95000, f"Expected 95000 cents for qty 5, got {tier1_price}"

            tier2_price = await CatalogService.resolve_unit_price(
                session=s,
                tenant_id=env["tenant_id"],
                product_id=product_id,
                variant_id=None,
                price_list_id=price_list_id,
                quantity=12
            )
            assert tier2_price == 85000, f"Expected 85000 cents for qty 12, got {tier2_price}"
