"""
Agent Ecosystem & Sales Representative Copilot REST API Routes.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 63, 65, 66, 67; Invariants 1, 2, 4, 9)
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel, Field

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import require_permission, SecurityContext
from src.ai.agents.registry import AgentRegistry, AgentRoleDefinition
from src.ai.agents.base import AgentInput, AgentOutput, BaseAgent
from src.ai.agents.supervisors.conversation_supervisor import ConversationSupervisorAgent
from src.ai.agents.supervisors.operations_supervisor import OperationsSupervisorAgent
from src.ai.agents.copilot.sales_copilot import (
    SalesRepresentativeCopilot,
    CopilotBriefResponse,
    CopilotActionProposal
)
from src.ai.tool_gateway import ServerSecurityContext
from src.backend.models.entities import AgentExecutionLog, CopilotBrief

router = APIRouter(prefix="/api/v1/agents", tags=["Agent Ecosystem & Copilot"])

# Global supervisor singleton
conversation_supervisor = ConversationSupervisorAgent()
operations_supervisor = OperationsSupervisorAgent()
sales_copilot = SalesRepresentativeCopilot()


class ExecuteAgentTurnRequest(BaseModel):
    user_prompt: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None
    turn_id: Optional[str] = None
    channel: str = "WEBCHAT"
    expected_turn_version: int = 0
    evidence: Optional[Dict[str, Any]] = None


class HumanTakeoverRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    action: str = Field(default="TAKEOVER")  # TAKEOVER or RELEASE


class ApproveProposalRequest(BaseModel):
    brief_id: str = Field(..., min_length=1)
    proposal_id: str = Field(..., min_length=1)


class GenerateBriefRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    customer_id: str = Field(..., min_length=1)
    transcript_snippet: str = Field(default="")


@router.get("", response_model=List[AgentRoleDefinition])
async def list_agent_catalog(
    group: Optional[str] = Query(None),
    ctx: SecurityContext = Depends(require_permission("crm:read"))
):
    """Lists all 18 catalog agent roles and capability metadata."""
    if group:
        return AgentRegistry.list_by_group(group)
    return AgentRegistry.list_roles()


@router.get("/{role_id}", response_model=AgentRoleDefinition)
async def get_agent_definition(
    role_id: str,
    ctx: SecurityContext = Depends(require_permission("crm:read"))
):
    """Retrieves capability metadata and allowed tools for a specific agent role."""
    try:
        return AgentRegistry.get_role(role_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.post("/turn", response_model=AgentOutput)
async def handle_conversation_turn(
    req: ExecuteAgentTurnRequest,
    ctx: SecurityContext = Depends(require_permission("crm:read")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Authoritative conversation turn entrypoint.
    Executes routing, turn fencing, human takeover checks, and specialist execution.
    """
    sec_ctx = ServerSecurityContext(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role="customer" if "customer" in ctx.roles else "sales_rep",
        permissions=ctx.permissions
    )

    agent_in = AgentInput(
        conversation_id=req.conversation_id,
        turn_id=req.turn_id,
        user_prompt=req.user_prompt,
        channel=req.channel,
        evidence=req.evidence
    )

    return await conversation_supervisor.handle_turn(
        input_data=agent_in,
        security_context=sec_ctx,
        expected_turn_version=req.expected_turn_version,
        db_session=db
    )


@router.post("/{role_id}/execute", response_model=AgentOutput)
async def execute_agent_directly(
    role_id: str,
    req: ExecuteAgentTurnRequest,
    ctx: SecurityContext = Depends(require_permission("ai:agents")),
    db: AsyncSession = Depends(get_db_session)
):
    """Executes a bounded turn directly on a designated specialist role."""
    try:
        AgentRegistry.get_role(role_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Role '{role_id}' not found.")

    agent = BaseAgent(role_id)
    sec_ctx = ServerSecurityContext(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=role_id,
        permissions=ctx.permissions
    )

    agent_in = AgentInput(
        conversation_id=req.conversation_id,
        turn_id=req.turn_id,
        user_prompt=req.user_prompt,
        channel=req.channel,
        evidence=req.evidence
    )

    return await agent.execute(
        input_data=agent_in,
        security_context=sec_ctx,
        db_session=db
    )


@router.post("/takeover")
async def toggle_human_takeover(
    req: HumanTakeoverRequest,
    ctx: SecurityContext = Depends(require_permission("crm:write"))
):
    """Enables or releases human takeover for a conversation."""
    if req.action == "TAKEOVER":
        conversation_supervisor.set_human_takeover(req.conversation_id, ctx.user_id)
        return {"conversation_id": req.conversation_id, "is_human_owned": True, "owner_id": ctx.user_id}
    else:
        conversation_supervisor.release_human_takeover(req.conversation_id)
        return {"conversation_id": req.conversation_id, "is_human_owned": False}


@router.post("/copilot/brief", response_model=CopilotBriefResponse)
async def generate_copilot_brief(
    req: GenerateBriefRequest,
    ctx: SecurityContext = Depends(require_permission("ai:copilot")),
    db: AsyncSession = Depends(get_db_session)
):
    """Generates a deal brief, objection points, and draft action proposals for sales rep."""
    sec_ctx = ServerSecurityContext(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role="sales_copilot",
        permissions=ctx.permissions
    )

    return await sales_copilot.generate_deal_brief(
        conversation_id=req.conversation_id,
        customer_id=req.customer_id,
        transcript_snippet=req.transcript_snippet,
        security_context=sec_ctx,
        db_session=db
    )


@router.post("/copilot/approve")
async def approve_copilot_proposal(
    req: ApproveProposalRequest,
    ctx: SecurityContext = Depends(require_permission("ai:copilot")),
    db: AsyncSession = Depends(get_db_session)
):
    """Authorizes a copilot action proposal with human representative signature."""
    sec_ctx = ServerSecurityContext(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role="sales_rep",
        permissions=ctx.permissions
    )

    return await sales_copilot.approve_action_proposal(
        brief_id=req.brief_id,
        proposal_id=req.proposal_id,
        approved_by_user_id=ctx.user_id,
        security_context=sec_ctx,
        db_session=db
    )


@router.post("/operations/triage")
async def execute_operations_triage(
    ctx: SecurityContext = Depends(require_permission("ai:agents")),
    db: AsyncSession = Depends(get_db_session)
):
    """Executes operational alert and worker queue triage via Operations Supervisor."""
    sec_ctx = ServerSecurityContext(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role="operations_supervisor",
        permissions=ctx.permissions
    )
    return await operations_supervisor.run_operational_triage(
        tenant_id=ctx.tenant_id,
        security_context=sec_ctx,
        db_session=db
    )


@router.get("/activity", response_model=List[Dict[str, Any]])
async def get_agent_activity_logs(
    limit: int = Query(20, ge=1, le=100),
    role: Optional[str] = Query(None),
    ctx: SecurityContext = Depends(require_permission("crm:read")),
    db: AsyncSession = Depends(get_db_session)
):
    """Retrieves recent agent execution logs strictly scoped to authenticated tenant."""
    stmt = (
        select(AgentExecutionLog)
        .where(AgentExecutionLog.tenant_id == ctx.tenant_id)
        .order_by(desc(AgentExecutionLog.created_at))
        .limit(limit)
    )
    if role:
        stmt = stmt.where(AgentExecutionLog.agent_role == role)

    res = await db.execute(stmt)
    logs = res.scalars().all()
    return [
        {
            "id": l.id,
            "agent_role": l.agent_role,
            "conversation_id": l.conversation_id,
            "execution_class": l.execution_class,
            "trace_id": l.trace_id,
            "input_summary": l.input_summary,
            "output_summary": l.output_summary,
            "tools_called": l.tools_called,
            "model_name": l.model_name,
            "total_tokens": l.total_tokens,
            "latency_ms": l.latency_ms,
            "status": l.status,
            "created_at": l.created_at.isoformat() if l.created_at else None
        }
        for l in logs
    ]
