"""
Invoicing API Endpoints.
Invoice Generation, Canonical Hashes, Immutability Guards, and Credit Notes.
(Controls 05, 07, 33, 34, 48, 57, 58)
Step 05: Sprint 3 - Transact
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.invoicing.service import (
    InvoicingService, InvoicingError, InvoiceNotFoundError, ImmutableInvoiceError
)
from src.backend.schemas.invoicing import (
    InvoiceCreateRequest, InvoiceResponse, InvoiceItemResponse, CreditNoteCreateRequest
)
from src.backend.models.entities import Invoice

router = APIRouter(prefix="/invoices", tags=["Invoices & Accounting"])


def map_invoice_to_response(invoice: Invoice) -> InvoiceResponse:
    item_responses = [
        InvoiceItemResponse(
            id=it.id,
            tenant_id=it.tenant_id,
            invoice_id=it.invoice_id,
            sku=it.sku,
            name=it.name,
            quantity=it.quantity,
            unit_price_cents=it.unit_price_cents,
            discount_cents=it.discount_cents,
            tax_rate_percent=float(it.tax_rate_percent),
            tax_cents=it.tax_cents,
            subtotal_cents=it.subtotal_cents,
            total_cents=it.total_cents,
            created_at=it.created_at
        )
        for it in (invoice.items or [])
    ]
    return InvoiceResponse(
        id=invoice.id,
        tenant_id=invoice.tenant_id,
        order_id=invoice.order_id,
        invoice_number=invoice.invoice_number,
        status=invoice.status,
        currency=invoice.currency,
        subtotal_cents=invoice.subtotal_cents,
        discount_total_cents=invoice.discount_total_cents,
        tax_total_cents=invoice.tax_total_cents,
        grand_total_cents=invoice.grand_total_cents,
        terms_hash=invoice.terms_hash,
        invoice_hash=invoice.invoice_hash,
        correction_of_invoice_id=invoice.correction_of_invoice_id,
        issued_at=invoice.issued_at,
        due_date=invoice.due_date,
        paid_at=invoice.paid_at,
        pdf_storage_path=invoice.pdf_storage_path,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
        items=item_responses
    )


@router.post("/from-order", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice_from_order(
    req: InvoiceCreateRequest,
    ctx: SecurityContext = Depends(require_permission("orders:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InvoicingService(db)
    try:
        invoice = await service.create_invoice_from_order(
            tenant_id=ctx.tenant_id,
            order_id=req.order_id,
            due_days=req.due_days,
            notes=req.notes
        )
        return map_invoice_to_response(invoice)
    except InvoicingError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=List[InvoiceResponse])
async def list_invoices(
    ctx: SecurityContext = Depends(require_permission("orders:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InvoicingService(db)
    invoices = await service.list_invoices(tenant_id=ctx.tenant_id)
    return [map_invoice_to_response(inv) for inv in invoices]


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    ctx: SecurityContext = Depends(require_permission("orders:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InvoicingService(db)
    invoice = await service.get_invoice_by_id(tenant_id=ctx.tenant_id, invoice_id=invoice_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return map_invoice_to_response(invoice)


@router.post("/credit-note", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_credit_note(
    req: CreditNoteCreateRequest,
    ctx: SecurityContext = Depends(require_permission("quotes:approve")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InvoicingService(db)
    try:
        cn = await service.create_credit_note(
            tenant_id=ctx.tenant_id,
            original_invoice_id=req.original_invoice_id,
            reason=req.reason,
            amount_cents=req.amount_cents
        )
        return map_invoice_to_response(cn)
    except InvoiceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Original invoice not found")
    except InvoicingError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
