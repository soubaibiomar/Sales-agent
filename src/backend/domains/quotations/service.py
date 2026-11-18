"""
Quotation Lifecycle Domain Service.
Implements the Quote State Machine, optimistic version locking, exact-terms revalidation, and issuance.
(Baseline Controls 16, 17, 33, 42, 57, 58; SAI-08)
"""
import uuid
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.models.entities import (
    Quote, QuoteItem, QuoteApproval, QuoteDocument, Opportunity, Account, Contact, AuditEvent
)
from src.backend.domains.pricing.service import PricingService
from src.backend.domains.pricing.money import Money

class QuoteDomainError(Exception):
    pass

class StaleQuoteError(QuoteDomainError):
    pass

class QuoteApprovalRequiredError(QuoteDomainError):
    pass

class QuoteExpiredError(QuoteDomainError):
    pass

class QuoteNotFoundError(QuoteDomainError):
    pass

class InvalidStateTransitionError(QuoteDomainError):
    pass

class QuotationService:
    """Enterprise domain service for commercial quotation state machine and issuance."""

    @staticmethod
    async def get_quote(
        session: AsyncSession,
        tenant_id: str,
        quote_id: str
    ) -> Optional[Quote]:
        stmt = select(Quote).where(
            Quote.id == quote_id,
            Quote.tenant_id == tenant_id
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def create_draft_quote(
        session: AsyncSession,
        tenant_id: str,
        opportunity_id: Optional[str] = None,
        account_id: Optional[str] = None,
        contact_id: Optional[str] = None,
        price_list_id: Optional[str] = None,
        currency: str = "MAD",
        payment_terms: str = "NET_30",
        valid_days: int = 30,
        notes: Optional[str] = None,
        created_by_user_id: Optional[str] = None
    ) -> Quote:
        now = datetime.now(timezone.utc)
        valid_until = now + timedelta(days=valid_days)
        quote_number = f"QT-{now.strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"

        quote = Quote(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            quote_number=quote_number,
            opportunity_id=opportunity_id,
            account_id=account_id,
            contact_id=contact_id,
            price_list_id=price_list_id,
            currency=currency.upper(),
            status="DRAFT",
            version=1,
            subtotal_cents=0,
            discount_total_cents=0,
            tax_total_cents=0,
            grand_total_cents=0,
            margin_percent=0.00,
            requires_approval=False,
            approval_reason=None,
            terms_hash="draft_uncalculated_hash",
            valid_until=valid_until,
            payment_terms=payment_terms,
            notes=notes,
            created_by_user_id=created_by_user_id
        )
        session.add(quote)
        await session.flush()
        return quote

    @staticmethod
    async def update_and_price_quote(
        session: AsyncSession,
        tenant_id: str,
        quote_id: str,
        item_requests: List[Dict[str, Any]],
        payment_terms: Optional[str] = None,
        expected_version: Optional[int] = None,
        actor_user_id: Optional[str] = None
    ) -> Quote:
        """
        Prices line items, performs optimistic version checks, computes cryptographic terms hash,
        and invalidates prior approvals if terms have changed.
        """
        quote = await QuotationService.get_quote(session, tenant_id, quote_id)
        if not quote:
            raise QuoteNotFoundError(f"Quote '{quote_id}' not found")

        if quote.status in ["ISSUED", "SENT", "ACCEPTED", "CANCELLED"]:
            raise InvalidStateTransitionError(f"Cannot edit quote in '{quote.status}' status")

        # Optimistic concurrency version check
        if expected_version is not None and quote.version != expected_version:
            raise StaleQuoteError(
                f"Quote version conflict: expected version {expected_version}, but current version is {quote.version}"
            )

        pay_terms = payment_terms or quote.payment_terms or "NET_30"

        # Deterministic pricing calculation
        pricing = await PricingService.calculate_quote_pricing(
            session=session,
            tenant_id=tenant_id,
            item_requests=item_requests,
            price_list_id=quote.price_list_id,
            currency=quote.currency,
            payment_terms=pay_terms
        )

        old_terms_hash = quote.terms_hash
        new_terms_hash = pricing["terms_hash"]

        # If terms changed, invalidate any existing pending/approved approvals
        if old_terms_hash != new_terms_hash:
            app_stmt = select(QuoteApproval).where(
                QuoteApproval.quote_id == quote.id,
                QuoteApproval.tenant_id == tenant_id,
                QuoteApproval.status.in_(["PENDING", "APPROVED"])
            )
            app_res = await session.execute(app_stmt)
            for app in app_res.scalars().all():
                app.status = "INVALIDATED"
                app.updated_at = datetime.now(timezone.utc)
                app.decision_reason = "Quote terms changed; prior approval invalidated"

        # Remove existing line items and insert frozen line item snapshots
        del_stmt = select(QuoteItem).where(QuoteItem.quote_id == quote.id)
        del_res = await session.execute(del_stmt)
        for old_item in del_res.scalars().all():
            await session.delete(old_item)

        for it in pricing["items"]:
            quote_item = QuoteItem(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                quote_id=quote.id,
                product_id=it["product_id"],
                variant_id=it["variant_id"],
                sku_snapshot=it["sku_snapshot"],
                name_snapshot=it["name_snapshot"],
                quantity=it["quantity"],
                uom_snapshot=it["uom_snapshot"],
                unit_price_cents=it["unit_price_cents"],
                unit_cost_cents=it["unit_cost_cents"],
                discount_percent=it["discount_percent"],
                discount_cents=it["discount_cents"],
                tax_rate_percent=it["tax_rate_percent"],
                subtotal_cents=it["subtotal_cents"],
                tax_cents=it["tax_cents"],
                total_cents=it["total_cents"],
                margin_percent=it["margin_percent"]
            )
            session.add(quote_item)

        # Update Quote aggregate values and state
        quote.version += 1
        quote.payment_terms = pay_terms
        quote.subtotal_cents = pricing["subtotal_cents"]
        quote.discount_total_cents = pricing["discount_total_cents"]
        quote.tax_total_cents = pricing["tax_total_cents"]
        quote.grand_total_cents = pricing["grand_total_cents"]
        quote.margin_percent = pricing["margin_percent"]
        quote.requires_approval = pricing["requires_approval"]
        quote.approval_reason = pricing["approval_reason"]
        quote.terms_hash = new_terms_hash
        quote.updated_at = datetime.now(timezone.utc)

        if quote.requires_approval:
            quote.status = "PENDING_APPROVAL"
            # Automatically enqueue canonical approval request
            approval_req = QuoteApproval(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                quote_id=quote.id,
                quote_version=quote.version,
                terms_hash=quote.terms_hash,
                requested_by_user_id=actor_user_id or quote.created_by_user_id,
                status="PENDING",
                decision_reason=quote.approval_reason
            )
            session.add(approval_req)
        else:
            quote.status = "PRICED"

        await session.flush()
        return quote

    @staticmethod
    async def issue_quote(
        session: AsyncSession,
        tenant_id: str,
        quote_id: str,
        actor_user_id: Optional[str] = None
    ) -> Tuple[Quote, QuoteDocument]:
        """
        Issues quote, produces cryptographic pro-forma document, and transitions state to ISSUED.
        Requires approved status if requires_approval is true.
        """
        quote = await QuotationService.get_quote(session, tenant_id, quote_id)
        if not quote:
            raise QuoteNotFoundError(f"Quote '{quote_id}' not found")

        if quote.requires_approval and quote.status != "APPROVED":
            raise QuoteApprovalRequiredError(
                f"Quote '{quote.quote_number}' requires manager approval before issuance (current status: {quote.status})"
            )

        if quote.status not in ["PRICED", "APPROVED"]:
            raise InvalidStateTransitionError(f"Cannot issue quote in status '{quote.status}'")

        from src.backend.domains.documents.service import DocumentService
        doc = await DocumentService.generate_quote_document(
            session=session,
            tenant_id=tenant_id,
            quote_id=quote.id,
            document_type="PRO_FORMA"
        )

        quote.status = "ISSUED"
        quote.issued_at = datetime.now(timezone.utc)
        quote.updated_at = quote.issued_at

        # Update linked Opportunity stage to PROPOSAL if applicable
        if quote.opportunity_id:
            opp_stmt = select(Opportunity).where(Opportunity.id == quote.opportunity_id, Opportunity.tenant_id == tenant_id)
            opp_res = await session.execute(opp_stmt)
            opp = opp_res.scalars().first()
            if opp and opp.stage in ["DISCOVERY", "QUALIFICATION"]:
                opp.stage = "PROPOSAL"
                opp.amount_cents = quote.grand_total_cents

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=actor_user_id,
            event_type="QUOTE_ISSUED",
            resource_type="QUOTE",
            resource_id=quote.id,
            action="ISSUE",
            status="SUCCESS",
            payload_json=json.dumps({
                "quote_number": quote.quote_number,
                "version": quote.version,
                "grand_total_cents": quote.grand_total_cents,
                "document_hash": doc.document_hash
            })
        )
        session.add(audit)
        await session.flush()
        return quote, doc

    @staticmethod
    async def send_quote(
        session: AsyncSession,
        tenant_id: str,
        quote_id: str,
        actor_user_id: Optional[str] = None
    ) -> Quote:
        quote = await QuotationService.get_quote(session, tenant_id, quote_id)
        if not quote:
            raise QuoteNotFoundError(f"Quote '{quote_id}' not found")

        if quote.status != "ISSUED":
            raise InvalidStateTransitionError(f"Quote must be ISSUED before sending, got '{quote.status}'")

        quote.status = "SENT"
        quote.updated_at = datetime.now(timezone.utc)
        await session.flush()
        return quote

    @staticmethod
    async def accept_quote(
        session: AsyncSession,
        tenant_id: str,
        quote_id: str,
        signature_or_note: Optional[str] = None
    ) -> Quote:
        quote = await QuotationService.get_quote(session, tenant_id, quote_id)
        if not quote:
            raise QuoteNotFoundError(f"Quote '{quote_id}' not found")

        now = datetime.now(timezone.utc)
        # Check expiration
        valid_until = quote.valid_until
        if valid_until is not None:
            if valid_until.tzinfo is None:
                valid_until = valid_until.replace(tzinfo=timezone.utc)
            if valid_until < now:
                quote.status = "EXPIRED"
                quote.updated_at = now
                await session.flush()
                raise QuoteExpiredError(f"Quote '{quote.quote_number}' expired on {quote.valid_until.isoformat()}")

        if quote.status not in ["ISSUED", "SENT"]:
            raise InvalidStateTransitionError(f"Cannot accept quote in '{quote.status}' status")

        quote.status = "ACCEPTED"
        quote.accepted_at = now
        quote.updated_at = now

        # Advance Opportunity to CLOSED_WON
        if quote.opportunity_id:
            opp_stmt = select(Opportunity).where(Opportunity.id == quote.opportunity_id, Opportunity.tenant_id == tenant_id)
            opp_res = await session.execute(opp_stmt)
            opp = opp_res.scalars().first()
            if opp:
                opp.stage = "CLOSED_WON"
                opp.probability_percent = 100
                opp.amount_cents = quote.grand_total_cents

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id="customer",
            event_type="QUOTE_ACCEPTED",
            resource_type="QUOTE",
            resource_id=quote.id,
            action="ACCEPT",
            status="SUCCESS",
            payload_json=json.dumps({
                "quote_number": quote.quote_number,
                "grand_total_cents": quote.grand_total_cents,
                "note": signature_or_note
            })
        )
        session.add(audit)
        await session.flush()
        return quote

    @staticmethod
    async def reject_quote(
        session: AsyncSession,
        tenant_id: str,
        quote_id: str,
        reason: Optional[str] = None
    ) -> Quote:
        quote = await QuotationService.get_quote(session, tenant_id, quote_id)
        if not quote:
            raise QuoteNotFoundError(f"Quote '{quote_id}' not found")

        quote.status = "REJECTED"
        quote.updated_at = datetime.now(timezone.utc)

        if quote.opportunity_id:
            opp_stmt = select(Opportunity).where(Opportunity.id == quote.opportunity_id, Opportunity.tenant_id == tenant_id)
            opp_res = await session.execute(opp_stmt)
            opp = opp_res.scalars().first()
            if opp:
                opp.stage = "CLOSED_LOST"
                opp.probability_percent = 0
                opp.lost_reason = reason or "Quote rejected by customer"

        await session.flush()
        return quote
