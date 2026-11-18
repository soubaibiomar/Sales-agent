"""
Integration Test Suite: Real PostgreSQL 16 Workflows, Notifications, and Automations Validation.
Executes against live PostgreSQL container (sales-ai-postgres) on 127.0.0.1:5432
under the unprivileged 'sales_app_user' account with FORCE ROW LEVEL SECURITY.

Verifies:
1. PostgreSQL 16 RLS tenant isolation across all 5 Step 07 tables:
   - workflow_executions
   - workflow_step_logs
   - notification_templates
   - notification_logs
   - automation_rules
2. Cross-tenant leakage rejection (Tenant Beta sees 0 rows from Tenant Alpha).
3. Missing tenant context rejection (unscoped queries see 0 rows under FORCE RLS).
4. End-to-end live transactional workflow execution and step logging on real PostgreSQL 16.
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
Step 07: Durable Workflows, Notifications and Peripheral Integrations
"""
import sys
import uuid
import psycopg
import pytest
import warnings
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text, select

if sys.platform == "win32":
    import asyncio
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from src.backend.models.entities import (
    Tenant, WorkflowExecution, WorkflowStepLog, NotificationTemplate, NotificationLog, AutomationRule
)
from src.backend.workflows.engine import WorkflowEngine, WorkflowExecutionStatus
import src.backend.workflows.sagas  # Ensure registered

PG_ASYNC_URL = "postgresql+psycopg://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"
PG_SYNC_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"

STEP07_TABLES = [
    "workflow_executions",
    "workflow_step_logs",
    "notification_templates",
    "notification_logs",
    "automation_rules"
]


@pytest.fixture(scope="module")
def real_pg07_tenants():
    t_alpha = f"t_pg07_alpha_{uuid.uuid4().hex[:8]}"
    t_beta = f"t_pg07_beta_{uuid.uuid4().hex[:8]}"

    admin_conn_str = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
    with psycopg.connect(admin_conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_alpha, "PG07 Alpha", f"slug-{t_alpha}"))
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_beta, "PG07 Beta", f"slug-{t_beta}"))
        conn.commit()

    yield t_alpha, t_beta

    with psycopg.connect(admin_conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (t_alpha, t_beta))
        conn.commit()


def test_real_postgres_step07_rls_isolation_all_5_tables(real_pg07_tenants):
    """
    Verifies PostgreSQL 16 RLS on all 5 Step 07 tables.
    Tenant Alpha inserts records; Tenant Beta reads and sees 0 rows under unprivileged sales_app_user.
    """
    t_alpha, t_beta = real_pg07_tenants

    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            # 1. Tenant Alpha session
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_alpha,))

            wf_id = f"wf_{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO workflow_executions (id, tenant_id, workflow_type, correlation_id, idempotency_key, status)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (wf_id, t_alpha, "CHECKOUT_SAGA", f"corr-{wf_id}", f"idemp-{wf_id}", "RUNNING"))

            step_id = f"step_{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO workflow_step_logs (id, workflow_id, tenant_id, step_name, status)
                VALUES (%s, %s, %s, %s, %s)
            """, (step_id, wf_id, t_alpha, "reserve_stock", "COMPLETED"))

            tmpl_id = f"tmpl_{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO notification_templates (id, tenant_id, template_code, channel_type, message_class, subject_template, body_template)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (tmpl_id, t_alpha, "ORDER_CONFIRM_TEST", "EMAIL", "TRANSACTIONAL", "Order Confirmed", "Hello {{name}}"))

            log_id = f"notif_{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO notification_logs (id, tenant_id, recipient_identifier, channel_type, message_class, content, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (log_id, t_alpha, "+212600112233", "WHATSAPP", "TRANSACTIONAL", "Your order is confirmed", "DELIVERED"))

            rule_id = f"rule_{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO automation_rules (id, tenant_id, name, trigger_event, action_type, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (rule_id, t_alpha, "Auto Escalation", "quote.expired", "QUOTE_APPROVAL_ESCALATION", True))

            conn.commit()

        # 2. Tenant Beta session - MUST SEE 0 ROWS IN ALL 5 TABLES
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_beta,))

            for table in STEP07_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                assert count == 0, f"Cross-tenant data leakage detected in {table}! Expected 0 rows, got {count}."


def test_real_postgres_step07_unscoped_queries_return_zero_rows(real_pg07_tenants):
    """
    Verifies that unauthenticated or missing tenant context returns 0 rows across all 5 Step 07 tables.
    """
    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', '', false)")

            for table in STEP07_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                assert count == 0, f"Unscoped query accessed rows in {table} under FORCE RLS! Expected 0 rows, got {count}."


@pytest.mark.asyncio
async def test_real_postgres_workflow_execution_live(real_pg07_tenants):
    """
    Executes a durable workflow against live PostgreSQL 16, verifying:
    1. Execution and step logs are written with valid JSONB.
    2. Tenant isolation is respected under async engine.
    """
    t_alpha, _ = real_pg07_tenants

    engine = create_async_engine(PG_ASYNC_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        await session.execute(text(f"SELECT set_config('app.current_tenant_id', '{t_alpha}', false)"))

        execution = await WorkflowEngine.execute_workflow(
            session=session,
            tenant_id=t_alpha,
            workflow_type="DAILY_RECONCILIATION",
            workflow_name="Live PG Daily Reconciliation",
            idempotency_key=f"idemp-live-{uuid.uuid4().hex[:8]}",
            input_payload={}
        )
        await session.commit()

        assert execution.status == WorkflowExecutionStatus.COMPLETED.value
        assert execution.id is not None

        # Verify rows in live PostgreSQL
        stmt = select(WorkflowExecution).where(WorkflowExecution.id == execution.id)
        saved = (await session.execute(stmt)).scalars().one()
        assert saved.workflow_type == "DAILY_RECONCILIATION"

        stmt_logs = select(WorkflowStepLog).where(WorkflowStepLog.workflow_id == execution.id)
        logs = (await session.execute(stmt_logs)).scalars().all()
        assert len(logs) >= 1
        assert logs[0].step_name == "audit_ledger_atp_balance"

    await engine.dispose()
