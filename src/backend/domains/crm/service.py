"""
CRM Domain Service.
Manages Accounts, Leads, Opportunities, Activities, and deterministic Lead Conversion.
(Baseline Controls 16, 17, 33, 42)
"""
import uuid
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import engine
from src.backend.models.entities import (
    Account, Contact, Lead, Opportunity, Activity, AuditEvent, User
)

class CrmDomainError(Exception):
    pass

class LeadAlreadyConvertedError(CrmDomainError):
    pass

class AccountNotFoundError(CrmDomainError):
    pass

class OpportunityNotFoundError(CrmDomainError):
    pass

class CrmService:
    """Enterprise domain service for CRM business entities and lead conversion."""

    # -------------------------------------------------------------------------
    # 1. Accounts Management
    # -------------------------------------------------------------------------
    @staticmethod
    async def create_account(
        session: AsyncSession,
        tenant_id: str,
        name: str,
        account_type: str = "CUSTOMER",
        tax_identifier: Optional[str] = None,
        industry: Optional[str] = None,
        website: Optional[str] = None,
        phone: Optional[str] = None,
        billing_address: Optional[str] = None,
        shipping_address: Optional[str] = None,
        assigned_user_id: Optional[str] = None,
        metadata_json: Optional[str] = "{}"
    ) -> Account:
        clean_name = name.strip()
        if not clean_name:
            raise CrmDomainError("Account name cannot be empty")

        account = Account(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=clean_name,
            account_type=account_type.upper(),
            tax_identifier=tax_identifier.strip() if tax_identifier else None,
            industry=industry.strip() if industry else None,
            website=website.strip() if website else None,
            phone=phone.strip() if phone else None,
            billing_address=billing_address,
            shipping_address=shipping_address,
            assigned_user_id=assigned_user_id,
            metadata_json=metadata_json or "{}"
        )
        session.add(account)
        await session.flush()
        return account

    @staticmethod
    async def get_account(
        session: AsyncSession,
        tenant_id: str,
        account_id: str
    ) -> Optional[Account]:
        stmt = select(Account).where(
            Account.id == account_id,
            Account.tenant_id == tenant_id
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def list_accounts(
        session: AsyncSession,
        tenant_id: str,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Account]:
        stmt = select(Account).where(Account.tenant_id == tenant_id)
        if is_active is not None:
            stmt = stmt.where(Account.is_active == is_active)
        stmt = stmt.order_by(Account.name.asc()).limit(limit).offset(offset)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    # -------------------------------------------------------------------------
    # 2. Leads Management & Conversion
    # -------------------------------------------------------------------------
    @staticmethod
    async def create_lead(
        session: AsyncSession,
        tenant_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        company_name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        source: str = "MANUAL",
        score: int = 10,
        assigned_user_id: Optional[str] = None,
        notes: Optional[str] = None,
        metadata_json: Optional[str] = "{}"
    ) -> Lead:
        if not company_name and not (first_name or last_name) and not email and not phone:
            raise CrmDomainError("Lead requires at least a company name, personal name, email, or phone")

        lead = Lead(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            first_name=first_name.strip() if first_name else None,
            last_name=last_name.strip() if last_name else None,
            company_name=company_name.strip() if company_name else None,
            email=email.strip().lower() if email else None,
            phone=phone.strip() if phone else None,
            status="NEW",
            source=source.upper(),
            score=max(0, min(100, score)),
            assigned_user_id=assigned_user_id,
            notes=notes,
            metadata_json=metadata_json or "{}"
        )
        session.add(lead)
        await session.flush()
        return lead

    @staticmethod
    async def get_lead(
        session: AsyncSession,
        tenant_id: str,
        lead_id: str
    ) -> Optional[Lead]:
        stmt = select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == tenant_id
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def list_leads(
        session: AsyncSession,
        tenant_id: str,
        status: Optional[str] = None,
        assigned_user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Lead]:
        stmt = select(Lead).where(Lead.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(Lead.status == status.upper())
        if assigned_user_id:
            stmt = stmt.where(Lead.assigned_user_id == assigned_user_id)
        stmt = stmt.order_by(Lead.created_at.desc()).limit(limit).offset(offset)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def convert_lead_to_opportunity(
        session: AsyncSession,
        tenant_id: str,
        lead_id: str,
        opportunity_title: str,
        estimated_amount_cents: int = 0,
        currency: str = "MAD",
        actor_user_id: Optional[str] = None
    ) -> Tuple[Account, Contact, Opportunity]:
        """
        Converts a qualified Lead into an Account, Contact, and Opportunity in a single atomic transaction.
        """
        stmt = select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == tenant_id
        )
        res = await session.execute(stmt)
        lead = res.scalars().first()
        if not lead:
            raise CrmDomainError(f"Lead '{lead_id}' not found")
        if lead.status == "CONVERTED":
            raise LeadAlreadyConvertedError(f"Lead '{lead_id}' has already been converted")

        # 1. Create or resolve Account
        acc_name = lead.company_name or f"{lead.first_name or ''} {lead.last_name or 'Account'}".strip() or "Unnamed Account"
        account = await CrmService.create_account(
            session=session,
            tenant_id=tenant_id,
            name=acc_name,
            phone=lead.phone,
            assigned_user_id=lead.assigned_user_id
        )

        # 2. Create Contact linked to Account
        contact_display = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email or "Lead Contact"
        contact = Contact(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            account_id=account.id,
            first_name=lead.first_name,
            last_name=lead.last_name,
            display_name=contact_display,
            primary_email=lead.email,
            primary_phone=lead.phone,
            is_verified=False
        )
        session.add(contact)
        await session.flush()

        # 3. Create Opportunity
        opp = Opportunity(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            account_id=account.id,
            contact_id=contact.id,
            lead_id=lead.id,
            title=opportunity_title.strip(),
            stage="QUALIFICATION",
            amount_cents=estimated_amount_cents,
            currency=currency.upper(),
            probability_percent=30,
            assigned_user_id=lead.assigned_user_id or actor_user_id
        )
        session.add(opp)
        await session.flush()

        # 4. Mark Lead as Converted
        lead.status = "CONVERTED"
        lead.converted_account_id = account.id
        lead.converted_contact_id = contact.id
        lead.converted_opportunity_id = opp.id
        lead.updated_at = datetime.now(timezone.utc)
        await session.flush()

        # 5. Audit Log
        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=actor_user_id or lead.assigned_user_id,
            event_type="LEAD_CONVERTED",
            resource_type="LEAD",
            resource_id=lead.id,
            action="CONVERT",
            status="SUCCESS",
            payload_json=json.dumps({
                "lead_id": lead.id,
                "account_id": account.id,
                "contact_id": contact.id,
                "opportunity_id": opp.id
            })
        )
        session.add(audit)
        await session.flush()

        return account, contact, opp

    # -------------------------------------------------------------------------
    # 3. Opportunities Management
    # -------------------------------------------------------------------------
    @staticmethod
    async def create_opportunity(
        session: AsyncSession,
        tenant_id: str,
        account_id: str,
        title: str,
        amount_cents: int = 0,
        currency: str = "MAD",
        contact_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        stage: str = "DISCOVERY",
        probability_percent: int = 20,
        expected_close_date: Optional[datetime] = None,
        assigned_user_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Opportunity:
        # Validate account exists in tenant
        account = await CrmService.get_account(session, tenant_id, account_id)
        if not account:
            raise AccountNotFoundError(f"Account '{account_id}' does not exist in tenant")

        opp = Opportunity(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            account_id=account_id,
            contact_id=contact_id,
            lead_id=lead_id,
            title=title.strip(),
            stage=stage.upper(),
            amount_cents=amount_cents,
            currency=currency.upper(),
            probability_percent=probability_percent,
            expected_close_date=expected_close_date,
            assigned_user_id=assigned_user_id,
            notes=notes
        )
        session.add(opp)
        await session.flush()
        return opp

    @staticmethod
    async def get_opportunity(
        session: AsyncSession,
        tenant_id: str,
        opportunity_id: str
    ) -> Optional[Opportunity]:
        stmt = select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.tenant_id == tenant_id
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def list_opportunities(
        session: AsyncSession,
        tenant_id: str,
        stage: Optional[str] = None,
        account_id: Optional[str] = None,
        assigned_user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Opportunity]:
        stmt = select(Opportunity).where(Opportunity.tenant_id == tenant_id)
        if stage:
            stmt = stmt.where(Opportunity.stage == stage.upper())
        if account_id:
            stmt = stmt.where(Opportunity.account_id == account_id)
        if assigned_user_id:
            stmt = stmt.where(Opportunity.assigned_user_id == assigned_user_id)
        stmt = stmt.order_by(Opportunity.created_at.desc()).limit(limit).offset(offset)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def update_opportunity_stage(
        session: AsyncSession,
        tenant_id: str,
        opportunity_id: str,
        new_stage: str,
        lost_reason: Optional[str] = None,
        actor_user_id: Optional[str] = None
    ) -> Opportunity:
        opp = await CrmService.get_opportunity(session, tenant_id, opportunity_id)
        if not opp:
            raise OpportunityNotFoundError(f"Opportunity '{opportunity_id}' not found")

        old_stage = opp.stage
        opp.stage = new_stage.upper()
        if opp.stage == "CLOSED_WON":
            opp.probability_percent = 100
        elif opp.stage == "CLOSED_LOST":
            opp.probability_percent = 0
            opp.lost_reason = lost_reason
        opp.updated_at = datetime.now(timezone.utc)
        await session.flush()

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=actor_user_id,
            event_type="OPPORTUNITY_STAGE_CHANGED",
            resource_type="OPPORTUNITY",
            resource_id=opp.id,
            action="UPDATE_STAGE",
            status="SUCCESS",
            payload_json=json.dumps({"old_stage": old_stage, "new_stage": opp.stage, "amount_cents": opp.amount_cents})
        )
        session.add(audit)
        await session.flush()
        return opp

    # -------------------------------------------------------------------------
    # 4. Activities Management
    # -------------------------------------------------------------------------
    @staticmethod
    async def log_activity(
        session: AsyncSession,
        tenant_id: str,
        activity_type: str,
        subject: str,
        description: Optional[str] = None,
        due_date: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        assigned_user_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        opportunity_id: Optional[str] = None,
        account_id: Optional[str] = None,
        contact_id: Optional[str] = None
    ) -> Activity:
        activity = Activity(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            activity_type=activity_type.upper(),
            subject=subject.strip(),
            description=description,
            due_date=due_date,
            completed_at=completed_at,
            assigned_user_id=assigned_user_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            account_id=account_id,
            contact_id=contact_id
        )
        session.add(activity)
        await session.flush()
        return activity
