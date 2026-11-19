"""
Support, Warranties & Return Authorizations (RMA) REST API Endpoints.
Tickets, Warranty Eligibility, Return Inspections, and Stock/Refund Handoffs.
(Controls 05, 06, 07, 16, 21, 22, 57, 58)
Step 06: Sprint 3 - Operate
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.support.service import (
    SupportService, SupportError, TicketNotFoundError,
    WarrantyClaimNotFoundError, RMANotFoundError, InvalidReturnStateError, WarrantyExpiredError
)
from src.backend.schemas.support import (
    SupportTicketCreateRequest, SupportTicketUpdateRequest, SupportTicketResponse,
    TicketMessageCreateRequest, TicketMessageResponse,
    WarrantyClaimCreateRequest, WarrantyClaimResponse,
    ReturnAuthorizationCreateRequest, ReturnAuthorizationResponse, ReturnInspectionRequest
)

router = APIRouter(prefix="/support", tags=["Support & Returns"])


# -----------------------------------------------------------------------------
# 1. SUPPORT TICKETS
# -----------------------------------------------------------------------------
@router.post("/tickets", response_model=SupportTicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    req: SupportTicketCreateRequest,
    ctx: SecurityContext = Depends(require_permission("support:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    return await service.create_ticket(
        tenant_id=ctx.tenant_id,
        subject=req.subject,
        description=req.description,
        category=req.category,
        priority=req.priority,
        order_id=req.order_id,
        account_id=req.account_id,
        contact_id=req.contact_id
    )


@router.get("/tickets", response_model=List[SupportTicketResponse])
async def list_tickets(
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = None,
    order_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: SecurityContext = Depends(require_permission("support:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    return await service.list_tickets(
        ctx.tenant_id, status=status_filter, category=category, order_id=order_id, limit=limit, offset=offset
    )


@router.get("/tickets/{ticket_id}", response_model=SupportTicketResponse)
async def get_ticket(
    ticket_id: str,
    ctx: SecurityContext = Depends(require_permission("support:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    try:
        return await service.get_ticket(ctx.tenant_id, ticket_id)
    except TicketNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/tickets/{ticket_id}/messages", response_model=TicketMessageResponse, status_code=status.HTTP_201_CREATED)
async def add_ticket_message(
    ticket_id: str,
    req: TicketMessageCreateRequest,
    ctx: SecurityContext = Depends(require_permission("support:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    try:
        return await service.add_message(
            tenant_id=ctx.tenant_id,
            ticket_id=ticket_id,
            sender_type=req.sender_type,
            message_text=req.message_text,
            sender_user_id=ctx.user_id,
            attachments=req.attachments_json
        )
    except TicketNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/tickets/{ticket_id}/status", response_model=SupportTicketResponse)
async def update_ticket_status(
    ticket_id: str,
    req: SupportTicketUpdateRequest,
    ctx: SecurityContext = Depends(require_permission("support:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    try:
        new_status = req.status or "IN_PROGRESS"
        return await service.update_ticket_status(
            ctx.tenant_id, ticket_id, new_status=new_status, assigned_user_id=req.assigned_user_id
        )
    except TicketNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# -----------------------------------------------------------------------------
# 2. WARRANTY CLAIMS
# -----------------------------------------------------------------------------
@router.post("/warranties/claims", response_model=WarrantyClaimResponse, status_code=status.HTTP_201_CREATED)
async def create_warranty_claim(
    req: WarrantyClaimCreateRequest,
    ctx: SecurityContext = Depends(require_permission("support:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    try:
        return await service.create_warranty_claim(
            tenant_id=ctx.tenant_id,
            order_id=req.order_id,
            order_item_id=req.order_item_id,
            sku=req.sku,
            claim_reason=req.claim_reason,
            serial_number=req.serial_number,
            ticket_id=req.ticket_id,
            warranty_days=req.warranty_days
        )
    except WarrantyExpiredError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except SupportError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/warranties/claims/{claim_id}/validate", response_model=WarrantyClaimResponse)
async def validate_warranty_claim(
    claim_id: str,
    claim_status: str = Query(..., description="VALIDATED, REJECTED, REPLACEMENT_ISSUED, REFUNDED"),
    inspection_notes: Optional[str] = None,
    ctx: SecurityContext = Depends(require_permission("support:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    try:
        return await service.validate_warranty_claim(
            tenant_id=ctx.tenant_id,
            claim_id=claim_id,
            status=claim_status,
            inspection_notes=inspection_notes,
            resolved_by_user_id=ctx.user_id
        )
    except WarrantyClaimNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# -----------------------------------------------------------------------------
# 3. RETURN AUTHORIZATIONS (RMA) & INSPECTIONS
# -----------------------------------------------------------------------------
@router.post("/rmas", response_model=ReturnAuthorizationResponse, status_code=status.HTTP_201_CREATED)
async def request_rma(
    req: ReturnAuthorizationCreateRequest,
    ctx: SecurityContext = Depends(require_permission("support:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    items_data = [item.model_dump() for item in req.items]
    try:
        return await service.request_rma(
            tenant_id=ctx.tenant_id,
            order_id=req.order_id,
            reason=req.reason,
            items_data=items_data,
            destination_warehouse_id=req.destination_warehouse_id,
            requested_action=req.requested_action,
            ticket_id=req.ticket_id
        )
    except SupportError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/rmas", response_model=List[ReturnAuthorizationResponse])
async def list_rmas(
    status_filter: Optional[str] = Query(None, alias="status"),
    order_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: SecurityContext = Depends(require_permission("support:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    return await service.list_rmas(
        ctx.tenant_id, status=status_filter, order_id=order_id, limit=limit, offset=offset
    )


@router.get("/rmas/{rma_id}", response_model=ReturnAuthorizationResponse)
async def get_rma(
    rma_id: str,
    ctx: SecurityContext = Depends(require_permission("support:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    try:
        return await service.get_rma(ctx.tenant_id, rma_id)
    except RMANotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/rmas/{rma_id}/authorize", response_model=ReturnAuthorizationResponse)
async def authorize_rma(
    rma_id: str,
    destination_warehouse_id: Optional[str] = None,
    ctx: SecurityContext = Depends(require_permission("support:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SupportService(db)
    try:
        return await service.authorize_rma(
            ctx.tenant_id, rma_id,
            authorized_by_user_id=ctx.user_id,
            destination_warehouse_id=destination_warehouse_id
        )
    except RMANotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidReturnStateError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/rmas/{rma_id}/inspect", response_model=ReturnAuthorizationResponse)
async def inspect_and_settle_rma(
    rma_id: str,
    req: ReturnInspectionRequest,
    ctx: SecurityContext = Depends(require_permission("support:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Executes formal return inspection, updates inventory if restocked,
    and authorizes financial refund handoffs.
    """
    service = SupportService(db)
    try:
        # First update received items quantities from quantity_received_map
        received_items = [
            {"return_item_id": item_id, "quantity_received": qty}
            for item_id, qty in req.quantity_received_map.items()
        ]
        await service.receive_return_items(ctx.tenant_id, rma_id, received_items)

        # Inspect and settle
        return await service.inspect_and_settle_rma(
            tenant_id=ctx.tenant_id,
            rma_id=rma_id,
            inspection_outcome=req.inspection_outcome,
            inspection_notes=req.inspection_notes,
            inspected_by_user_id=ctx.user_id,
            refund_amount_cents=req.refund_amount_cents or 0
        )
    except RMANotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (InvalidReturnStateError, SupportError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
