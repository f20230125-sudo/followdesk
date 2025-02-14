import copy
import json
import pytest
from followdesk import create_app,services as s
from followdesk.contract import ContractError
from followdesk import crm
from conftest import run,session_for
from test_domain import deliver


def test_pages_csrf_inbox_and_escape(app,db,workspace,plan,context):
    context["title"]="<script>alert('x')</script>"
    eid=run(db,workspace,plan,context)
    client=app.test_client()
    token=session_for(client,workspace)
    for path in ("/queue",f"/runs/{eid}","/connection","/plans","/reports","/inbox"):
        response=client.get(path)
        assert response.status_code==200,path
        assert b"<script>alert('x')</script>" not in response.data
        assert response.headers["Cache-Control"]=="no-store"
    response=client.post(f"/runs/{eid}/action",data={"action":"outcome","version":1,"kind":"opt_out","note":"Test"})
    assert response.status_code==400
    response=client.post(f"/runs/{eid}/action",data={"csrf_token":token,"action":"outcome","version":1,"kind":"opt_out","note":"Fictional opt-out"},headers={"Origin":"https://evil.example"})
    assert response.status_code==403
    rid=deliver(db,workspace,eid,context)
    assert client.get("/inbox/"+rid).status_code==200
    assert b"Simulated" in client.get("/reports.csv").data
    other=app.test_client()
    other_wid=s.create_workspace(db)
    session_for(other,other_wid)
    assert other.get("/inbox/"+rid).status_code==404
    assert other.get("/runs/"+eid).status_code==404


def test_reply_stops_locally_without_network(app,db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    client=app.test_client()
    token=session_for(client,workspace)
    response=client.post(f"/runs/{eid}/action",data=dict(csrf_token=token,action="outcome",version=1,kind="reviewer_reply",note="A reply was recorded while the CRM was unavailable."))
    assert response.status_code==303
    assert s.record(db,"enrollments",workspace,eid)["status"]=="Stopped"
    assert s.report(db,workspace)["pending"]==1


def test_reset_revokes_saved_cookie(app,db,workspace):
    client=app.test_client()
    token=session_for(client,workspace)
    old=client.get_cookie("followdesk_session").value
    response=client.post("/demo",data=dict(csrf_token=token,reset="1"))
    assert response.status_code==303
    replay=app.test_client()
    replay.set_cookie("followdesk_session",old)
    assert replay.get("/queue").status_code==303
    assert replay.post("/sync",data=dict(csrf_token=token)).status_code==303


def test_draft_error_preserves_input(app,db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    step=s.current_step(db,workspace,eid)
    client=app.test_client()
    token=session_for(client,workspace)
    response=client.post(f"/steps/{step['id']}/action",data=dict(csrf_token=token,version=999,action="draft",subject="Keep this draft",body="My unsaved words"))
    assert response.status_code==409
    assert b"Keep this draft" in response.data and b"My unsaved words" in response.data
    assert b'disabled' in response.data
    assert s.current_step(db,workspace,eid)["body"]!="My unsaved words"


def test_native_browser_line_endings_are_normalised(db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    step=s.current_step(db,workspace,eid)
    s.save_draft(db,workspace,step["id"],step["version"],"Subject","Line one\r\nLine two")
    assert s.current_step(db,workspace,eid)["body"]=="Line one\nLine two"


@pytest.mark.parametrize("separator",["\n","\r\n","\t"])
def test_crm_placeholder_cannot_add_subject_headers(db,workspace,plan,context,separator):
    context["title"]="Laptop scope"+separator+"Bcc: external@example.com"
    before=db.one("SELECT COUNT(*) AS n FROM audit_events WHERE workspace_id=?",(workspace,))["n"]
    with pytest.raises(ContractError,match="subject must be a single line"):
        run(db,workspace,plan,context)
    assert not db.one("SELECT id FROM enrollments WHERE workspace_id=?",(workspace,))
    assert not db.one("SELECT id FROM steps WHERE workspace_id=?",(workspace,))
    assert db.one("SELECT COUNT(*) AS n FROM audit_events WHERE workspace_id=?",(workspace,))["n"]==before


def test_real_clock_expiry_not_schedule(app,db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    client=app.test_client()
    session_for(client,workspace)
    with db.transaction(): db.execute("UPDATE workspaces SET expires_at=? WHERE id=?",("2026-10-25T00:00:00+00:00",workspace))
    assert client.get("/queue").status_code==303
    with pytest.raises(s.Conflict): s.outcome(db,workspace,eid,1,"reviewer_reply","Cannot mutate an expired workspace.")


@pytest.mark.parametrize("base",["http://evil.example","https://example.com/extra","https://user:pass@example.com","https://example.com?x=1","file:///secret"])
def test_fixed_origin_configuration_fails_closed(base,tmp_path):
    with pytest.raises(crm.CRMError):
        create_app(dict(TESTING=True,SECRET_KEY="test",DATABASE_URL="sqlite:///"+str(tmp_path/"x.sqlite3"),LOOPDESK_URL=base))


def test_vault_roundtrip_and_no_plaintext(app):
    from followdesk.vault import seal,open_token
    with app.app_context():
        token="fixture-high-entropy-token-not-a-real-grant"
        encrypted=seal(token)
        assert token not in encrypted and open_token(encrypted)==token


def test_contract_copy_parity():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    if (root/"loopdesk/loopdesk/outreach_contract.py").exists():
        assert (root/"followdesk/followdesk/contract.py").read_bytes()==(root/"loopdesk/loopdesk/outreach_contract.py").read_bytes()


@pytest.mark.parametrize("content_type",["application/x-www-form-urlencoded","multipart/form-data"])
def test_five_valid_maximum_utf8_steps_fit_form_boundary(app,db,workspace,content_type):
    client=app.test_client()
    token=session_for(client,workspace)
    fields=dict(csrf_token=token,name="Full bounded plan",family="")
    for index in range(5):
        fields.update({f"include_{index}":"1",f"kind_{index}":"message",f"title_{index}":"界"*53,f"delay_{index}":"720",f"subject_{index}":"界"*66,f"body_{index}":"界"*1365})
    response=client.post("/plans",data=fields,content_type=content_type)
    assert response.status_code==303
    published=db.one("SELECT steps FROM plan_versions WHERE workspace_id=? AND name=?",(workspace,"Full bounded plan"))
    assert len(json.loads(published["steps"]))==5
