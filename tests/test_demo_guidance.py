import html
import re
import sqlite3
from datetime import timedelta

import pytest

from followdesk import crm,services as s
from conftest import run,session_for
from test_domain import deliver


def grant(db,wid,expires=None,status="Connected"):
    with db.transaction():
        db.execute("INSERT INTO connections VALUES (?,?,?,?,?)",(wid,"5"*32,"encrypted-fixture",expires or (s.now()+timedelta(hours=1)).isoformat(),status))


def preview_fields(db,wid,pid,index=0):
    plan=s.record(db,"plan_versions",wid,pid)
    data=dict(plan_id=pid,family=plan["family"],name="Unsaved plan name",preview=str(index))
    for i in range(5):
        data.update({f"kind_{i}":"message",f"title_{i}":f"Unsaved step {i+1}",f"subject_{i}":"Hello ${contact_name}",f"body_{i}":"For ${client_name}",f"delay_{i}":str(i)})
    data["include_0"]="1"
    return data


def test_checklist_follows_saved_data_and_exact_completion(app,db,workspace,plan,context):
    client=app.test_client()
    session_for(client,workspace)
    response=client.get("/queue")
    assert response.status_code==200
    assert b'aria-current="step"' in response.data and b'Connect LoopDesk</a>' in response.data
    assert b'target="_blank" rel="noopener"' in response.data
    assert b'Next: Connect LoopDesk.' in response.data
    assert [x["state"] for x in s.demo_progress(db,workspace,False)["steps"]]==["next"]+["later"]*5
    assert s.demo_progress(db,workspace,True)["next"]["endpoint"]=="enroll"
    eid=run(db,workspace,plan,context)
    progress=s.demo_progress(db,workspace,True)
    assert progress["next"]["args"]==dict(eid=eid,_anchor="message-editor")
    assert progress["steps"][2]["state"]=="next"  # Enrolment's generated draft is not an authored save.
    step=s.current_step(db,workspace,eid)
    s.save_draft(db,workspace,step["id"],step["version"],"Saved subject","Saved body")
    assert s.demo_progress(db,workspace,True)["steps"][3]["state"]=="next"
    deliver(db,workspace,eid,context)
    assert s.demo_progress(db,workspace,True)["steps"][4]["state"]=="next"
    current=s.record(db,"enrollments",workspace,eid)
    s.outcome(db,workspace,eid,current["version"],"reviewer_reply","Fictional reply")
    assert s.demo_progress(db,workspace,True)["steps"][5]["state"]=="next"
    events=db.all("SELECT id FROM events WHERE workspace_id=? ORDER BY sequence",(workspace,))
    with db.transaction(): db.execute("UPDATE events SET sync_status='Synced' WHERE workspace_id=? AND id=?",(workspace,events[0]["id"]))
    assert not s.demo_progress(db,workspace,True)["complete"]
    with db.transaction(): db.execute("UPDATE events SET sync_status='Synced' WHERE workspace_id=?",(workspace,))
    assert s.demo_progress(db,workspace,True)["complete"]
    assert s.demo_progress(db,workspace,False)["next"]["endpoint"]=="connection"


def test_empty_and_foreign_workspace_history_do_not_complete_checklist(app,db,workspace,plan,context,monkeypatch):
    assert not s.demo_progress(db,workspace,True)["steps"][5]["done"]
    eid=run(db,workspace,plan,context)
    step=s.current_step(db,workspace,eid)
    s.save_draft(db,workspace,step["id"],step["version"],"<script>inert</script>","{{7*7}}")
    deliver(db,workspace,eid,context)
    s.outcome(db,workspace,eid,1,"reviewer_reply","Fictional reply")
    with db.transaction(): db.execute("UPDATE events SET sync_status='Synced' WHERE workspace_id=?",(workspace,))
    grant(db,workspace)
    monkeypatch.setattr(crm,"call",lambda *args,**kwargs:dict(items=[]))
    client=app.test_client()
    session_for(client,workspace)
    response=client.get("/queue")
    assert b'<details class="card demo-path">' in response.data
    assert b'6 of 6 done' in response.data
    assert b'<script>inert</script>' not in response.data
    other=s.create_workspace(db)
    session_for(client,other)
    response=client.get("/queue")
    assert b'0 of 6 done' in response.data
    assert b'Next: Connect LoopDesk.' in response.data
    assert not any(step["done"] for step in s.demo_progress(db,other,False)["steps"])


def test_stopped_unsaved_run_links_to_new_enrolment(db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    s.outcome(db,workspace,eid,1,"stopped","Fictional manual stop")
    assert s.demo_progress(db,workspace,True)["next"]["endpoint"]=="enroll"


@pytest.mark.parametrize("status,offset,expected",[("Connected",3600,"Connected until"),("Connected",0,"Expired"),("Connected",-1,"Expired"),("Disconnected",3600,"Revoked"),("Revoked",3600,"Revoked")])
def test_connection_status_expiry_boundaries_and_workspace(app,db,workspace,monkeypatch,status,offset,expected):
    grant(db,workspace,(s.now()+timedelta(seconds=offset)).isoformat(),status)
    calls=[]
    def available(db,wid,path):
        calls.append((wid,path))
        return dict(items=[])
    monkeypatch.setattr(crm,"call",available)
    client=app.test_client()
    session_for(client,workspace)
    response=client.get("/connection")
    assert response.status_code==200 and expected.encode() in response.data
    if expected=="Connected until":
        assert b'26 Oct 2026' in response.data and b'17:00 Dubai' in response.data
        assert calls==[(workspace,"/opportunities")]
    else: assert calls==[]
    session_for(client,s.create_workspace(db))
    assert b'Not connected' in client.get("/connection").data


@pytest.mark.parametrize("error,expected",[(crm.CRMAccessError,"Revoked"),(crm.CRMError,"Connected until")])
def test_connection_live_revocation_and_outage_are_distinct(app,db,workspace,monkeypatch,error,expected):
    grant(db,workspace)
    def failed(*args): raise error("Secret upstream detail")
    monkeypatch.setattr(crm,"call",failed)
    client=app.test_client()
    session_for(client,workspace)
    response=client.get("/connection")
    assert expected.encode() in response.data and b'Secret upstream detail' not in response.data
    assert (b'LoopDesk could not be checked' in response.data)==(error is crm.CRMError)
    assert b'Next: Connect LoopDesk.' in client.get("/queue").data
    assert db.one("SELECT status FROM connections WHERE workspace_id=?",(workspace,))["status"]=="Connected"


@pytest.mark.parametrize("token,expected",[("contact_name","Alex Example (fictional)"),("client_name","Fictional Cedar Recycling"),("opportunity_title","Fictional laptop collection enquiry"),("received_scope_revision","2"),("next_action","Discuss the fictional collection scope")])
def test_preview_uses_enrolment_renderer_for_every_placeholder(token,expected):
    result=s.preview_message("message","${"+token+"}","${"+token+"} $$ {{7*7}} <script>alert(1)</script>")
    assert result["subject"]==expected
    assert result["body"]==expected+' $ {{7*7}} <script>alert(1)</script>'


@pytest.mark.parametrize("index",range(5))
def test_preview_unsaved_steps_preserves_all_fields_and_never_publishes(app,db,workspace,plan,index):
    client=app.test_client()
    token=session_for(client,workspace)
    fields=preview_fields(db,workspace,plan,index)
    fields.update(csrf_token=token)
    fields[f"body_{index}"]='<script>alert("x")</script> {{7*7}} ${contact_name}'
    before=db.all("SELECT * FROM plan_versions WHERE workspace_id=? ORDER BY id",(workspace,))
    response=client.post("/plans",data=fields)
    assert response.status_code==200
    content=response.data.decode()
    assert 'Sample preview · fictional contact' in content
    assert 'Alex Example (fictional)' in content and '{{7*7}}' in content
    assert '<script>alert(' not in content and '&lt;script&gt;' in content
    assert f'id="preview-{plan}-{index}"' in content
    assert 'value="Unsaved plan name"' in content
    assert '<h2>Unsaved plan name</h2>' not in content
    assert 'value="Unsaved step 5"' in content
    assert f'id="include-{plan}-0" type="checkbox" name="include_0" value="1" checked' in content
    assert f'id="include-{plan}-4" type="checkbox" name="include_4" value="1" checked' not in content
    assert db.all("SELECT * FROM plan_versions WHERE workspace_id=? ORDER BY id",(workspace,))==before
    assert not db.one("SELECT id FROM enrollments WHERE workspace_id=?",(workspace,))


@pytest.mark.parametrize("value",["${unknown}","${contact_name.__class__}","${", "$not_allowed"])
def test_preview_rejects_unknown_and_malformed_placeholders(app,db,workspace,plan,value):
    client=app.test_client()
    token=session_for(client,workspace)
    data=preview_fields(db,workspace,plan)
    data.update(csrf_token=token,body_0=value)
    response=client.post("/plans",data=data)
    assert response.status_code==422 and b'Use only the listed text placeholders' in response.data
    assert html.escape(value).encode() in response.data
    assert b'Unsaved plan name' in response.data


@pytest.mark.parametrize("subject,body,expected",[("x"*200,"x"*4096,200),("x"*201,"body",422),("subject","x"*4097,422),("line\nBcc: hostile@example.com","body",422),("subject","界"*1365,200),("subject","界"*1366,422),("","body",422),("x"*185+"${contact_name}","body",422),("subject","x"*4080+"${client_name}",422)])
def test_preview_text_boundaries(app,db,workspace,plan,subject,body,expected):
    client=app.test_client()
    token=session_for(client,workspace)
    data=preview_fields(db,workspace,plan)
    data.update(csrf_token=token,subject_0=subject,body_0=body)
    assert client.post("/plans",data=data).status_code==expected


@pytest.mark.parametrize("index",["-1","5","999999999999999999999","0; DROP TABLE steps","<script>",""])
def test_preview_rejects_invalid_step_index(app,db,workspace,plan,index):
    client=app.test_client()
    token=session_for(client,workspace)
    data=preview_fields(db,workspace,plan)
    data.update(csrf_token=token,preview=index)
    assert client.post("/plans",data=data).status_code==422


def test_preview_csrf_origin_and_cross_workspace(app,db,workspace,plan):
    client=app.test_client()
    token=session_for(client,workspace)
    data=preview_fields(db,workspace,plan)
    assert client.post("/plans",data=data).status_code==400
    data["csrf_token"]=token
    assert client.post("/plans",data=data,headers={"Origin":"https://hostile.example"}).status_code==403
    session_for(client,s.create_workspace(db))
    assert client.post("/plans",data=data).status_code==404
    data["plan_id"]="' OR 1=1 --"
    assert client.post("/plans",data=data).status_code==422


def test_manual_task_preview_uses_plain_instructions():
    assert s.preview_message("task","","Discuss ${opportunity_title}")["body"]=='Discuss Fictional laptop collection enquiry'
    with pytest.raises(s.ValidationError): s.preview_message("unlisted","Subject","Body")


def test_page_metadata_and_helpful_redacted_errors(app,db,workspace,plan,context,monkeypatch):
    client=app.test_client()
    session_for(client,workspace)
    eid=run(db,workspace,plan,context)
    rid=deliver(db,workspace,eid,context)
    monkeypatch.setattr(crm,"call",lambda *args,**kwargs:dict(items=[]))
    titles=[]
    for path in ("/","/queue","/connection","/enroll","/plans","/reports","/inbox",f"/runs/{eid}",f"/inbox/{rid}","/missing-page"):
        response=client.get(path)
        assert response.status_code in {200,404}
        for tag in (b'name="description"',b'property="og:title"',b'property="og:description"',b'name="theme-color"'):
            assert tag in response.data
        titles.append(re.search(rb'<title>(.*?)</title>',response.data).group(1))
    assert len(set(titles))==len(titles)
    response=client.get('/missing-page')
    assert response.status_code==404 and b'Page not found.' in response.data
    assert b'href="/queue">Return to work queue' in response.data
    anonymous=app.test_client()
    assert anonymous.get('/missing-page').status_code==404


@pytest.mark.parametrize("failure,code",[(sqlite3.OperationalError,503),(RuntimeError,500)])
def test_error_pages_redact_internal_details_and_offer_queue(app,workspace,monkeypatch,failure,code):
    def fail(*args): raise failure("sensitive database detail /do-not-expose")
    app.config["PROPAGATE_EXCEPTIONS"]=False
    monkeypatch.setattr(s,"report",fail)
    client=app.test_client()
    session_for(client,workspace)
    response=client.get("/reports")
    assert response.status_code==code
    assert b'sensitive database detail' not in response.data and b'/do-not-expose' not in response.data
    assert b'href="/queue">Return to work queue' in response.data
    assert b'name="description"' in response.data
    if code==503: assert response.headers["Retry-After"]=="30"

