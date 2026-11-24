# Cross-tenant FK reference probe. Everything is rolled back; nothing persists.
import psycopg, uuid, json, os
pw_admin = os.environ["PGA"]; pw_app = os.environ["PGU"]
admin = psycopg.connect(f"postgresql://postgres:{pw_admin}@127.0.0.1:5432/sales_ai_db")
app = psycopg.connect(f"postgresql://sales_app_user:{pw_app}@127.0.0.1:5432/sales_ai_db")
ta, tb = "insp_A_"+uuid.uuid4().hex[:8], "insp_B_"+uuid.uuid4().hex[:8]
acc_b = str(uuid.uuid4()); out = {}
try:
    with admin.cursor() as c:
        c.execute("insert into tenants(id,name,slug) values (%s,'InspA',%s),(%s,'InspB',%s)", (ta, ta, tb, tb))
        c.execute("insert into accounts(id,tenant_id,name) values (%s,%s,'B secret account')", (acc_b, tb))
    admin.commit()
    with app.cursor() as c:
        c.execute("select set_config('app.current_tenant_id', %s, true)", (ta,))
        c.execute("select count(*) from accounts where id=%s", (acc_b,)); out["A_can_read_B_account"] = c.fetchone()[0]
        opp = str(uuid.uuid4())
        try:
            c.execute("insert into opportunities(id,tenant_id,account_id,title) values (%s,%s,%s,'xref')", (opp, ta, acc_b))
            out["A_insert_opportunity_referencing_B_account"] = "ACCEPTED (FK passed across tenants)"
        except Exception as e:
            out["A_insert_opportunity_referencing_B_account"] = "REJECTED: "+type(e).__name__
        app.rollback()
        c.execute("select count(*) from accounts"); out["no_tenant_context_rows_visible"] = c.fetchone()[0]
        try:
            c.execute("update tenants set name=name where id=%s", (tb,)); out["app_user_can_update_other_tenant_row_in_tenants"] = c.rowcount
        except Exception as e: out["app_user_can_update_other_tenant_row_in_tenants"] = "denied "+type(e).__name__
        app.rollback()
        try:
            c.execute("select set_config('app.current_tenant_id', %s, true)", (tb,))
            c.execute("update audit_logs set action=action where false"); out["app_user_has_UPDATE_on_audit_logs"] = "yes (statement permitted)"
        except Exception as e: out["app_user_has_UPDATE_on_audit_logs"] = "denied "+type(e).__name__
        app.rollback()
finally:
    with admin.cursor() as c:
        c.execute("delete from accounts where id=%s", (acc_b,)); c.execute("delete from tenants where id in (%s,%s)", (ta, tb))
    admin.commit()
print(json.dumps(out, indent=1))
