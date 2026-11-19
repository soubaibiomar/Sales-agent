"""
Integration Test Suite: Real PostgreSQL 16 Agent Ecosystem & Copilot RLS Validation.
Executes against live PostgreSQL container (sales-ai-postgres) on 127.0.0.1:5432
under the unprivileged 'sales_app_user' account with FORCE ROW LEVEL SECURITY.

Verifies:
1. PostgreSQL 16 RLS tenant isolation across all 4 Step 09 tables:
   - agent_definitions
   - agent_execution_logs
   - copilot_briefs
   - agent_evaluations
2. Cross-tenant leakage rejection (Tenant Beta sees 0 rows from Tenant Alpha).
3. Missing tenant context rejection (unscoped queries see 0 rows under FORCE RLS).
(Controls 40, 63, 67; Invariants 1, 3, 4)
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
import sys
import uuid
import psycopg
import pytest
import warnings
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text, select

if sys.platform == "win32":
    import asyncio
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from src.backend.models.entities import AgentDefinition, AgentExecutionLog, CopilotBrief, AgentEvaluation

PG_ASYNC_URL = "postgresql+psycopg://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"
PG_SYNC_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"

STEP09_TABLES = [
    "agent_definitions",
    "agent_execution_logs",
    "copilot_briefs",
    "agent_evaluations"
]


@pytest.fixture(scope="module")
def real_pg09_tenants():
    t_alpha = f"t_pg09_alpha_{uuid.uuid4().hex[:8]}"
    t_beta = f"t_pg09_beta_{uuid.uuid4().hex[:8]}"
    u_alpha = f"u_pg09_alpha_{uuid.uuid4().hex[:8]}"
    ct_alpha = f"ct_pg09_alpha_{uuid.uuid4().hex[:8]}"
    c_alpha = f"c_pg09_alpha_{uuid.uuid4().hex[:8]}"

    admin_conn_str = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
    with psycopg.connect(admin_conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Create tenants
            cur.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
                (t_alpha, f"Step09 Alpha {t_alpha}", f"alpha-{t_alpha}")
            )
            cur.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
                (t_beta, f"Step09 Beta {t_beta}", f"beta-{t_beta}")
            )
            # Create representative user for foreign keys
            cur.execute(
                "INSERT INTO users (id, tenant_id, email, hashed_password, full_name) VALUES (%s, %s, %s, %s, %s)",
                (u_alpha, t_alpha, f"{u_alpha}@test.ma", "hash123", "Rep Alpha")
            )
            # Create contact
            cur.execute(
                "INSERT INTO contacts (id, tenant_id, first_name, last_name, display_name) VALUES (%s, %s, %s, %s, %s)",
                (ct_alpha, t_alpha, "Karim", "Tazi", "Karim Tazi")
            )
            # Create conversation for foreign keys
            cur.execute(
                "INSERT INTO conversations (id, tenant_id, contact_id, channel_type, channel_identifier, status) VALUES (%s, %s, %s, %s, %s, %s)",
                (c_alpha, t_alpha, ct_alpha, "WEBCHAT", "user-web-01", "BOT_ACTIVE")
            )

    yield {"alpha": t_alpha, "beta": t_beta, "user_alpha": u_alpha, "conv_alpha": c_alpha}

    with psycopg.connect(admin_conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (t_alpha, t_beta))


def test_step09_tables_have_force_rls_enabled():
    """Validates that all 4 Step 09 tables have ROW LEVEL SECURITY enabled and forced."""
    admin_conn_str = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
    with psycopg.connect(admin_conn_str) as conn:
        with conn.cursor() as cur:
            for tbl in STEP09_TABLES:
                cur.execute(
                    """
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = %s;
                    """,
                    (tbl,)
                )
                row = cur.fetchone()
                assert row is not None, f"Table {tbl} not found in pg_class"
                has_rls, has_force = row
                assert has_rls is True, f"Table {tbl} does NOT have RLS enabled"
                assert has_force is True, f"Table {tbl} does NOT have FORCE RLS enabled"


@pytest.mark.asyncio
async def test_step09_rls_tenant_isolation(real_pg09_tenants):
    """
    Verifies that Tenant Beta cannot see any records inserted by Tenant Alpha
    across all 4 Step 09 tables.
    """
    t_alpha = real_pg09_tenants["alpha"]
    t_beta = real_pg09_tenants["beta"]
    u_alpha = real_pg09_tenants["user_alpha"]
    c_alpha = real_pg09_tenants["conv_alpha"]

    engine = create_async_engine(PG_ASYNC_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        # 1. Insert records under Tenant Alpha
        async with session_factory() as session:
            await session.execute(text(f"SET LOCAL app.current_tenant_id = '{t_alpha}'"))

            # Table 1: agent_definitions
            agent_def = AgentDefinition(
                id=f"agdef-{uuid.uuid4().hex[:8]}",
                tenant_id=t_alpha,
                role_id="custom_specialist",
                role_code="A99",
                role_group="INTERACTIVE_SPECIALIST",
                display_name="Custom Specialist Alpha",
                description="Custom test agent for RLS verification",
                model_tier="PRIMARY_4B",
                context_token_cap=2048,
                allowed_tools=["catalog.search"],
                is_enabled=True
            )
            session.add(agent_def)

            # Table 2: agent_execution_logs
            exec_log = AgentExecutionLog(
                id=f"agl-{uuid.uuid4().hex[:8]}",
                tenant_id=t_alpha,
                conversation_id=c_alpha,
                agent_role="qualification_crm",
                execution_class="BOUNDED_REASONING_TURN",
                trace_id=f"trc-{uuid.uuid4().hex[:8]}",
                model_name="qwen3.5:4b",
                total_tokens=45,
                latency_ms=120,
                status="SUCCESS"
            )
            session.add(exec_log)

            # Table 3: copilot_briefs
            copilot_brief = CopilotBrief(
                id=f"cb-{uuid.uuid4().hex[:8]}",
                tenant_id=t_alpha,
                conversation_id=c_alpha,
                representative_id=u_alpha,
                brief_type="DEAL_BRIEF",
                customer_summary="Prospect interested in 100kW solar farm",
                suggested_replies=["Propose solar consultation"],
                proposed_actions=[{"action": "propose_quote", "amount": 45000.0}],
                evidence_sources=["catalog.search"]
            )
            session.add(copilot_brief)

            # Table 4: agent_evaluations
            evaluation = AgentEvaluation(
                id=f"eval-{uuid.uuid4().hex[:8]}",
                tenant_id=t_alpha,
                suite_name="OFFLINE_SAFETY_CORPUS",
                total_cases=39,
                passed_cases=39,
                failed_cases=0,
                accuracy_score=100.0,
                category_scores={"SAFETY": 100.0},
                details=[]
            )
            session.add(evaluation)

            await session.commit()

        # 2. Query as Tenant Alpha -> Must see 1 row per table
        async with session_factory() as session:
            await session.execute(text(f"SET LOCAL app.current_tenant_id = '{t_alpha}'"))

            res_ag = await session.execute(select(AgentDefinition))
            assert len(res_ag.scalars().all()) == 1

            res_log = await session.execute(select(AgentExecutionLog))
            assert len(res_log.scalars().all()) == 1

            res_brief = await session.execute(select(CopilotBrief))
            assert len(res_brief.scalars().all()) == 1

            res_eval = await session.execute(select(AgentEvaluation))
            assert len(res_eval.scalars().all()) == 1

        # 3. Query as Tenant Beta -> Must see 0 rows (Absolute zero leakage)
        async with session_factory() as session:
            await session.execute(text(f"SET LOCAL app.current_tenant_id = '{t_beta}'"))

            res_ag_beta = await session.execute(select(AgentDefinition))
            assert len(res_ag_beta.scalars().all()) == 0

            res_log_beta = await session.execute(select(AgentExecutionLog))
            assert len(res_log_beta.scalars().all()) == 0

            res_brief_beta = await session.execute(select(CopilotBrief))
            assert len(res_brief_beta.scalars().all()) == 0

            res_eval_beta = await session.execute(select(AgentEvaluation))
            assert len(res_eval_beta.scalars().all()) == 0

        # 4. Query without tenant context -> Must see 0 rows (Fail-closed)
        async with session_factory() as session:
            res_ag_none = await session.execute(select(AgentDefinition))
            assert len(res_ag_none.scalars().all()) == 0

            res_log_none = await session.execute(select(AgentExecutionLog))
            assert len(res_log_none.scalars().all()) == 0

    finally:
        await engine.dispose()
