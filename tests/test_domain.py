import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
from werkzeug.exceptions import NotFound,TooManyRequests
from followdesk import services as s
from followdesk.contract import ContractError,strict_json,event_payload
from conftest import run

FIXTURES=json.loads((Path(__file__).parent/"fixtures.json").read_text())


def deliver(db,wid,eid,context):
    step=s.current_step(db,wid,eid)
    s.approve(db,wid,step["id"],step["version"],context)
    step=s.current_step(db,wid,eid)
    return s.deliver(db,wid,step["id"],step["version"],context)


def finish_all(db,wid,eid,context,app):
    while (step:=s.current_step(db,wid,eid)):
        # Seed a due step without advancing the real 24-hour authorisation clock.
        with db.transaction():
            db.execute("UPDATE steps SET due_at=? WHERE workspace_id=? AND id=?",(s.stamp(),wid,step["id"]))
        step=s.current_step(db,wid,eid)
        if step["kind"]=="message": deliver(db,wid,eid,context)
        else: s.finish_task(db,wid,step["id"],step["version"],"Reviewed the fictional response.")


@pytest.mark.parametrize("fixture",FIXTURES,ids=[x["id"]+"-"+x["scenario"] for x in FIXTURES])
def test_authored_case(fixture,db,workspace,plan,context,app):
    case=fixture["scenario"]
    eid=run(db,workspace,plan,context)
    get_run=lambda:s.record(db,"enrollments",workspace,eid)
    get_step=lambda:s.current_step(db,workspace,eid)
    if case=="complete":
        finish_all(db,workspace,eid,context,app)
        assert get_run()["status"]=="Completed" and s.report(db,workspace)["deliveries"]==2
        assert db.one("SELECT COUNT(*) AS n FROM steps WHERE status='Done'")["n"]==1
    elif case=="reply":
        rid=deliver(db,workspace,eid,context)
        s.outcome(db,workspace,eid,get_run()["version"],"synthetic_reply","Please arrange a discussion.")
        assert get_run()["status"]=="Stopped" and get_step() is None
        assert s.record(db,"receipts",workspace,rid)["body"]
        assert s.report(db,workspace)["replies"]==1
    elif case in {"ooo","pause"}:
        deliver(db,workspace,eid,context)
        before=s.utc_value(get_step()["due_at"])-s.now()
        if case=="ooo": s.outcome(db,workspace,eid,get_run()["version"],"out_of_office","Away until next week; reviewer classification.")
        else: s.pause_resume(db,workspace,eid,get_run()["version"],"Wait for reviewed information.")
        assert get_run()["status"]=="Paused" and s.report(db,workspace)["replies"]==0
        app.test_clock[0]+=timedelta(hours=2)
        s.pause_resume(db,workspace,eid,get_run()["version"],"Resume with the same remaining delay.")
        assert s.utc_value(get_step()["due_at"])-s.now()==before
    elif case=="versions":
        original=db.all("SELECT subject,body FROM steps WHERE enrollment_id=? ORDER BY position",(eid,))
        published=s.record(db,"plan_versions",workspace,plan)
        steps=json.loads(published["steps"])
        steps[0]["body"]="A new version."
        s.publish_plan(db,workspace,"Enquiry follow-up",steps,published["family"])
        assert db.all("SELECT subject,body FROM steps WHERE enrollment_id=? ORDER BY position",(eid,))==original
    elif case=="separate_contacts":
        other=copy.deepcopy(context)
        other["id"]="6"*32
        other["contact"]["id"]="7"*32
        other["contact"]["email"]="other@acacia.example.com"
        run(db,workspace,plan,other)
        s.outcome(db,workspace,eid,get_run()["version"],"opt_out","Fictional contact opts out.")
        assert s.report(db,workspace)["active"]==1
    elif case=="meeting":
        s.outcome(db,workspace,eid,get_run()["version"],"meeting","Reviewer records a meeting; no calendar claim.")
        assert get_step() is None and s.report(db,workspace)["meetings"]==1 and s.report(db,workspace)["replies"]==0
    elif case=="reschedule":
        step=get_step()
        s.approve(db,workspace,step["id"],step["version"],context)
        step=get_step()
        s.reschedule(db,workspace,step["id"],step["version"],(s.now()+timedelta(hours=2)).isoformat(),"Wait for customer availability.")
        assert get_step()["approval"] is None
    elif case in {"duplicate_contact","duplicate_address","suppressed"}:
        other=copy.deepcopy(context)
        if case=="suppressed": s.outcome(db,workspace,eid,get_run()["version"],"opt_out","Do not contact again in this demo.")
        if case=="duplicate_address": other["id"],other["contact"]["id"]="8"*32,"9"*32
        with pytest.raises(ContractError): run(db,workspace,plan,other)
        assert s.report(db,workspace)["runs"]==1
    elif case in {"changed_recipient","closed","archived"}:
        step=get_step()
        s.approve(db,workspace,step["id"],step["version"],context)
        step=get_step()
        changed=copy.deepcopy(context)
        if case=="changed_recipient": changed["contact"]["email"]="new@acacia.example.com"
        if case=="closed": changed["stage"]="Won"
        if case=="archived": changed["organisation"]["archived"]=True
        with pytest.raises(ContractError): s.deliver(db,workspace,step["id"],step["version"],changed)
        assert s.report(db,workspace)["deliveries"]==0
    elif case=="unapproved":
        step=get_step()
        with pytest.raises(s.Conflict): s.deliver(db,workspace,step["id"],step["version"],context)
        assert s.report(db,workspace)["pending"]==0
    elif case=="future":
        deliver(db,workspace,eid,context)
        step=get_step()
        with pytest.raises(s.Conflict): s.finish_task(db,workspace,step["id"],step["version"],"Attempting early completion.")
        assert get_step()["status"]=="Pending"
    elif case=="repeat_delivery":
        step=get_step()
        s.approve(db,workspace,step["id"],step["version"],context)
        step=get_step()
        one=s.deliver(db,workspace,step["id"],step["version"],context)
        two=s.deliver(db,workspace,step["id"],step["version"],context)
        assert one==two and s.report(db,workspace)["deliveries"]==s.report(db,workspace)["pending"]==1
    elif case=="stale":
        step=get_step()
        s.save_draft(db,workspace,step["id"],step["version"],"New subject","Saved text")
        with pytest.raises(s.Conflict): s.save_draft(db,workspace,step["id"],step["version"],"Stale","Do not overwrite")
        assert get_step()["body"]=="Saved text"
    elif case=="zero_delay":
        app.test_clock[0]+=timedelta(hours=2)
        deliver(db,workspace,eid,context)
        assert s.utc_value(get_step()["due_at"])==s.now()+timedelta(hours=48)
    elif case=="unicode_limit":
        step=get_step()
        with pytest.raises(ContractError): s.save_draft(db,workspace,step["id"],step["version"],"Subject","🙂"*1025)
    elif case=="event_integrity":
        deliver(db,workspace,eid,context)
        payload=json.loads(db.one("SELECT payload FROM events")["payload"])
        assert event_payload(payload)==payload
        payload["summary"]="Changed content"
        with pytest.raises(ContractError): event_payload(payload)
    elif case=="late_reply":
        finish_all(db,workspace,eid,context,app)
        s.outcome(db,workspace,eid,get_run()["version"],"reviewer_reply","Reviewer records a late fictional reply.")
        assert s.report(db,workspace)["replies"]==1 and s.report(db,workspace)["deliveries"]==2
    elif case=="skip":
        step=get_step()
        s.finish_task(db,workspace,step["id"],step["version"],"Skip this fictional introductory message.",True)
        assert s.report(db,workspace)["deliveries"]==0 and get_step()["kind"]=="task"
    elif case=="quota_rollback":
        step=get_step()
        s.approve(db,workspace,step["id"],step["version"],context)
        step=get_step()
        with db.transaction():
            while db.one("SELECT count(*) AS n FROM audit_events")["n"]<500:
                db.execute("INSERT INTO audit_events VALUES (?,?,?,?,?,?)",(s.uid(),workspace,eid,"fixture","At quota",s.stamp()))
        with pytest.raises(TooManyRequests): s.deliver(db,workspace,step["id"],step["version"],context)
        assert s.report(db,workspace)["deliveries"]==0 and get_step()["status"]=="Pending"
    elif case=="template_literal":
        assert s.render_text("{{7*7}} Hello ${contact_name}",context)=="{{7*7}} Hello Alex Example"
    elif case=="template_unknown":
        with pytest.raises(ContractError): s.render_text("${config.SECRET_KEY}",context)
    elif case=="no_recursion":
        context["contact"]["name"]="${next_action} {{7*7}}"
        assert s.render_text("Hi ${contact_name}",context)=="Hi ${next_action} {{7*7}}"
    elif case=="workspace_denial":
        other=s.create_workspace(db)
        with pytest.raises(NotFound): s.record(db,"enrollments",other,eid)
    elif case=="safe_csv":
        s.outcome(db,workspace,eid,get_run()["version"],"reviewer_reply","=HYPERLINK(\"https://invalid.example\")")
        assert "'=HYPERLINK" in s.csv_export(db.all("SELECT * FROM events"))
    elif case=="integer_bounds":
        step=get_step()
        for bad in ("9"*100,True,-1,0,"1.0",None):
            with pytest.raises(s.Conflict): s.save_draft(db,workspace,step["id"],bad,"Subject","Text")
    elif case=="strict_json":
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'\xff',b'['*1000):
            with pytest.raises(ContractError): strict_json(raw)
    elif case=="subject_injection":
        step=get_step()
        with pytest.raises(ContractError): s.save_draft(db,workspace,step["id"],step["version"],"Hello\nBcc: victim@example.com","Text")
    else: pytest.fail("Authored fixture has no implementation: "+case)


def test_fixture_distribution():
    assert len(FIXTURES)==32 and len({f["id"] for f in FIXTURES})==32
    assert {group:sum(x["group"]==group for x in FIXTURES) for group in ("valid","conflicting","boundary","security")}==dict(valid=8,conflicting=8,boundary=8,security=8)


def test_later_optout_on_replied_run_is_not_lost(db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    s.outcome(db,workspace,eid,1,"reviewer_reply","First fictional reply.")
    s.outcome(db,workspace,eid,1,"opt_out","Later request to stop all contact.")
    assert s.record(db,"enrollments",workspace,eid)["stop_reason"]=="opt_out"
    with pytest.raises(ContractError): run(db,workspace,plan,context)
    # Repeated identical command has no duplicate event.
    s.outcome(db,workspace,eid,1,"opt_out","Later request to stop all contact.")
    assert s.report(db,workspace)["pending"]==2


@pytest.mark.parametrize("bad",[[],{},True,None,3])
def test_plan_kind_type_is_rejected(db,workspace,bad):
    with pytest.raises(ContractError):
        s.publish_plan(db,workspace,"Bad",[dict(kind=bad,title="Title",delay_hours=0,subject="Subject",body="Text")])


def test_optout_address_case_variant_cannot_bypass(db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    s.outcome(db,workspace,eid,1,"opt_out","Do not contact this fictional person.")
    context["contact"]["id"]="9"*32
    context["contact"]["email"]="Alex@acacia.example.com"
    with pytest.raises(ContractError): run(db,workspace,plan,context)


def test_optout_on_previous_run_cancels_new_active_run(db,workspace,plan,context):
    old=run(db,workspace,plan,context)
    s.outcome(db,workspace,old,1,"reviewer_reply","Initial response.")
    new=run(db,workspace,plan,context)
    s.outcome(db,workspace,old,2,"opt_out","Later global contact opt-out.")
    assert s.record(db,"enrollments",workspace,new)["status"]=="Stopped"
    assert s.current_step(db,workspace,new) is None
    assert s.report(db,workspace)["active"]==0


def test_safety_stop_has_reserved_audit_capacity(db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    with db.transaction():
        while db.one("SELECT count(*) AS n FROM audit_events")["n"]<500:
            db.execute("INSERT INTO audit_events VALUES (?,?,?,?,?,?)",(s.uid(),workspace,eid,"fixture","At normal audit quota",s.stamp()))
    s.outcome(db,workspace,eid,1,"opt_out","A safety stop must still be recorded.")
    assert s.record(db,"enrollments",workspace,eid)["status"]=="Stopped"
    assert s.current_step(db,workspace,eid) is None


def test_expiry_cleanup_removes_complete_graph(db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    deliver(db,workspace,eid,context)
    s.outcome(db,workspace,eid,s.record(db,"enrollments",workspace,eid)["version"],"opt_out","Fictional opt-out before expiry.")
    with db.transaction():
        db.execute("INSERT INTO connections VALUES (?,?,?,?,?)",(workspace,"5"*32,"fixture ciphertext never used",s.stamp(),"Disconnected"))
        db.execute("UPDATE workspaces SET expires_at=? WHERE id=?",((s.now()-timedelta(seconds=1)).isoformat(),workspace))
    new=s.create_workspace(db)
    assert new!=workspace
    for table in ("enrollments","steps","receipts","events","audit_events","suppressions","connections","plan_versions"):
        assert db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE workspace_id=?",(workspace,))["n"]==0,table
