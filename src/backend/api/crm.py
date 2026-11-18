"""
CRM API Endpoints.
Provides REST APIs for Accounts, Leads, Opportunities, Activities, and Pipelines.
(Baseline Controls 16, 17, 33, 34, 42)
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.crm.service import CrmService, CrmDomainError, LeadAlreadyConvertedError
from src.backend.schemas.crm import (
    AccountCreate, AccountResponse,
    LeadCreate, LeadConvertRequest, LeadResponse,
    OpportunityCreate, OpportunityUpdateStage, OpportunityResponse,
    ActivityCreate, ActivityResponse
)

router = APIRouter(prefix="/crm", tags=["CRM & Pipeline"])

# -----------------------------------------------------------------------------
# 1. ACCOUNTS
# -----------------------------------------------------------------------------
@router.post("/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    req: AccountCreate,
    context: SecurityContext = Depends(require_permission("crm:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        acc = await CrmService.create_account(
            session=db,
            tenant_id=context.tenant_id,
            name=req.name,
            account_type=req.account_type,
            tax_identifier=req.tax_identifier,
            industry=req.industry,
            website=req.website,
            phone=req.phone,
            billing_address=req.billing_address,
            shipping_address=req.shipping_address,
            assigned_user_id=req.assigned_user_id or context.user_id
        )
        return acc
    except CrmDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/accounts", response_model=List[AccountResponse])
async def list_accounts(
    is_active: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    context: SecurityContext = Depends(require_permission("crm:read")),
    db: AsyncSession = Depends(get_db_session)
):
    return await CrmService.list_accounts(db, context.tenant_id, is_active=is_active, limit=limit, offset=offset)

@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: str,
    context: SecurityContext = Depends(require_permission("crm:read")),
    db: AsyncSession = Depends(get_db_session)
):
    acc = await CrmService.get_account(db, context.tenant_id, account_id)
    if not acc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return acc

# -----------------------------------------------------------------------------
# 2. LEADS
# -----------------------------------------------------------------------------
@router.post("/leads", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    req: LeadCreate,
    context: SecurityContext = Depends(require_permission("crm:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        lead = await CrmService.create_lead(
            session=db,
            tenant_id=context.tenant_id,
            first_name=req.first_name,
            last_name=req.last_name,
            company_name=req.company_name,
            email=req.email,
            phone=req.phone,
            source=req.source,
            score=req.score,
            assigned_user_id=req.assigned_user_id or context.user_id,
            notes=req.notes
        )
        return lead
    except CrmDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/leads", response_model=List[LeadResponse])
async def list_leads(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    context: SecurityContext = Depends(require_permission("crm:read")),
    db: AsyncSession = Depends(get_db_session)
):
    return await CrmService.list_leads(db, context.tenant_id, status=status_filter, limit=limit, offset=offset)

@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: str,
    context: SecurityContext = Depends(require_permission("crm:read")),
    db: AsyncSession = Depends(get_db_session)
):
    lead = await CrmService.get_lead(db, context.tenant_id, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return lead

@router.post("/leads/{lead_id}/convert")
async def convert_lead(
    lead_id: str,
    req: LeadConvertRequest,
    context: SecurityContext = Depends(require_permission("crm:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        acc, contact, opp = await CrmService.convert_lead_to_opportunity(
            session=db,
            tenant_id=context.tenant_id,
            lead_id=lead_id,
            opportunity_title=req.opportunity_title,
            estimated_amount_cents=req.estimated_amount_cents,
            currency=req.currency,
            actor_user_id=context.user_id
        )
        return {
            "status": "success",
            "account_id": acc.id,
            "contact_id": contact.id,
            "opportunity_id": opp.id,
            "converted_account_id": acc.id,
            "converted_contact_id": contact.id,
            "converted_opportunity_id": opp.id
        }
    except LeadAlreadyConvertedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except CrmDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

# -----------------------------------------------------------------------------
# 3. OPPORTUNITIES
# -----------------------------------------------------------------------------
@router.post("/opportunities", response_model=OpportunityResponse, status_code=status.HTTP_201_CREATED)
async def create_opportunity(
    req: OpportunityCreate,
    context: SecurityContext = Depends(require_permission("crm:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        opp = await CrmService.create_opportunity(
            session=db,
            tenant_id=context.tenant_id,
            account_id=req.account_id,
            title=req.title,
            amount_cents=req.amount_cents,
            currency=req.currency,
            contact_id=req.contact_id,
            lead_id=req.lead_id,
            stage=req.stage,
            probability_percent=req.probability_percent,
            expected_close_date=req.expected_close_date,
            assigned_user_id=req.assigned_user_id or context.user_id,
            notes=req.notes
        )
        return opp
    except CrmDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/opportunities", response_model=List[OpportunityResponse])
async def list_opportunities(
    stage: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    context: SecurityContext = Depends(require_permission("crm:read")),
    db: AsyncSession = Depends(get_db_session)
):
    return await CrmService.list_opportunities(db, context.tenant_id, stage=stage, limit=limit, offset=offset)

@router.get("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def get_opportunity(
    opportunity_id: str,
    context: SecurityContext = Depends(require_permission("crm:read")),
    db: AsyncSession = Depends(get_db_session)
):
    opp = await CrmService.get_opportunity(db, context.tenant_id, opportunity_id)
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    return opp

@router.patch("/opportunities/{opportunity_id}/stage", response_model=OpportunityResponse)
async def update_opportunity_stage(
    opportunity_id: str,
    req: OpportunityUpdateStage,
    context: SecurityContext = Depends(require_permission("crm:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        opp = await CrmService.update_opportunity_stage(
            session=db,
            tenant_id=context.tenant_id,
            opportunity_id=opportunity_id,
            new_stage=req.stage,
            lost_reason=req.lost_reason,
            actor_user_id=context.user_id
        )
        return opp
    except CrmDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

# -----------------------------------------------------------------------------
# 4. ACTIVITIES & PIPELINE BOARD
# -----------------------------------------------------------------------------
@router.post("/activities", response_model=ActivityResponse, status_code=status.HTTP_201_CREATED)
async def log_activity(
    req: ActivityCreate,
    context: SecurityContext = Depends(require_permission("crm:write")),
    db: AsyncSession = Depends(get_db_session)
):
    act = await CrmService.log_activity(
        session=db,
        tenant_id=context.tenant_id,
        activity_type=req.activity_type,
        subject=req.subject,
        description=req.description,
        due_date=req.due_date,
        completed_at=req.completed_at,
        assigned_user_id=req.assigned_user_id or context.user_id,
        lead_id=req.lead_id,
        opportunity_id=req.opportunity_id,
        account_id=req.account_id,
        contact_id=req.contact_id
    )
    return act

@router.get("/pipeline")
async def get_pipeline_board(
    context: SecurityContext = Depends(require_permission("crm:read")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Returns aggregated Pipeline stages with opportunity count and total volume in cents.
    """
    opps = await CrmService.list_opportunities(db, context.tenant_id, limit=200)
    stages = ["DISCOVERY", "QUALIFICATION", "PROPOSAL", "NEGOTIATION", "CLOSED_WON", "CLOSED_LOST"]
    board = {s: {"opportunities": [], "total_cents": 0, "count": 0} for s in stages}

    for opp in opps:
        s = opp.stage if opp.stage in board else "DISCOVERY"
        board[s]["opportunities"].append({
            "id": opp.id,
            "title": opp.title,
            "amount_cents": opp.amount_cents,
            "currency": opp.currency,
            "probability_percent": opp.probability_percent,
            "account_id": opp.account_id
        })
        board[s]["total_cents"] += opp.amount_cents
        board[s]["count"] += 1

    return {"stages": board}
