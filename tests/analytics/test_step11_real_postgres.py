"""
Real PostgreSQL 16 Integration Tests for Step 11 Tables.
Validates Row-Level Security (RLS) isolation and fail-closed behavior across:
- tenant_subscriptions
- tenant_usage_meters
- tenant_quota_limits
- analytics_daily_sales
- analytics_pipeline_snapshots
- analytics_ai_performance
- system_alert_events
- system_metric_snapshots
Under least-privilege sales_app_user role.
(Controls 06, 07, 33, 48, 49; Invariants 3, 4)
"""
import uuid
import psycopg
import pytest
from datetime import datetime, timezone, timedelta, date

PG_ADMIN_CONN = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
PG_APP_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"


@pytest.fixture(scope="module")
def step11_pg_tenants():
    t_alpha = f"t_step11_a_{uuid.uuid4().hex[:8]}"
    t_beta = f"t_step11_b_{uuid.uuid4().hex[:8]}"

    with psycopg.connect(PG_ADMIN_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_alpha, "Analytics Alpha", f"slug-{t_alpha}"))
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_beta, "Analytics Beta", f"slug-{t_beta}"))
        conn.commit()

    yield t_alpha, t_beta

    with psycopg.connect(PG_ADMIN_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (t_alpha, t_beta))
        conn.commit()


def test_real_postgres_step11_tables_rls_isolation(step11_pg_tenants):
    """
    Verifies that all 8 Step 11 tables enforce strict RLS isolation between tenants
    and fail closed when the tenant session variable is not set.
    """
    t_alpha, t_beta = step11_pg_tenants
    now = datetime.now(timezone.utc)
    today = date.today()

    with psycopg.connect(PG_APP_CONN) as conn:
        with conn.cursor() as cur:
            # 1. Insert records as Tenant Alpha
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_alpha,))

            # Table 1: tenant_subscriptions
            cur.execute("""
                INSERT INTO tenant_subscriptions (id, tenant_id, plan_id, status, current_period_start, current_period_end)
                VALUES (%s, %s, 'professional', 'ACTIVE', %s, %s);
            """, (f"sub_{t_alpha}", t_alpha, now, now + timedelta(days=30)))

            # Table 2: tenant_usage_meters
            cur.execute("""
                INSERT INTO tenant_usage_meters (id, tenant_id, period_month, total_tokens, voice_seconds, api_requests_count)
                VALUES (%s, %s, '2026-11', 450000, 1200, 850);
            """, (f"meter_{t_alpha}", t_alpha))

            # Table 3: tenant_quota_limits
            cur.execute("""
                INSERT INTO tenant_quota_limits (id, tenant_id, metric_name, limit_value)
                VALUES (%s, %s, 'total_tokens', 10000000);
            """, (f"quota_{t_alpha}", t_alpha))

            # Table 4: analytics_daily_sales
            cur.execute("""
                INSERT INTO analytics_daily_sales (id, tenant_id, date, total_revenue_cents, order_count, currency)
                VALUES (%s, %s, %s, 1500000, 5, 'MAD');
            """, (f"daily_{t_alpha}", t_alpha, today))

            # Table 5: analytics_pipeline_snapshots
            cur.execute("""
                INSERT INTO analytics_pipeline_snapshots (id, tenant_id, snapshot_date, stage, deal_count, total_value_cents, currency)
                VALUES (%s, %s, %s, 'DISCOVERY', 3, 4500000, 'MAD');
            """, (f"snap_{t_alpha}", t_alpha, today))

            # Table 6: analytics_ai_performance
            cur.execute("""
                INSERT INTO analytics_ai_performance (id, tenant_id, date, agent_role, total_executions, avg_latency_ms)
                VALUES (%s, %s, %s, 'S01_DISCOVERY', 14, 380);
            """, (f"ai_perf_{t_alpha}", t_alpha, today))

            # Table 7: system_alert_events
            cur.execute("""
                INSERT INTO system_alert_events (id, tenant_id, alert_id, severity, source, title, description, status)
                VALUES (%s, %s, 'ALT-001', 'WARNING', 'API', 'Latency Spike', 'High latency detected', 'ACTIVE');
            """, (f"alt_{t_alpha}", t_alpha))

            # Table 8: system_metric_snapshots
            cur.execute("""
                INSERT INTO system_metric_snapshots (id, tenant_id, metric_family, metric_name, value)
                VALUES (%s, %s, 'voice', 'ttft_ms', 420.5);
            """, (f"metric_{t_alpha}", t_alpha))

            conn.commit()

            # 2. Query as Tenant Alpha -> All 8 tables must return 1 row
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_alpha,))
            tables = [
                "tenant_subscriptions", "tenant_usage_meters", "tenant_quota_limits",
                "analytics_daily_sales", "analytics_pipeline_snapshots", "analytics_ai_performance",
                "system_alert_events", "system_metric_snapshots"
            ]
            for tbl in tables:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                count = cur.fetchone()[0]
                assert count == 1, f"Tenant Alpha must see exactly 1 row in {tbl}, got {count}"

            # 3. Query as Tenant Beta -> All 8 tables must return 0 rows (Cross-Tenant Isolation)
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_beta,))
            for tbl in tables:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                count = cur.fetchone()[0]
                assert count == 0, f"Tenant Beta must see 0 rows in {tbl}, got {count} (Cross-Tenant Leak!)"

            # 4. Fail-closed check: Empty tenant context -> 0 rows returned
            cur.execute("SELECT set_config('app.current_tenant_id', '', false);")
            for tbl in tables:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                count = cur.fetchone()[0]
                assert count == 0, f"Unauthenticated/empty context must return 0 rows in {tbl}, got {count}"
