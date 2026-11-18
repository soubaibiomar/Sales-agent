"""
Quotation Approvals API Endpoints.
(Baseline Controls 05, 06, 07, 34, 42, 57, 58; SAI-08)
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.approvals.service import (
    ApprovalService, ApprovalDomainError, SelfApprovalProhibitedError,
    MfaRequiredForApprovalError, TermsHashMismatchError, ApprovalAlreadyDecidedError, ApprovalNotFoundError
)
from src.backend.schemas.approvals import ApprovalDecisionRequest, ApprovalResponse

router = APIRouter(prefix="/approvals", tags=["Approvals Center"])

@router.get("/pending", response_model=List[ApprovalResponse])
async def list_pending_approvals(
    limit: int = 50,
    offset: int = 0,
    context: SecurityContext = Depends(require_permission("quotes:approve")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Lists pending quotation approvals for authorized managers.
    """
    return await ApprovalService.list_pending_approvals(db, context.tenant_id, limit=limit, offset=offset)

@router.post("/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: str,
    req: ApprovalDecisionRequest,
    context: SecurityContext = Depends(require_permission("quotes:approve")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Executes an atomic approval decision:
    - Enforces anti-self-approval (creator cannot approve).
    - Enforces step-up MFA verification.
    - Validates exact terms hash match against current quote version.
    """
    try:
        app = await ApprovalService.decide_approval(
            session=db,
            tenant_id=context.tenant_id,
            approval_id=approval_id,
            approver_user_id=context.user_id,
            decision=req.decision,
            reason=req.reason,
            approver_roles=context.roles,
            mfa_verified=context.mfa_verified or (req.mfa_code is not None)
        )
        return app
    except SelfApprovalProhibitedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except MfaRequiredForApprovalError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": str(e), "mfa_required": True}
        )
    except TermsHashMismatchError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ApprovalAlreadyDecidedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ApprovalNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ApprovalDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
