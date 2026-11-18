"""
Tests for Workflow Persistence, Idempotency, and Crash Recovery.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
import pytest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from src.backend.models.entities import Base, Tenant, WorkflowExecution, WorkflowStepLog
from src.backend.workflows.engine import (
    WorkflowEngine,
    WorkflowStep,
    SagaDefinition,
    WorkflowExecutionStatus,
    WorkflowStepStatus
)


@asynccontextmanager
async def get_workflow_test_session():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_wf_persist_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        tenant = Tenant(id="tenant_wf_test", name="Workflow Test Tenant", slug=f"wf-test-{unique_id}")
        session.add(tenant)
        await session.commit()

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_workflow_execution_idempotency():
    """
    Verifies that calling execute with the same idempotency key returns the existing execution
    without executing duplicate steps.
    """
    async with get_workflow_test_session() as session:
        tenant_id = "tenant_wf_test"
        idempotency_key = f"idemp-{uuid.uuid4().hex}"

        step_execution_counter = 0

        async def sample_action(context, db):
            nonlocal step_execution_counter
            step_execution_counter += 1
            return {"result": "success", "count": step_execution_counter}

        saga = SagaDefinition(
            name="TEST_IDEMPOTENCY_SAGA",
            steps=[
                WorkflowStep(
                    name="step_one",
                    action=sample_action,
                    compensate=None
                )
            ]
        )
        WorkflowEngine.register_saga(saga)

        # First invocation
        exec1 = await WorkflowEngine.execute_workflow(
            session=session,
            tenant_id=tenant_id,
            workflow_type="TEST_IDEMPOTENCY_SAGA",
            workflow_name="Test Idempotency Workflow",
            idempotency_key=idempotency_key,
            input_payload={"param": 100}
        )
        assert exec1.status == WorkflowExecutionStatus.COMPLETED.value
        assert step_execution_counter == 1

        # Second invocation with same idempotency key
        exec2 = await WorkflowEngine.execute_workflow(
            session=session,
            tenant_id=tenant_id,
            workflow_type="TEST_IDEMPOTENCY_SAGA",
            workflow_name="Test Idempotency Workflow",
            idempotency_key=idempotency_key,
            input_payload={"param": 200}
        )
        assert exec2.id == exec1.id
        # Step action should NOT have executed a second time!
        assert step_execution_counter == 1


@pytest.mark.asyncio
async def test_crash_recovery_resumes_interrupted_workflows():
    """
    Simulates a worker crash where an execution is left in RUNNING status.
    Calling resume_interrupted_workflows recovers and settles the pending steps.
    """
    async with get_workflow_test_session() as session:
        tenant_id = "tenant_wf_test"

        async def step1_action(ctx, db):
            return {"step1": "done"}

        async def step2_action(ctx, db):
            return {"step2": "done"}

        saga = SagaDefinition(
            name="CRASH_RECOVERY_SAGA",
            steps=[
                WorkflowStep(name="step_alpha", action=step1_action),
                WorkflowStep(name="step_beta", action=step2_action)
            ]
        )
        WorkflowEngine.register_saga(saga)

        # Manually create an execution in RUNNING state simulating a crash after step 1
        crashed_exec_id = f"wf-crashed-{uuid.uuid4().hex[:8]}"
        crashed_exec = WorkflowExecution(
            id=crashed_exec_id,
            tenant_id=tenant_id,
            workflow_type="CRASH_RECOVERY_SAGA",
            correlation_id=f"corr-{crashed_exec_id}",
            idempotency_key=f"idemp-crash-{uuid.uuid4().hex[:8]}",
            status=WorkflowExecutionStatus.RUNNING.value,
            current_step="step_alpha",
            payload_json={"sample": "data"},
            result_json={"step_alpha": {"step1": "done"}},
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10)
        )
        step1_log = WorkflowStepLog(
            id=f"step-log-{uuid.uuid4().hex[:8]}",
            workflow_id=crashed_exec_id,
            tenant_id=tenant_id,
            step_name="step_alpha",
            step_type="ACTION",
            status=WorkflowStepStatus.COMPLETED.value,
            output_json={"step1": "done"}
        )
        session.add_all([crashed_exec, step1_log])
        await session.commit()

        # Trigger crash recovery
        resumed_count = await WorkflowEngine.resume_interrupted_workflows(session=session, tenant_id=tenant_id)
        assert resumed_count >= 1

        # Check updated status
        stmt = select(WorkflowExecution).where(WorkflowExecution.id == crashed_exec_id)
        result = await session.execute(stmt)
        recovered_exec = result.scalar_one()

        assert recovered_exec.status == WorkflowExecutionStatus.COMPENSATED.value


@pytest.mark.asyncio
async def test_workflow_step_logging_durations():
    """
    Verifies that each executed step persists a detailed log with execution duration.
    """
    async with get_workflow_test_session() as session:
        tenant_id = "tenant_wf_test"

        async def fast_action(ctx, db):
            return {"metric": 42}

        saga = SagaDefinition(
            name="METRICS_SAGA",
            steps=[
                WorkflowStep(name="metric_step", action=fast_action)
            ]
        )
        WorkflowEngine.register_saga(saga)

        exec_result = await WorkflowEngine.execute_workflow(
            session=session,
            tenant_id=tenant_id,
            workflow_type="METRICS_SAGA",
            idempotency_key=f"idemp-metrics-{uuid.uuid4().hex[:8]}",
            input_payload={}
        )

        stmt = select(WorkflowStepLog).where(WorkflowStepLog.workflow_id == exec_result.id)
        step_logs = (await session.execute(stmt)).scalars().all()

        assert len(step_logs) == 1
        assert step_logs[0].step_name == "metric_step"
        assert step_logs[0].status == WorkflowStepStatus.COMPLETED.value
        assert step_logs[0].duration_ms >= 0
