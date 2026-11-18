"""
Invoicing Domain Service.
Handles Sequential Invoice Numbering, Cryptographic SHA-256 Invoice Hashes,
Immutability Safeguards, and Credit Note Chains.
(Controls 05, 07, 33, 34, 48, 57, 58)
Step 05: Sprint 3 - Transact
"""
import uuid
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.backend.models.entities import Invoice, InvoiceItem, SalesOrder, AuditEvent
from src.backend.domains.pricing.money import Money


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InvoicingError(Exception):
    pass


class InvoiceNotFoundError(InvoicingError):
    pass


class ImmutableInvoiceError(InvoicingError):
    pass


class InvoicingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def compute_invoice_hash(
        invoice_number: str,
        currency: str,
        subtotal_cents: int,
        discount_total_cents: int,
        tax_total_cents: int,
        grand_total_cents: int,
        items: List[Dict[str, Any]]
    ) -> str:
        canonical_items = []
        for it in sorted(items, key=lambda x: x.get("sku", "")):
            canonical_items.append({
                "sku": it.get("sku"),
                "name": it.get("name"),
                "quantity": it.get("quantity"),
                "unit_price_cents": it.get("unit_price_cents"),
                "discount_cents": it.get("discount_cents", 0),
                "tax_cents": it.get("tax_cents", 0),
                "total_cents": it.get("total_cents")
            })

        payload = {
            "invoice_number": invoice_number.strip(),
            "currency": currency.upper().strip(),
            "subtotal_cents": subtotal_cents,
            "discount_total_cents": discount_total_cents,
            "tax_total_cents": tax_total_cents,
            "grand_total_cents": grand_total_cents,
            "items": canonical_items
        }
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical_bytes).hexdigest()

    async def generate_next_invoice_number(self, tenant_id: str, prefix: str = "INV") -> str:
        current_year = datetime.now().strftime("%Y")
        pattern = f"{prefix}-{current_year}-%"
        stmt = select(func.count(Invoice.id)).where(
            and_(
                Invoice.tenant_id == tenant_id,
                Invoice.invoice_number.like(pattern)
            )
        )
        res = await self.db.execute(stmt)
        count = res.scalar_one() or 0
        seq = count + 1
        return f"{prefix}-{current_year}-{seq:05d}"

    async def create_invoice_from_order(
        self,
        tenant_id: str,
        order_id: str,
        due_days: int = 30,
        notes: Optional[str] = None
    ) -> Invoice:
        # Check if an invoice already exists for this order
        existing_stmt = select(Invoice).where(
            and_(Invoice.order_id == order_id, Invoice.tenant_id == tenant_id)
        ).options(selectinload(Invoice.items))
        existing_res = await self.db.execute(existing_stmt)
        existing = existing_res.scalar_one_or_none()
        if existing:
            return existing

        # Fetch sales order
        order_stmt = select(SalesOrder).where(
            and_(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        ).options(selectinload(SalesOrder.items))
        order_res = await self.db.execute(order_stmt)
        order = order_res.scalar_one_or_none()
        if not order:
            raise InvoicingError(f"Sales order {order_id} not found")

        invoice_number = await self.generate_next_invoice_number(tenant_id, prefix="INV")
        now = utc_now()
        due_date = now + timedelta(days=due_days)

        canonical_items = []
        for oi in order.items:
            canonical_items.append({
                "sku": oi.sku,
                "name": oi.name,
                "quantity": oi.quantity,
                "unit_price_cents": oi.unit_price_cents,
                "discount_cents": oi.discount_cents,
                "tax_cents": oi.tax_cents,
                "total_cents": oi.total_cents
            })

        invoice_hash = self.compute_invoice_hash(
            invoice_number=invoice_number,
            currency=order.currency,
            subtotal_cents=order.subtotal_cents,
            discount_total_cents=order.discount_total_cents,
            tax_total_cents=order.tax_total_cents,
            grand_total_cents=order.grand_total_cents,
            items=canonical_items
        )

        pdf_path = f"invoices/{tenant_id}/{invoice_number}_{invoice_hash[:12]}.pdf"

        invoice = Invoice(
            tenant_id=tenant_id,
            order_id=order.id,
            invoice_number=invoice_number,
            status="PAID" if order.payment_status == "PAID" else "ISSUED",
            currency=order.currency,
            subtotal_cents=order.subtotal_cents,
            discount_total_cents=order.discount_total_cents,
            tax_total_cents=order.tax_total_cents,
            grand_total_cents=order.grand_total_cents,
            terms_hash=order.terms_hash,
            invoice_hash=invoice_hash,
            issued_at=now,
            due_date=due_date,
            paid_at=now if order.payment_status == "PAID" else None,
            pdf_storage_path=pdf_path
        )
        self.db.add(invoice)
        await self.db.flush()

        for it in canonical_items:
            inv_item = InvoiceItem(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                sku=it["sku"],
                name=it["name"],
                quantity=it["quantity"],
                unit_price_cents=it["unit_price_cents"],
                discount_cents=it["discount_cents"],
                tax_rate_percent=20.00,
                tax_cents=it["tax_cents"],
                subtotal_cents=it["unit_price_cents"] * it["quantity"] - it["discount_cents"],
                total_cents=it["total_cents"]
            )
            self.db.add(inv_item)

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=order.created_by_user_id,
            event_type="INVOICE_ISSUED",
            resource_type="INVOICE",
            resource_id=invoice.id,
            action="CREATE",
            status="SUCCESS",
            payload_json=f'{{"invoice_number": "{invoice_number}", "grand_total_cents": {order.grand_total_cents}, "invoice_hash": "{invoice_hash}"}}'
        )
        self.db.add(audit)
        await self.db.flush()

        stmt = select(Invoice).where(Invoice.id == invoice.id).options(selectinload(Invoice.items))
        res = await self.db.execute(stmt)
        return res.scalar_one()

    async def create_credit_note(
        self,
        tenant_id: str,
        original_invoice_id: str,
        reason: str,
        amount_cents: Optional[int] = None
    ) -> Invoice:
        stmt = select(Invoice).where(
            and_(Invoice.id == original_invoice_id, Invoice.tenant_id == tenant_id)
        ).options(selectinload(Invoice.items))
        res = await self.db.execute(stmt)
        orig = res.scalar_one_or_none()
        if not orig:
            raise InvoiceNotFoundError("Original invoice not found")

        credit_amount = amount_cents if amount_cents is not None else orig.grand_total_cents
        cn_number = await self.generate_next_invoice_number(tenant_id, prefix="CN")
        now = utc_now()

        cn_item = {
            "sku": "CREDIT_ADJUSTMENT",
            "name": f"Credit adjustment: {reason}",
            "quantity": 1,
            "unit_price_cents": -credit_amount,
            "discount_cents": 0,
            "tax_cents": 0,
            "total_cents": -credit_amount
        }

        cn_hash = self.compute_invoice_hash(
            invoice_number=cn_number,
            currency=orig.currency,
            subtotal_cents=-credit_amount,
            discount_total_cents=0,
            tax_total_cents=0,
            grand_total_cents=-credit_amount,
            items=[cn_item]
        )

        credit_note = Invoice(
            tenant_id=tenant_id,
            order_id=orig.order_id,
            invoice_number=cn_number,
            status="ISSUED",
            currency=orig.currency,
            subtotal_cents=-credit_amount,
            discount_total_cents=0,
            tax_total_cents=0,
            grand_total_cents=-credit_amount,
            terms_hash=orig.terms_hash,
            invoice_hash=cn_hash,
            correction_of_invoice_id=orig.id,
            issued_at=now,
            due_date=now,
            pdf_storage_path=f"credit_notes/{tenant_id}/{cn_number}_{cn_hash[:12]}.pdf"
        )
        self.db.add(credit_note)
        await self.db.flush()

        cn_invoice_item = InvoiceItem(
            tenant_id=tenant_id,
            invoice_id=credit_note.id,
            sku="CREDIT_ADJUSTMENT",
            name=f"Credit adjustment: {reason}",
            quantity=1,
            unit_price_cents=-credit_amount,
            discount_cents=0,
            tax_rate_percent=0.00,
            tax_cents=0,
            subtotal_cents=-credit_amount,
            total_cents=-credit_amount
        )
        self.db.add(cn_invoice_item)

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=None,
            event_type="CREDIT_NOTE_ISSUED",
            resource_type="INVOICE",
            resource_id=credit_note.id,
            action="CREATE",
            status="SUCCESS",
            payload_json=f'{{"credit_note_number": "{cn_number}", "original_invoice": "{orig.invoice_number}", "amount_cents": {-credit_amount}}}'
        )
        self.db.add(audit)
        await self.db.flush()

        stmt = select(Invoice).where(Invoice.id == credit_note.id).options(selectinload(Invoice.items))
        res = await self.db.execute(stmt)
        return res.scalar_one()

    async def get_invoice_by_id(self, tenant_id: str, invoice_id: str) -> Optional[Invoice]:
        stmt = select(Invoice).where(
            and_(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        ).options(selectinload(Invoice.items))
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_invoices(self, tenant_id: str) -> List[Invoice]:
        stmt = select(Invoice).where(
            Invoice.tenant_id == tenant_id
        ).options(selectinload(Invoice.items)).order_by(Invoice.created_at.desc())
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
