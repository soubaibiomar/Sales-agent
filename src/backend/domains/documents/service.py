"""
Document Generation Domain Service.
Generates canonical, hash-addressed pro-forma invoices and formal quote documents.
(Baseline Controls 16, 17, 33, 42)
"""
import uuid
import json
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.models.entities import Quote, QuoteItem, QuoteDocument, Tenant, Account, Contact
from src.backend.domains.pricing.money import Money

class DocumentDomainError(Exception):
    pass

class DocumentService:
    """Enterprise domain service for cryptographic hash-addressed commercial documents."""

    @staticmethod
    async def generate_quote_document(
        session: AsyncSession,
        tenant_id: str,
        quote_id: str,
        document_type: str = "PRO_FORMA"
    ) -> QuoteDocument:
        # Fetch Quote with items
        q_stmt = select(Quote).where(Quote.id == quote_id, Quote.tenant_id == tenant_id)
        q_res = await session.execute(q_stmt)
        quote = q_res.scalars().first()
        if not quote:
            raise DocumentDomainError(f"Quote '{quote_id}' not found")

        items_stmt = select(QuoteItem).where(QuoteItem.quote_id == quote.id).order_by(QuoteItem.sku_snapshot.asc())
        items_res = await session.execute(items_stmt)
        items = list(items_res.scalars().all())

        # Fetch Tenant info
        t_stmt = select(Tenant).where(Tenant.id == tenant_id)
        t_res = await session.execute(t_stmt)
        tenant = t_res.scalars().first()
        tenant_name = tenant.name if tenant else "Sales AI Tenant"

        # Fetch Account & Contact info
        account_name = "Direct Customer"
        billing_address = None
        if quote.account_id:
            acc_stmt = select(Account).where(Account.id == quote.account_id, Account.tenant_id == tenant_id)
            acc_res = await session.execute(acc_stmt)
            acc = acc_res.scalars().first()
            if acc:
                account_name = acc.name
                billing_address = acc.billing_address

        contact_name = None
        contact_email = None
        if quote.contact_id:
            c_stmt = select(Contact).where(Contact.id == quote.contact_id, Contact.tenant_id == tenant_id)
            c_res = await session.execute(c_stmt)
            c = c_res.scalars().first()
            if c:
                contact_name = c.display_name
                contact_email = c.primary_email

        # Build Canonical Document Structure
        doc_items = []
        for it in items:
            doc_items.append({
                "sku": it.sku_snapshot,
                "name": it.name_snapshot,
                "quantity": it.quantity,
                "uom": it.uom_snapshot,
                "unit_price_cents": it.unit_price_cents,
                "unit_price_formatted": Money(it.unit_price_cents, quote.currency).format(),
                "discount_percent": str(it.discount_percent),
                "discount_cents": it.discount_cents,
                "tax_rate_percent": str(it.tax_rate_percent),
                "subtotal_cents": it.subtotal_cents,
                "tax_cents": it.tax_cents,
                "total_cents": it.total_cents,
                "total_formatted": Money(it.total_cents, quote.currency).format()
            })

        canonical_doc = {
            "document_type": document_type.upper(),
            "quote_number": quote.quote_number,
            "version": quote.version,
            "terms_hash": quote.terms_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
            "payment_terms": quote.payment_terms,
            "issuer": {
                "tenant_id": tenant_id,
                "tenant_name": tenant_name
            },
            "recipient": {
                "account_name": account_name,
                "contact_name": contact_name,
                "contact_email": contact_email,
                "billing_address": billing_address
            },
            "currency": quote.currency,
            "financials": {
                "subtotal_cents": quote.subtotal_cents,
                "subtotal_formatted": Money(quote.subtotal_cents, quote.currency).format(),
                "discount_total_cents": quote.discount_total_cents,
                "discount_total_formatted": Money(quote.discount_total_cents, quote.currency).format(),
                "tax_total_cents": quote.tax_total_cents,
                "tax_total_formatted": Money(quote.tax_total_cents, quote.currency).format(),
                "grand_total_cents": quote.grand_total_cents,
                "grand_total_formatted": Money(quote.grand_total_cents, quote.currency).format()
            },
            "items": doc_items
        }

        canonical_json_str = json.dumps(canonical_doc, sort_keys=True, indent=2)
        document_hash = hashlib.sha256(canonical_json_str.encode("utf-8")).hexdigest()
        file_path = f"documents/{tenant_id}/quotes/{quote.quote_number}_v{quote.version}_{document_hash[:8]}.json"

        quote_doc = QuoteDocument(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            quote_id=quote.id,
            quote_version=quote.version,
            document_type=document_type.upper(),
            document_hash=document_hash,
            file_path=file_path,
            content_json=canonical_json_str
        )
        session.add(quote_doc)
        await session.flush()
        return quote_doc

    @staticmethod
    async def get_document(
        session: AsyncSession,
        tenant_id: str,
        document_id_or_hash: str
    ) -> Optional[QuoteDocument]:
        stmt = select(QuoteDocument).where(
            QuoteDocument.tenant_id == tenant_id,
            (QuoteDocument.id == document_id_or_hash) | (QuoteDocument.document_hash == document_id_or_hash)
        )
        res = await session.execute(stmt)
        return res.scalars().first()
