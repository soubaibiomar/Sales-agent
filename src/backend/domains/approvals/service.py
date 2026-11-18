"""
Quotation Approval Domain Service.
Manages canonical manager approval queues, anti-self-approval enforcement, MFA verification,
and exact-terms cryptographic hash matching.
(Baseline Controls 05, 06, 07, 34, 42, 57, 58; SAI-08)
"""
import uuid
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import engine
from src.backend.models.entities import Quote, QuoteApproval, AuditEvent, User
from src.backend.core.policy_service import policy_service

class ApprovalDomainError(Exception):
    pass

class SelfApprovalProhibitedError(ApprovalDomainError):
    pass

class MfaRequiredForApprovalError(ApprovalDomainError):
    pass

class TermsHashMismatchError(ApprovalDomainError):
    pass

class ApprovalAlreadyDecidedError(ApprovalDomainError):
    pass

class ApprovalNotFoundError(ApprovalDomainError):
    pass

class ApprovalService:
    """Enterprise domain service for commercial approval workflows."""

    @staticmethod
    async def get_approval(
        session: AsyncSession,
        tenant_id: str,
        approval_id: str
    ) -> Optional[QuoteApproval]:
        stmt = select(QuoteApproval).where(
            QuoteApproval.id == approval_id,
            QuoteApproval.tenant_id == tenant_id
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def list_pending_approvals(
        session: AsyncSession,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[QuoteApproval]:
        stmt = (
            select(QuoteApproval)
            .where(
                QuoteApproval.tenant_id == tenant_id,
                QuoteApproval.status == "PENDING"
            )
            .order_by(QuoteApproval.requested_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def decide_approval(
        session: AsyncSession,
        tenant_id: str,
        approval_id: str,
        approver_user_id: str,
        decision: str,  # APPROVED or REJECTED
        reason: Optional[str] = None,
        approver_roles: Optional[List[str]] = None,
        mfa_verified: bool = False
    ) -> QuoteApproval:
        """
        Executes a canonical approval decision under strict security constraints:
        1. Pessimistic row locking on PostgreSQL.
        2. Rejects self-approval (requester cannot approve).
        3. Enforces MFA verification for privileged approvals.
        4. Validates exact terms hash match against current quote state.
        5. One-use decision enforcement.
        """
        bind = session.bind or engine
        stmt = select(QuoteApproval).where(
            QuoteApproval.id == approval_id,
            QuoteApproval.tenant_id == tenant_id
        )
        if bind and getattr(bind.dialect, "name", None) == "postgresql":
            stmt = stmt.with_for_update()

        res = await session.execute(stmt)
        approval = res.scalars().first()
        if not approval:
            raise ApprovalNotFoundError(f"Approval request '{approval_id}' not found")

        # 1. One-use decision check & terms invalidation check
        if approval.status == "INVALIDATED":
            raise TermsHashMismatchError(
                f"Approval request '{approval_id}' was invalidated because quote terms changed."
            )
        if approval.status != "PENDING":
            raise ApprovalAlreadyDecidedError(
                f"Approval request '{approval_id}' is already '{approval.status}' and cannot be decided again"
            )

        # 2. Anti-Self-Approval Guard (Control 57)
        if approval.requested_by_user_id == approver_user_id:
            raise SelfApprovalProhibitedError(
                "Self-approval is strictly prohibited: quote creator/requester cannot approve their own quotation"
            )

        # 3. Privileged Role and Step-up MFA Guard (Controls 05, 07; SAI-08)
        roles = approver_roles or []
        is_privileged = policy_service.has_privileged_role(roles) or "sales_manager" in roles or "tenant_admin" in roles
        if is_privileged and not mfa_verified:
            raise MfaRequiredForApprovalError(
                "Step-up MFA verification is mandatory for commercial quotation approvals"
            )

        # 4. Fetch live Quote with row locking
        q_stmt = select(Quote).where(
            Quote.id == approval.quote_id,
            Quote.tenant_id == tenant_id
        )
        if bind and getattr(bind.dialect, "name", None) == "postgresql":
            q_stmt = q_stmt.with_for_update()

        q_res = await session.execute(q_stmt)
        quote = q_res.scalars().first()
        if not quote:
            raise ApprovalDomainError(f"Target quote '{approval.quote_id}' not found")

        # 5. Exact Terms Hash & Version Match Guard
        if quote.version != approval.quote_version or quote.terms_hash != approval.terms_hash:
            approval.status = "INVALIDATED"
            approval.decision_reason = "Quote terms changed while approval was pending"
            approval.updated_at = datetime.now(timezone.utc)
            await session.flush()
            raise TermsHashMismatchError(
                f"Quote terms have changed since approval was requested (version {approval.quote_version} -> {quote.version}). Older approval is invalidated."
            )

        # 6. Apply Decision
        now = datetime.now(timezone.utc)
        clean_decision = decision.strip().upper()
        if clean_decision not in ["APPROVED", "REJECTED"]:
            raise ApprovalDomainError(f"Invalid approval decision '{decision}'. Must be APPROVED or REJECTED")

        approval.status = clean_decision
        approval.decided_by_user_id = approver_user_id
        approval.decided_at = now
        approval.decision_reason = reason or ("Approved by manager" if clean_decision == "APPROVED" else "Rejected by manager")
        approval.mfa_verified = mfa_verified
        approval.decision_signature = f"sig_{uuid.uuid4().hex[:12]}"
        approval.updated_at = now

        # Update Quote State Machine
        if clean_decision == "APPROVED":
            quote.status = "APPROVED"
        else:
            quote.status = "REJECTED"
        quote.updated_at = now

        # 7. Immutable Audit Event Emission
        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=approver_user_id,
            event_type="QUOTE_APPROVAL_DECIDED",
            resource_type="QUOTE_APPROVAL",
            resource_id=approval.id,
            action=clean_decision,
            status="SUCCESS",
            payload_json=json.dumps({
                "quote_id": quote.id,
                "quote_number": quote.quote_number,
                "quote_version": quote.version,
                "terms_hash": quote.terms_hash,
                "decision": clean_decision,
                "reason": approval.decision_reason,
                "mfa_verified": mfa_verified
            })
        )
        session.add(audit)
        await session.flush()
        return approval
