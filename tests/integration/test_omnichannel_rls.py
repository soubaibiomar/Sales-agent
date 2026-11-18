"""
Integration Tests for Omnichannel Tables with Real PostgreSQL 16 Row-Level Security.
Verifies RLS on contacts, channel_identities, conversations, inbound_raw_events,
conversation_messages, and message_attachments using unprivileged role sales_app_user.
(Baseline Controls 07, 41)
"""
import pytest
import psycopg
from psycopg import errors

PG_ADMIN_CONN = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
PG_APP_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"

@pytest.fixture(scope="module")
def setup_omnichannel_tenants():
    with psycopg.connect(PG_ADMIN_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tenants (id, name, slug) VALUES
                ('t_omni_alpha', 'Omni Alpha Corp', 'omni-alpha'),
                ('t_omni_beta', 'Omni Beta Ltd', 'omni-beta')
                ON CONFLICT (id) DO NOTHING;
            """)
            conn.commit()
    yield
    with psycopg.connect(PG_ADMIN_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id IN ('t_omni_alpha', 't_omni_beta');")
            conn.commit()

def test_omnichannel_missing_tenant_context_fails_closed(setup_omnichannel_tenants):
    """Unset tenant context must fail closed (0 rows) on all 6 omnichannel tables."""
    with psycopg.connect(PG_APP_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("RESET app.current_tenant_id;")
            tables = [
                "contacts", "channel_identities", "conversations",
                "inbound_raw_events", "conversation_messages", "message_attachments",
                "outbox_events"
            ]
            for tbl in tables:
                cur.execute(f"SELECT * FROM {tbl};")
                assert len(cur.fetchall()) == 0, f"Table {tbl} leaked rows without tenant context!"

def test_omnichannel_cross_tenant_isolation(setup_omnichannel_tenants):
    """Positive and negative tenant isolation for contacts, conversations, and messages."""
    with psycopg.connect(PG_APP_CONN) as conn:
        # 1. Insert Alpha Data
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = 't_omni_alpha';")
            cur.execute("""
                INSERT INTO contacts (id, tenant_id, display_name, primary_phone)
                VALUES ('c_alpha_1', 't_omni_alpha', 'Alpha Client', '+212600112233');
            """)
            cur.execute("""
                INSERT INTO conversations (id, tenant_id, contact_id, channel_type, channel_identifier)
                VALUES ('conv_alpha_1', 't_omni_alpha', 'c_alpha_1', 'WHATSAPP', '+212600112233');
            """)
            cur.execute("""
                INSERT INTO conversation_messages (id, conversation_id, tenant_id, sender_type, content)
                VALUES ('msg_alpha_1', 'conv_alpha_1', 't_omni_alpha', 'CUSTOMER', 'Alpha secret query');
            """)
            cur.execute("""
                INSERT INTO outbox_events (id, tenant_id, conversation_id, event_type, channel_type, recipient_identifier, payload_json)
                VALUES ('out_alpha_1', 't_omni_alpha', 'conv_alpha_1', 'DISPATCH_MESSAGE', 'WHATSAPP', '+212600112233', '{"text":"hello"}');
            """)
            conn.commit()

        # 2. Insert Beta Data
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = 't_omni_beta';")
            cur.execute("""
                INSERT INTO contacts (id, tenant_id, display_name, primary_phone)
                VALUES ('c_beta_1', 't_omni_beta', 'Beta Client', '+212699887766');
            """)
            cur.execute("""
                INSERT INTO conversations (id, tenant_id, contact_id, channel_type, channel_identifier)
                VALUES ('conv_beta_1', 't_omni_beta', 'c_beta_1', 'WHATSAPP', '+212699887766');
            """)
            cur.execute("""
                INSERT INTO conversation_messages (id, conversation_id, tenant_id, sender_type, content)
                VALUES ('msg_beta_1', 'conv_beta_1', 't_omni_beta', 'CUSTOMER', 'Beta confidential query');
            """)
            cur.execute("""
                INSERT INTO outbox_events (id, tenant_id, conversation_id, event_type, channel_type, recipient_identifier, payload_json)
                VALUES ('out_beta_1', 't_omni_beta', 'conv_beta_1', 'DISPATCH_MESSAGE', 'WHATSAPP', '+212699887766', '{"text":"secret"}');
            """)
            conn.commit()

        # 3. Read as Alpha -> Should see only Alpha
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = 't_omni_alpha';")
            cur.execute("SELECT id, display_name FROM contacts;")
            contacts = cur.fetchall()
            assert len(contacts) == 1 and contacts[0][0] == 'c_alpha_1'

            cur.execute("SELECT id FROM conversations;")
            convs = cur.fetchall()
            assert len(convs) == 1 and convs[0][0] == 'conv_alpha_1'

            cur.execute("SELECT id, content FROM conversation_messages;")
            msgs = cur.fetchall()
            assert len(msgs) == 1 and msgs[0][0] == 'msg_alpha_1'

            cur.execute("SELECT id, recipient_identifier FROM outbox_events;")
            outs = cur.fetchall()
            assert len(outs) == 1 and outs[0][0] == 'out_alpha_1'

        # 4. Attempt Cross-Tenant INSERT as Alpha into Beta -> InsufficientPrivilege
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = 't_omni_alpha';")
            with pytest.raises(errors.InsufficientPrivilege):
                cur.execute("""
                    INSERT INTO contacts (id, tenant_id, display_name)
                    VALUES ('c_attack_1', 't_omni_beta', 'Malicious Contact');
                """)
            conn.rollback()

            cur.execute("SET LOCAL app.current_tenant_id = 't_omni_alpha';")
            with pytest.raises(errors.InsufficientPrivilege):
                cur.execute("""
                    INSERT INTO outbox_events (id, tenant_id, event_type, channel_type, recipient_identifier, payload_json)
                    VALUES ('out_attack_1', 't_omni_beta', 'DISPATCH_MESSAGE', 'WHATSAPP', '+212699887766', '{}');
                """)
            conn.rollback()

        # 5. Attempt Cross-Tenant UPDATE and DELETE as Alpha on Beta -> 0 rows affected
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = 't_omni_alpha';")
            cur.execute("UPDATE conversations SET status = 'CLOSED' WHERE id = 'conv_beta_1';")
            assert cur.rowcount == 0

            cur.execute("DELETE FROM conversation_messages WHERE id = 'msg_beta_1';")
            assert cur.rowcount == 0

            cur.execute("UPDATE outbox_events SET status = 'DELIVERED' WHERE id = 'out_beta_1';")
            assert cur.rowcount == 0

            cur.execute("DELETE FROM outbox_events WHERE id = 'out_beta_1';")
            assert cur.rowcount == 0
            conn.commit()
