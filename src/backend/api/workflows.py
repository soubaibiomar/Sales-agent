"""
Durable Workflows & Sagas API Routes.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import (
    get_security_context,
    get_optional_security_context,
    require_permission,
    SecurityContext
)
from src.backend.models.entities import WorkflowExecution, WorkflowStepLog, AutomationRule
from src.backend.schemas.workflows import (
    WorkflowExecutionCreateRequest,
    WorkflowExecutionResponse,
    WorkflowRetryRequest,
    AutomationRuleCreateRequest,
    AutomationRuleResponse
)
from src.backend.workflows.engine import WorkflowEngine
import src.backend.workflows.sagas  # Ensure sagas are registered

router = APIRouter(prefix="/api/v1/workflows", tags=["Durable Workflows"])


@router.post("/executions", response_model=WorkflowExecutionResponse, status_code=status.HTTP_201_CREATED)
async def trigger_workflow_execution(
    req: WorkflowExecutionCreateRequest,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Triggers an asynchronous durable workflow saga with guaranteed idempotency.
    """
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    engine = WorkflowEngine(db)
    try:
        execution = await engine.execute_workflow(
            tenant_id=tenant_id,
            workflow_type=req.workflow_type,
            idempotency_key=req.idempotency_key,
            payload=req.payload,
            correlation_id=req.correlation_id or (ctx.correlation_id if ctx else None)
        )
        await db.commit()

        # Re-fetch with step logs
        stmt = select(WorkflowExecution).options(
            selectinload(WorkflowExecution.step_logs)
        ).where(WorkflowExecution.id == execution.id)
        res = await db.execute(stmt)
        full_exec = res.scalar_one()

        return full_exec
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/executions", response_model=List[WorkflowExecutionResponse])
async def list_workflow_executions(
    status_filter: Optional[str] = None,
    workflow_type: Optional[str] = None,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    stmt = select(WorkflowExecution).options(
        selectinload(WorkflowExecution.step_logs)
    ).where(WorkflowExecution.tenant_id == tenant_id)

    if status_filter:
        stmt = stmt.where(WorkflowExecution.status == status_filter.upper())
    if workflow_type:
        stmt = stmt.where(WorkflowExecution.workflow_type == workflow_type.upper())

    stmt = stmt.order_by(WorkflowExecution.created_at.desc()).limit(100)
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.get("/executions/{execution_id}", response_model=WorkflowExecutionResponse)
async def get_workflow_execution(
    execution_id: str,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    stmt = select(WorkflowExecution).options(
        selectinload(WorkflowExecution.step_logs)
    ).where(
        WorkflowExecution.tenant_id == tenant_id,
        WorkflowExecution.id == execution_id
    )
    res = await db.execute(stmt)
    execution = res.scalars().first()
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow execution '{execution_id}' not found.")

    return execution


@router.post("/recovery/resume", response_model=Dict[str, Any])
async def resume_interrupted_workflows(
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Operator endpoint: Resumes or compensates workflows interrupted by a sudden process restart.
    """
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    engine = WorkflowEngine(db)
    recovered = await engine.resume_interrupted_workflows(tenant_id)
    await db.commit()

    return {
        "status": "RECOVERY_COMPLETED",
        "recovered_count": len(recovered),
        "resumed_count": len(recovered),
        "recovered_ids": [r.id for r in recovered]
    }


@router.get("/automations/rules", response_model=List[AutomationRuleResponse])
async def list_automation_rules(
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    stmt = select(AutomationRule).where(AutomationRule.tenant_id == tenant_id).order_by(AutomationRule.created_at.desc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post("/automations/rules", response_model=AutomationRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_automation_rule(
    req: AutomationRuleCreateRequest,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    import uuid
    rule = AutomationRule(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=req.name,
        trigger_event=req.trigger_event,
        condition_json=req.condition or {},
        action_type=req.action_type,
        action_config_json=req.action_config or {},
        is_active=req.is_active
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule
