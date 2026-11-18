"""
Real PostgreSQL 16 Integration Tests for Voice AI Platform Tables.
Validates Row-Level Security (RLS) isolation and missing-context fail-closed behavior
on voice_sessions, voice_transcripts, and voice_recordings.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 06, 07, 31, 33, 48, 49; SAI-01, SAI-04, SAI-05)
"""
import uuid
import psycopg
import pytest
from datetime import datetime, timezone, timedelta

PG_ADMIN_CONN = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
PG_APP_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"


@pytest.fixture(scope="module")
def voice_pg_tenants():
    t_alpha = f"t_voice_alpha_{uuid.uuid4().hex[:8]}"
    t_beta = f"t_voice_beta_{uuid.uuid4().hex[:8]}"

    with psycopg.connect(PG_ADMIN_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_alpha, "Voice Alpha", f"slug-{t_alpha}"))
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_beta, "Voice Beta", f"slug-{t_beta}"))
        conn.commit()

    yield t_alpha, t_beta

    with psycopg.connect(PG_ADMIN_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (t_alpha, t_beta))
        conn.commit()


def test_real_postgres_voice_tables_rls_isolation(voice_pg_tenants):
    """
    Verifies that voice_sessions, voice_transcripts, and voice_recordings
    enforce strict Row-Level Security between two isolated tenants under sales_app_user.
    """
    t_alpha, t_beta = voice_pg_tenants

    with psycopg.connect(PG_APP_CONN) as conn:
        with conn.cursor() as cur:
            # 1. Insert data as Tenant Alpha
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_alpha,))
            sess_id_alpha = f"voice_alpha_{uuid.uuid4().hex[:8]}"

            cur.execute("""
                INSERT INTO voice_sessions (id, tenant_id, session_id, voice_mode, channel_type, language, status)
                VALUES (%s, %s, %s, 'CUSTOMER', 'WEBRTC', 'fr-FR', 'ACTIVE');
            """, (str(uuid.uuid4()), t_alpha, sess_id_alpha))

            cur.execute("""
                INSERT INTO voice_transcripts (id, tenant_id, session_id, turn_index, speaker_type, raw_text, redacted_text, language)
                VALUES (%s, %s, %s, 1, 'USER', 'Bonjour', 'Bonjour', 'fr-FR');
            """, (str(uuid.uuid4()), t_alpha, sess_id_alpha))

            cur.execute("""
                INSERT INTO voice_recordings (id, tenant_id, session_id, storage_path, duration_seconds, expires_at)
                VALUES (%s, %s, %s, 's3://voice/rec1.wav', 12, %s);
            """, (str(uuid.uuid4()), t_alpha, sess_id_alpha, datetime.now(timezone.utc) + timedelta(days=90)))
            conn.commit()

            # 2. Tenant Alpha reads its own data
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_alpha,))
            cur.execute("SELECT COUNT(*) FROM voice_sessions WHERE session_id = %s;", (sess_id_alpha,))
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT COUNT(*) FROM voice_transcripts WHERE session_id = %s;", (sess_id_alpha,))
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT COUNT(*) FROM voice_recordings WHERE session_id = %s;", (sess_id_alpha,))
            assert cur.fetchone()[0] == 1

            # 3. Tenant Beta CANNOT read Tenant Alpha's records (RLS Isolation)
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_beta,))
            cur.execute("SELECT COUNT(*) FROM voice_sessions WHERE session_id = %s;", (sess_id_alpha,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM voice_transcripts WHERE session_id = %s;", (sess_id_alpha,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM voice_recordings WHERE session_id = %s;", (sess_id_alpha,))
            assert cur.fetchone()[0] == 0

            # 4. Missing tenant context FAILS CLOSED (0 rows returned)
            cur.execute("SELECT set_config('app.current_tenant_id', '', false)")
            cur.execute("SELECT COUNT(*) FROM voice_sessions WHERE session_id = %s;", (sess_id_alpha,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM voice_transcripts WHERE session_id = %s;", (sess_id_alpha,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM voice_recordings WHERE session_id = %s;", (sess_id_alpha,))
            assert cur.fetchone()[0] == 0
