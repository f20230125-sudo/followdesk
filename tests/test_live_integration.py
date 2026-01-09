"""Real local HTTP integration with LoopDesk; failures injected after real writes."""
from pathlib import Path
import os
import sys
import uuid
from threading import Thread
from datetime import timedelta

import pytest
from werkzeug.serving import make_server

LOOP=Path(__file__).resolve().parents[2]/"loopdesk"
if not LOOP.is_dir(): pytest.skip("Live integration tests require the sibling LoopDesk source checkout.",allow_module_level=True)
sys.path.insert(0,str(LOOP))
from loopdesk import create_app as create_loop
from loopdesk.db import Database as LoopDatabase,get_db as loop_db,migrate as loop_migrate
from loopdesk import services as ls,outreach as lo
from followdesk import services as s,crm
from conftest import run
from test_domain import deliver


@pytest.fixture
def issuer(tmp_path,app,request):
    source_url=os.environ.get("FOLLOWDESK_TEST_DATABASE_URL")
    schema=None
    admin=None
    if source_url:
        if not source_url.startswith(("postgres://","postgresql://")):raise ValueError("Use a dedicated PostgreSQL test database.")
        from psycopg import sql
        schema="loop_follow_test_"+uuid.uuid4().hex
        admin=LoopDatabase(source_url)
        def cleanup_schema():
            try:
                with admin.transaction():admin.conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
            finally:admin.close()
        request.addfinalizer(cleanup_schema)
        with admin.transaction():admin.conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    loop=create_loop(dict(TESTING=True,PRODUCTION=False,SECRET_KEY="local-integration-test-secret",DATABASE_URL=source_url or "sqlite:///"+str(tmp_path/"issuer.sqlite3"),DATABASE_SCHEMA=schema))
    with loop.app_context():
        db=loop_db()
        loop_migrate(db)
        wid=ls.create_workspace(db,seed=False)
        org=ls.save_organisation(db,wid,dict(name="Synthetic Acacia",sector="Technology",city="Dubai"))
        contact=ls.save_contact(db,wid,dict(name="Alex Example",email="alex@acacia.example.com",role="Coordinator",organisation_id=org))
        oid=ls.save_opportunity(db,wid,dict(title="Fictional laptop enquiry",organisation_id=org,contact_id=contact,owner="Maya (demo)",stage="New",service="IT asset disposition",value="",next_action="Discuss next steps"))
    server=make_server("127.0.0.1",0,loop,threaded=True)
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    original=app.config["LOOPDESK_URL"]
    app.config["LOOPDESK_URL"]=f"http://127.0.0.1:{server.server_port}"
    try: yield dict(app=loop,wid=wid,oid=oid,contact=contact,org=org)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        app.config["LOOPDESK_URL"]=original


def code(issuer):
    with issuer["app"].app_context(): return lo.make_code(loop_db(),issuer["wid"])


def connect(db,workspace,issuer):
    crm.pair(db,workspace,code(issuer))
    return crm.fresh_context(db,workspace,issuer["oid"])


def source_activities(issuer):
    with issuer["app"].app_context(): return loop_db().all("SELECT * FROM activities WHERE kind='followdesk'")


def test_pair_redirect_and_connection_detects_real_revocation(app,db,workspace,issuer):
    from conftest import session_for
    client=app.test_client()
    token=session_for(client,workspace)
    pairing=code(issuer)
    response=client.post("/connection",data=dict(csrf_token=token,pairing_code=pairing))
    assert response.status_code==303 and response.headers["Location"]=="/enroll"
    assert pairing not in response.headers["Location"]
    response=client.get("/enroll")
    assert b'Connected to this LoopDesk demo' in response.data
    assert b'Connected until' in client.get("/connection").data
    assert b'1 of 6 done' in client.get("/queue").data
    assert client.post("/connection",data=dict(csrf_token=token,pairing_code=pairing)).status_code==422
    with issuer["app"].app_context():
        with loop_db().transaction(): loop_db().execute("UPDATE outreach_grants SET revoked=1 WHERE workspace_id=?",(issuer["wid"],))
    assert b'Revoked' in client.get("/connection").data
    assert b'Next: Connect LoopDesk.' in client.get("/queue").data


def test_real_http_lost_ack_retries_without_duplicate(db,workspace,plan,issuer,monkeypatch):
    context=connect(db,workspace,issuer)
    eid=run(db,workspace,plan,context)
    # Runtime enrolment uses actual source identity, not the generic fixture ID.
    with db.transaction(): db.execute("UPDATE enrollments SET source_workspace_id=? WHERE id=?",(issuer["wid"],eid))
    deliver(db,workspace,eid,context)
    original=crm.call
    lost=[True]
    def lose_once(db,wid,path,method="GET",payload=None):
        result=original(db,wid,path,method,payload)
        if path=="/events" and lost[0]:
            lost[0]=False
            raise crm.CRMError("Transport dropped after real issuer commit.")
        return result
    monkeypatch.setattr(crm,"call",lose_once)
    with pytest.raises(crm.CRMError): crm.sync(db,workspace)
    assert s.report(db,workspace)["pending"]==1 and len(source_activities(issuer))==1
    assert crm.sync(db,workspace)==1
    assert crm.sync(db,workspace)==0
    assert len(source_activities(issuer))==1 and s.report(db,workspace)["deliveries"]==1


def test_changed_live_recipient_requires_refresh_and_review(db,workspace,plan,issuer):
    context=connect(db,workspace,issuer)
    eid=s.enroll(db,workspace,plan,context,issuer["wid"])
    step=s.current_step(db,workspace,eid)
    s.approve(db,workspace,step["id"],step["version"],crm.fresh_context(db,workspace,issuer["oid"]))
    with issuer["app"].app_context():
        dbi=loop_db()
        current=ls.record(dbi,"contacts",issuer["wid"],issuer["contact"])
        ls.save_contact(dbi,issuer["wid"],dict(name=current["name"],email="changed@acacia.example.com",role=current["role"],organisation_id=issuer["org"],version=current["version"]),current["id"])
    fresh=crm.fresh_context(db,workspace,issuer["oid"])
    step=s.current_step(db,workspace,eid)
    with pytest.raises(s.Conflict): s.deliver(db,workspace,step["id"],step["version"],fresh)
    assert s.report(db,workspace)["deliveries"]==0
    s.refresh_context(db,workspace,eid,1,fresh)
    rid=deliver(db,workspace,eid,fresh)
    assert s.record(db,"receipts",workspace,rid)["recipient"]=="changed@acacia.example.com"


def test_revocation_stops_delivery_but_reply_is_recorded_and_reconnect_syncs(db,workspace,plan,issuer):
    context=connect(db,workspace,issuer)
    eid=s.enroll(db,workspace,plan,context,issuer["wid"])
    with issuer["app"].app_context():
        with loop_db().transaction(): loop_db().execute("UPDATE outreach_grants SET revoked=1 WHERE workspace_id=?",(issuer["wid"],))
    with pytest.raises(crm.CRMError): crm.fresh_context(db,workspace,issuer["oid"])
    s.outcome(db,workspace,eid,1,"opt_out","Record the stop while the live grant is unavailable.")
    assert s.current_step(db,workspace,eid) is None and s.report(db,workspace)["pending"]==1
    connect(db,workspace,issuer)
    assert crm.sync(db,workspace)==1 and len(source_activities(issuer))==1


def test_database_tokens_remain_encrypted_and_no_message_transport(db,workspace,issuer):
    connect(db,workspace,issuer)
    row=db.one("SELECT * FROM connections WHERE workspace_id=?",(workspace,))
    assert row["encrypted_token"].startswith("aesgcm:")
    with issuer["app"].app_context():
        grant=loop_db().one("SELECT * FROM outreach_grants WHERE revoked=0")
        assert len(grant["token_hash"])==64 and "encrypted_token" not in grant
    assert crm.call(db,workspace,"/opportunities")["items"][0]["id"]==issuer["oid"]


def test_disconnect_disables_local_token_and_revokes_issuer(db,workspace,issuer):
    connect(db,workspace,issuer)
    assert crm.disconnect(db,workspace) is None
    row=db.one("SELECT encrypted_token,status FROM connections WHERE workspace_id=?",(workspace,))
    assert row==dict(encrypted_token="",status="Disconnected")
    with issuer["app"].app_context(): assert loop_db().one("SELECT COUNT(*) AS n FROM outreach_grants WHERE revoked=0")["n"]==0


def test_wrong_source_pairing_does_not_remap_history(db,workspace,plan,issuer):
    context=connect(db,workspace,issuer)
    s.enroll(db,workspace,plan,context,issuer["wid"])
    with issuer["app"].app_context():
        other=ls.create_workspace(loop_db(),seed=False)
        other_code=lo.make_code(loop_db(),other)
    with pytest.raises(crm.CRMError): crm.pair(db,workspace,other_code)
    assert db.one("SELECT source_workspace_id FROM connections WHERE workspace_id=?",(workspace,))["source_workspace_id"]==issuer["wid"]
    with issuer["app"].app_context(): assert loop_db().one("SELECT COUNT(*) AS n FROM outreach_grants WHERE workspace_id=? AND revoked=0",(other,))["n"]==0


def test_http_review_proof_rejects_direct_approval_and_stale_snapshot(app,db,workspace,plan,issuer):
    import re
    from conftest import session_for
    context=connect(db,workspace,issuer)
    eid=s.enroll(db,workspace,plan,context,issuer["wid"])
    step=s.current_step(db,workspace,eid)
    client=app.test_client()
    csrf=session_for(client,workspace)
    action=f"/steps/{step['id']}/action"
    response=client.post(action,data=dict(csrf_token=csrf,version=step["version"],action="approve"))
    assert response.status_code==409 and s.current_step(db,workspace,eid)["approval"] is None
    review=client.get(f"/steps/{step['id']}/review")
    assert review.status_code==200
    proof=re.search(rb'name="review_token" value="([^"]+)"',review.data)[1].decode()
    s.save_draft(db,workspace,step["id"],step["version"],"Changed subject","This invalidates the previous review.")
    response=client.post(action,data=dict(csrf_token=csrf,version=step["version"],review_token=proof,action="approve"))
    assert response.status_code==409
    assert s.current_step(db,workspace,eid)["approval"] is None


def test_public_plan_editor_uses_structured_fields(app,db,workspace,plan):
    from conftest import session_for
    client=app.test_client()
    token=session_for(client,workspace)
    published=s.record(db,"plan_versions",workspace,plan)
    response=client.get("/plans")
    assert response.status_code==200 and b'Ordered steps' not in response.data
    response=client.post("/plans",data=dict(csrf_token=token,name="New plan version",family=published["family"],include_0="1",kind_0="message",title_0="Reviewed message",delay_0="0",subject_0="Hello ${contact_name}",body_0="Plain text instructions"))
    assert response.status_code==303
    assert db.one("SELECT MAX(revision) AS n FROM plan_versions WHERE family=?",(published["family"],))["n"]==2


def test_reset_also_revokes_live_crm_connection(app,db,workspace,issuer):
    from conftest import session_for
    connect(db,workspace,issuer)
    client=app.test_client()
    csrf=session_for(client,workspace)
    old=client.get_cookie("followdesk_session").value
    response=client.post("/demo",data=dict(csrf_token=csrf,reset="1"))
    assert response.status_code==303
    assert db.one("SELECT encrypted_token FROM connections WHERE workspace_id=?",(workspace,))["encrypted_token"]==""
    with issuer["app"].app_context(): assert loop_db().one("SELECT COUNT(*) AS n FROM outreach_grants WHERE revoked=0")["n"]==0
    other=app.test_client()
    other.set_cookie("followdesk_session",old)
    assert other.get("/queue").status_code==303
