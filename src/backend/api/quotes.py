"""
Quotation & Pro-Forma API Endpoints.
(Baseline Controls 16, 17, 33, 42, 51, 57, 58)
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.core.config import settings
from src.backend.core.database import bind_tenant_context
from src.backend.core.signed_links import issue_link_token, verify_link_token, SignedLinkError

QUOTE_LINK_PURPOSE = "quote_response"
from src.backend.domains.quotations.service import (
    QuotationService, QuoteDomainError, StaleQuoteError,
    QuoteApprovalRequiredError, QuoteExpiredError, QuoteNotFoundError, InvalidStateTransitionError
)
from src.backend.domains.documents.service import DocumentService
from src.backend.schemas.quotes import (
    QuoteCreateRequest, QuoteUpdateRequest, QuoteResponse,
    QuoteItemResponse, QuoteSendRequest, QuoteAcceptRequest, QuoteRejectRequest
)
from src.backend.models.entities import Quote, QuoteItem, QuoteDocument

router = APIRouter(prefix="/quotes", tags=["Quotations & Pro-Formas"])

def map_quote_to_response(quote: Quote, items: List[QuoteItem]) -> QuoteResponse:
    item_responses = [
        QuoteItemResponse(
            id=it.id,
            quote_id=it.quote_id,
            product_id=it.product_id,
            variant_id=it.variant_id,
            sku_snapshot=it.sku_snapshot,
            name_snapshot=it.name_snapshot,
            quantity=it.quantity,
            uom_snapshot=it.uom_snapshot,
            unit_price_cents=it.unit_price_cents,
            unit_cost_cents=it.unit_cost_cents,
            discount_percent=it.discount_percent,
            discount_cents=it.discount_cents,
            tax_rate_percent=it.tax_rate_percent,
            subtotal_cents=it.subtotal_cents,
            tax_cents=it.tax_cents,
            total_cents=it.total_cents,
            margin_percent=it.margin_percent
        )
        for it in items
    ]
    return QuoteResponse(
        id=quote.id,
        tenant_id=quote.tenant_id,
        quote_number=quote.quote_number,
        opportunity_id=quote.opportunity_id,
        account_id=quote.account_id,
        contact_id=quote.contact_id,
        price_list_id=quote.price_list_id,
        currency=quote.currency,
        status=quote.status,
        version=quote.version,
        subtotal_cents=quote.subtotal_cents,
        discount_total_cents=quote.discount_total_cents,
        tax_total_cents=quote.tax_total_cents,
        grand_total_cents=quote.grand_total_cents,
        margin_percent=quote.margin_percent,
        requires_approval=quote.requires_approval,
        approval_reason=quote.approval_reason,
        terms_hash=quote.terms_hash,
        valid_until=quote.valid_until,
        payment_terms=quote.payment_terms,
        notes=quote.notes,
        issued_at=quote.issued_at,
        accepted_at=quote.accepted_at,
        created_by_user_id=quote.created_by_user_id,
        items=item_responses,
        created_at=quote.created_at,
        updated_at=quote.updated_at
    )

@router.post("", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED)
async def create_draft_quote(
    req: QuoteCreateRequest,
    context: SecurityContext = Depends(require_permission("quotes:create")),
    db: AsyncSession = Depends(get_db_session)
):
    quote = await QuotationService.create_draft_quote(
        session=db,
        tenant_id=context.tenant_id,
        opportunity_id=req.opportunity_id,
        account_id=req.account_id,
        contact_id=req.contact_id,
        price_list_id=req.price_list_id,
        currency=req.currency,
        payment_terms=req.payment_terms,
        valid_days=req.valid_days,
        notes=req.notes,
        created_by_user_id=context.user_id
    )
    return map_quote_to_response(quote, [])

@router.get("", response_model=List[QuoteResponse])
async def list_quotes(
    status_filter: Optional[str] = Query(None, alias="status"),
    opportunity_id: Optional[str] = None,
    account_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    context: SecurityContext = Depends(require_permission("quotes:read")),
    db: AsyncSession = Depends(get_db_session)
):
    stmt = select(Quote).where(Quote.tenant_id == context.tenant_id)
    if status_filter:
        stmt = stmt.where(Quote.status == status_filter.upper())
    if opportunity_id:
        stmt = stmt.where(Quote.opportunity_id == opportunity_id)
    if account_id:
        stmt = stmt.where(Quote.account_id == account_id)
    stmt = stmt.order_by(Quote.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    quotes = list(res.scalars().all())

    output = []
    for q in quotes:
        i_stmt = select(QuoteItem).where(QuoteItem.quote_id == q.id).order_by(QuoteItem.created_at.asc())
        i_res = await db.execute(i_stmt)
        items = list(i_res.scalars().all())
        output.append(map_quote_to_response(q, items))
    return output

@router.get("/{quote_id}", response_model=QuoteResponse)
async def get_quote(
    quote_id: str,
    context: SecurityContext = Depends(require_permission("quotes:read")),
    db: AsyncSession = Depends(get_db_session)
):
    quote = await QuotationService.get_quote(db, context.tenant_id, quote_id)
    if not quote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
    i_stmt = select(QuoteItem).where(QuoteItem.quote_id == quote.id).order_by(QuoteItem.created_at.asc())
    i_res = await db.execute(i_stmt)
    items = list(i_res.scalars().all())
    return map_quote_to_response(quote, items)

@router.put("/{quote_id}/items", response_model=QuoteResponse)
async def update_and_price_quote(
    quote_id: str,
    req: QuoteUpdateRequest,
    context: SecurityContext = Depends(require_permission("quotes:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        raw_items = [it.model_dump() for it in req.items]
        quote = await QuotationService.update_and_price_quote(
            session=db,
            tenant_id=context.tenant_id,
            quote_id=quote_id,
            item_requests=raw_items,
            payment_terms=req.payment_terms,
            expected_version=req.expected_version,
            actor_user_id=context.user_id
        )
        i_stmt = select(QuoteItem).where(QuoteItem.quote_id == quote.id).order_by(QuoteItem.created_at.asc())
        i_res = await db.execute(i_stmt)
        items = list(i_res.scalars().all())
        return map_quote_to_response(quote, items)
    except QuoteNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except StaleQuoteError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except QuoteDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/{quote_id}/issue")
async def issue_quote(
    quote_id: str,
    context: SecurityContext = Depends(require_permission("quotes:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        quote, doc = await QuotationService.issue_quote(
            session=db,
            tenant_id=context.tenant_id,
            quote_id=quote_id,
            actor_user_id=context.user_id
        )
        return {
            "status": "success",
            "quote_number": quote.quote_number,
            "version": quote.version,
            "quote_status": quote.status,
            "document_hash": doc.document_hash,
            "document_path": doc.file_path,
            "issued_at": quote.issued_at.isoformat()
        }
    except QuoteNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except QuoteApprovalRequiredError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except QuoteDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/{quote_id}/send")
async def send_quote(
    quote_id: str,
    req: QuoteSendRequest,
    context: SecurityContext = Depends(require_permission("quotes:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        quote = await QuotationService.send_quote(
            session=db,
            tenant_id=context.tenant_id,
            quote_id=quote_id,
            actor_user_id=context.user_id
        )
        # F-14: the customer receives a signed link bound to this tenant, quote and
        # version; editing the quote later bumps the version and voids the link.
        token = issue_link_token(
            QUOTE_LINK_PURPOSE, context.tenant_id, quote.id, quote.version,
            ttl_seconds=settings.quote_link_ttl_days * 86400
        )
        return {
            "status": "success",
            "quote_status": quote.status,
            "recipient": req.recipient_identifier,
            "channel": req.channel_type,
            "acceptance_token": token,
            "acceptance_path": f"/quote_view.html?quote={quote.id}&token={token}"
        }
    except QuoteNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except QuoteDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

async def _load_quote_from_link(db: AsyncSession, quote_id: str, token: str) -> Quote:
    """Resolves a public quote action through a verified signed link (F-14)."""
    try:
        claims = verify_link_token(token, QUOTE_LINK_PURPOSE, quote_id)
    except SignedLinkError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    await bind_tenant_context(db, claims.tenant_id)
    quote = (await db.execute(
        select(Quote).where(Quote.id == quote_id, Quote.tenant_id == claims.tenant_id)
    )).scalars().first()
    if not quote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
    if quote.version != claims.version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Quote terms changed since this link was issued; request a new link.")
    return quote


@router.post("/{quote_id}/accept")
async def customer_accept_quote(
    quote_id: str,
    req: QuoteAcceptRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Public customer acceptance through the signed link sent with the quote (F-14).
    """
    quote = await _load_quote_from_link(db, quote_id, req.acceptance_token)
    client_ip = request.client.host if request.client else "unknown"
    note = (req.signature_or_note or "").strip()
    try:
        accepted = await QuotationService.accept_quote(
            session=db,
            tenant_id=quote.tenant_id,
            quote_id=quote.id,
            signature_or_note=f"{note} [accepted via signed link from {client_ip}]".strip()
        )
        return {
            "status": "success",
            "quote_number": accepted.quote_number,
            "quote_status": accepted.status,
            "accepted_at": accepted.accepted_at.isoformat()
        }
    except QuoteExpiredError as e:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(e))
    except QuoteDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/{quote_id}/reject")
async def customer_reject_quote(
    quote_id: str,
    req: QuoteRejectRequest,
    db: AsyncSession = Depends(get_db_session)
):
    quote = await _load_quote_from_link(db, quote_id, req.acceptance_token)
    try:
        rejected = await QuotationService.reject_quote(
            session=db,
            tenant_id=quote.tenant_id,
            quote_id=quote.id,
            reason=req.reason
        )
    except QuoteDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {
        "status": "success",
        "quote_number": rejected.quote_number,
        "quote_status": rejected.status
    }

@router.get("/{quote_id}/document")
async def get_quote_document(
    quote_id: str,
    context: SecurityContext = Depends(require_permission("quotes:read")),
    db: AsyncSession = Depends(get_db_session)
):
    doc_stmt = (
        select(QuoteDocument)
        .where(
            QuoteDocument.quote_id == quote_id,
            QuoteDocument.tenant_id == context.tenant_id
        )
        .order_by(QuoteDocument.created_at.desc())
    )
    res = await db.execute(doc_stmt)
    doc = res.scalars().first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote document not found or quote not issued yet")

    return {
        "document_type": doc.document_type,
        "document_hash": doc.document_hash,
        "file_path": doc.file_path,
        "content": doc.content_json
    }
