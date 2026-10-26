"""Shared transactional workflow services for HTTP handlers and tests."""
import csv
import io
import json
import re
import sqlite3
import uuid
from datetime import datetime,timedelta,timezone
from string import Template

import psycopg
from flask import current_app
from werkzeug.exceptions import NotFound,TooManyRequests

from . import security
from .contract import ContractError,canonical,digest,text,identifier,address_key


class ValidationError(ContractError):
    pass


class Conflict(ValidationError):
    pass


def uid(): return uuid.uuid4().hex
def now(): return current_app.config.get("CLOCK",lambda:datetime.now(timezone.utc))()
def stamp(): return now().isoformat()


def utc_value(value):
    try:
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds()!=0:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError,TypeError,AttributeError):
        raise ValidationError("Use a valid UTC timestamp.") from None


def lock(db,wid):
    security._lock_workspace(db,wid)
    if not security.active_workspace(db,wid,stamp()):
        raise Conflict("This workspace expired or was reset. Start a fresh demo.")


CAPS={"plan_versions":10,"enrollments":25,"receipts":125,"events":400,"audit_events":500}


def cap(db,wid,table,critical=False):
    if table not in CAPS: raise ValueError("Unknown quota")
    maximum=CAPS[table]+(50 if critical and table in {"events","audit_events"} else 0)
    if db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE workspace_id=?",(wid,))["n"]>=maximum:
        raise TooManyRequests("This demo reached its record limit. Existing history is retained.",retry_after=3600)


def audit(db,wid,eid,action,note,critical=False):
    cap(db,wid,"audit_events",critical)
    db.execute("INSERT INTO audit_events VALUES (?,?,?,?,?,?)",(uid(),wid,eid,action,text(note,"Audit note",1800),stamp()))


def record(db,table,wid,rid):
    if table not in {"enrollments","steps","plan_versions","receipts"}: raise ValueError("Unknown table")
    row=db.one(f"SELECT * FROM {table} WHERE workspace_id=? AND id=?",(wid,rid))
    if not row: raise NotFound("This record is not available in your workspace.")
    return row


def version(row,value):
    if security.positive_integer(value)!=row["version"]:
        raise Conflict("This item changed after you opened it. Reload before saving; your submitted draft has not been applied.")


TOKENS={"contact_name","client_name","opportunity_title","received_scope_revision","next_action"}


def render_text(source,context):
    template=Template(source)
    if not template.is_valid() or not set(template.get_identifiers())<=TOKENS:
        raise ValidationError("Use only the listed text placeholders. Escape a literal dollar sign as $$.")
    scopes=context["received_scopes"]
    values=dict(contact_name=context["contact"]["name"],client_name=context["organisation"]["name"],opportunity_title=context["title"],next_action=context["next_action"],received_scope_revision=", ".join(str(x["revision"]) for x in scopes))
    if "received_scope_revision" in template.get_identifiers() and not scopes:
        raise ValidationError("This plan needs a reviewed scope already imported into LoopDesk.")
    return template.substitute(values)


def publish_plan(db,wid,name,steps,family=None):
    name=text(name,"Plan name",160)
    if not isinstance(steps,list) or not 1<=len(steps)<=5:
        raise ValidationError("A plan needs one to five ordered steps.")
    clean=[]
    for item in steps:
        if not isinstance(item,dict) or set(item)!={"kind","title","delay_hours","subject","body"}:
            raise ValidationError("Invalid plan step.")
        if not isinstance(item["kind"],str) or item["kind"] not in {"message","task"} or type(item["delay_hours"]) is not int or not 0<=item["delay_hours"]<=720:
            raise ValidationError("Choose a listed step type and a delay from 0 to 720 elapsed hours.")
        row=dict(kind=item["kind"],title=text(item["title"],"Step title",160),delay_hours=item["delay_hours"],subject=text(item["subject"],"Subject",200,item["kind"]=="message"),body=text(item["body"],"Message or task instructions",4096))
        if "\n" in row["subject"] or "\t" in row["subject"]:
            raise ValidationError("Subject must be a single line.")
        for value in (row["subject"],row["body"]):
            tpl=Template(value)
            if not tpl.is_valid() or not set(tpl.get_identifiers())<=TOKENS:
                raise ValidationError("A template contains an unknown or malformed placeholder.")
        clean.append(row)
    with db.transaction():
        lock(db,wid)
        cap(db,wid,"plan_versions")
        revision=1
        if family:
            previous=db.one("SELECT MAX(revision) AS n FROM plan_versions WHERE workspace_id=? AND family=?",(wid,family))
            if not previous or previous["n"] is None: raise NotFound("Plan family is unavailable.")
            revision=previous["n"]+1
        else: family=uid()
        pid=_insert_plan(db,wid,name,clean,family,revision)
    return pid


def _insert_plan(db,wid,name,steps,family,revision):
    pid=uid()
    db.execute("INSERT INTO plan_versions VALUES (?,?,?,?,?,?,?)",(pid,wid,name,family,revision,canonical(steps),stamp()))
    audit(db,wid,None,"plan_published",f"{name} · version {revision}. Existing runs retain their original steps.")
    return pid


def create_workspace(db):
    wid=uid()
    enquiry=[dict(kind="message",title="First follow-up",delay_hours=0,subject="Next steps: ${opportunity_title}",body="Hello ${contact_name},\n\nI am following up on ${opportunity_title} for ${client_name}. Could we discuss the next step?\n\nThis is a fictional demonstration message."),dict(kind="task",title="Review response and next action",delay_hours=48,subject="",body="Review any response before deciding whether another message is appropriate. Record completion or a reasoned skip."),dict(kind="message",title="Final follow-up",delay_hours=72,subject="Follow-up: ${opportunity_title}",body="Hello ${contact_name},\n\nWould you like to continue the discussion about ${opportunity_title}? Please let us know your preferred next step.")]
    scope=[dict(enquiry[0],subject="Discussion of reviewed scope ${received_scope_revision}",body="Hello ${contact_name},\n\nCould we discuss the scope revision ${received_scope_revision} received in LoopDesk for ${client_name}? Any remaining questions or assumptions still need confirmation. Internal review does not mean customer acceptance."),*enquiry[1:]]
    with db.transaction():
        # Acquire global capacity lock before cleanup; don't upgrade a table lock
        # after taking row locks on PostgreSQL.
        if db.postgres: db.execute("LOCK TABLE workspaces IN SHARE ROW EXCLUSIVE MODE")
        else: db.execute("UPDATE workspaces SET created_at=created_at WHERE id='capacity-lock'")
        cutoff=stamp()
        # Receipts/events have two scoped parent relationships. Remove leaves
        # first, using one cutoff, before the workspace cascades other records.
        for table in ("receipts","events"):
            db.execute(f"DELETE FROM {table} WHERE workspace_id IN (SELECT id FROM workspaces WHERE expires_at<=?)",(cutoff,))
        db.execute("DELETE FROM workspaces WHERE expires_at<=?",(cutoff,))
        if db.one("SELECT COUNT(*) AS n FROM workspaces")["n"]>=250:
            raise TooManyRequests("Demo capacity reached. Please try later.",retry_after=3600)
        db.execute("INSERT INTO workspaces VALUES (?,?,?)",(wid,stamp(),(now()+timedelta(hours=24)).isoformat()))
        _insert_plan(db,wid,"Enquiry follow-up",enquiry,uid(),1)
        _insert_plan(db,wid,"Reviewed scope next discussion",scope,uid(),1)
    return wid


def validate_context(context):
    if not isinstance(context,dict): raise ValidationError("Invalid CRM context.")
    identifier(context["id"])
    for key in ("title","stage","service","owner","next_action"):
        text(context[key],key,2000)
    if context["stage"] not in {"New","Contacted","Qualified","Proposal","Won","Lost"}: raise ValidationError("Unrecognised CRM stage.")
    for key in ("contact","organisation"):
        value=context[key]
        identifier(value["id"])
        text(value["name"],"Name",640)
        if type(value["archived"]) is not bool or security.positive_integer(value["version"]) is None: raise ValidationError("Invalid CRM record status.")
    address_key(context["contact"]["email"])
    if security.positive_integer(context["version"]) is None or not isinstance(context["received_scopes"],list) or len(context["received_scopes"])>20: raise ValidationError("Invalid CRM context versions.")
    for item in context["received_scopes"]:
        identifier(item["case_id"])
        if security.positive_integer(item["revision"]) is None or not re.fullmatch(r"[0-9a-f]{64}",item["digest"]) or item["review_status"] not in {"Reviewed","Reviewed with assumptions"}:
            raise ValidationError("Invalid received scope identity.")
    if len(canonical(context).encode())>32768: raise ValidationError("CRM context exceeds the demo limit.")
    return context


def eligible(context):
    validate_context(context)
    if context["stage"] in {"Won","Lost"}: raise ValidationError("This opportunity is closed. Delivery is blocked.")
    if context["contact"]["archived"] or context["organisation"]["archived"]: raise ValidationError("The contact or organisation is archived. Delivery is blocked.")


def context_hash(context):
    # Metadata-only version increments do not force a content change.
    data=json.loads(canonical(context))
    data.pop("version",None)
    for key in ("contact","organisation"): data[key].pop("version",None)
    return digest(data)


def suppressed(db,wid,contact_id,email):
    if db.one("SELECT identity FROM suppressions WHERE workspace_id=? AND ((key_type='contact' AND identity=?) OR (key_type='address' AND identity=?))",(wid,contact_id,address_key(email))):
        raise ValidationError("This contact or destination is suppressed in this demo and cannot receive outreach.")
    key=address_key(email)
    for row in db.all("SELECT identity FROM suppressions WHERE workspace_id=? AND key_type='address'",(wid,)):
        if row["identity"].casefold()==key.casefold():
            raise ValidationError("A possible case variant of this destination is suppressed. Clarify the identity before enrolling; records were not merged.")


def destination_guard(db,wid,email,exclude=None):
    # Preserve case-sensitive local parts. Possible case variants need clarification.
    key=address_key(email)
    for row in db.all("SELECT id,address_key FROM enrollments WHERE workspace_id=? AND status IN ('Active','Paused')",(wid,)):
        if row["id"]!=exclude and row["address_key"].casefold()==key.casefold():
            raise Conflict("An active run uses this address or a possible case variant. Review the existing run; records have not been merged.")


def enroll(db,wid,pid,context,source_workspace_id):
    eligible(context)
    identifier(source_workspace_id)
    try:
        with db.transaction():
            lock(db,wid)
            cap(db,wid,"enrollments")
            suppressed(db,wid,context["contact"]["id"],context["contact"]["email"])
            destination_guard(db,wid,context["contact"]["email"])
            if db.one("SELECT id FROM enrollments WHERE workspace_id=? AND contact_id=? AND status IN ('Active','Paused')",(wid,context["contact"]["id"])):
                raise Conflict("This CRM contact already has an active or paused run.")
            plan=record(db,"plan_versions",wid,pid)
            eid=uid()
            db.execute("INSERT INTO enrollments(id,workspace_id,source_workspace_id,opportunity_id,contact_id,address_key,context,plan_id,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(eid,wid,source_workspace_id,context["id"],context["contact"]["id"],address_key(context["contact"]["email"]),canonical(context),pid,"Active",stamp()))
            for index,item in enumerate(json.loads(plan["steps"])):
                subject=text(render_text(item["subject"],context),"Rendered subject",200,item["kind"]=="message")
                if "\n" in subject or "\t" in subject:
                    raise ValidationError("Rendered subject must be a single line. Correct the CRM text or use a subject without that placeholder.")
                body=text(render_text(item["body"],context),"Rendered body",4096)
                db.execute("INSERT INTO steps(id,workspace_id,enrollment_id,position,kind,title,delay_hours,due_at,status,subject,body) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(uid(),wid,eid,index,item["kind"],item["title"],item["delay_hours"],(now()+timedelta(hours=item["delay_hours"])).isoformat() if index==0 else None,"Pending",subject,body))
            audit(db,wid,eid,"enrolled","Pinned plan version and CRM contact selected. No message sent.")
        return eid
    except (sqlite3.IntegrityError,psycopg.IntegrityError):
        raise Conflict("A concurrent request already enrolled this contact or destination.") from None


def current_step(db,wid,eid):
    return db.one("SELECT * FROM steps WHERE workspace_id=? AND enrollment_id=? AND status='Pending' ORDER BY position LIMIT 1",(wid,eid))


def event(db,wid,enrollment,kind,origin,note,critical=False):
    cap(db,wid,"events",critical)
    sequence=db.one("SELECT COALESCE(MAX(sequence),0)+1 AS n FROM events WHERE workspace_id=? AND enrollment_id=?",(wid,enrollment["id"]))["n"]
    event_id=uid()
    summary=text(origin+": "+note,"Event summary",1800)
    payload=dict(schema_version=1,source_system="followdesk",source_workspace_id=wid,event_id=event_id,enrollment_id=enrollment["id"],sequence=sequence,opportunity_id=enrollment["opportunity_id"],kind=kind,recorded_at_utc=stamp(),summary=summary)
    payload["digest"]=digest(payload)
    db.execute("INSERT INTO events(id,workspace_id,enrollment_id,sequence,kind,origin,note,payload,created_at) VALUES (?,?,?,?,?,?,?,?,?)",(event_id,wid,enrollment["id"],sequence,kind,origin,note,canonical(payload),stamp()))


def save_draft(db,wid,sid,expected,subject,body):
    subject=text(subject,"Subject",200)
    body=text(body,"Body",4096)
    if "\n" in subject or "\t" in subject: raise ValidationError("Subject must be a single line.")
    with db.transaction():
        lock(db,wid)
        step=record(db,"steps",wid,sid)
        version(step,expected)
        run=record(db,"enrollments",wid,step["enrollment_id"])
        if step["status"]!="Pending" or step["kind"]!="message" or run["status"] not in {"Active","Paused"}: raise Conflict("This message is no longer editable.")
        db.execute("UPDATE steps SET subject=?,body=?,approval=NULL,version=version+1 WHERE workspace_id=? AND id=?",(subject,body,wid,sid))
        audit(db,wid,run["id"],"draft_saved","Message text saved; prior approval invalidated.")


def refresh_context(db,wid,eid,expected,fresh):
    eligible(fresh)
    with db.transaction():
        lock(db,wid)
        run=record(db,"enrollments",wid,eid)
        version(run,expected)
        if run["status"] not in {"Active","Paused"} or fresh["id"]!=run["opportunity_id"] or fresh["contact"]["id"]!=run["contact_id"]:
            raise Conflict("Contact relationship changed. Stop this run and enrol the current contact explicitly.")
        suppressed(db,wid,run["contact_id"],fresh["contact"]["email"])
        destination_guard(db,wid,fresh["contact"]["email"],eid)
        db.execute("UPDATE enrollments SET context=?,address_key=?,version=version+1 WHERE workspace_id=? AND id=?",(canonical(fresh),address_key(fresh["contact"]["email"]),wid,eid))
        db.execute("UPDATE steps SET approval=NULL,version=version+1 WHERE workspace_id=? AND enrollment_id=? AND status='Pending'",(wid,eid))
        audit(db,wid,eid,"context_refreshed","Current CRM context loaded. Review existing message text before approving again.")


def approval_value(step,context):
    return digest(dict(recipient=context["contact"]["email"],subject=step["subject"],body=step["body"],due_at=step["due_at"],context=context_hash(context)))


def actionable(db,wid,step,run,fresh=None):
    if run["status"]!="Active" or step["status"]!="Pending" or current_step(db,wid,run["id"])["id"]!=step["id"]:
        raise Conflict("Only the current step of an active run can execute.")
    if not step["due_at"] or utc_value(step["due_at"])>now(): raise Conflict("This step is not due yet.")
    if fresh is not None:
        eligible(fresh)
        if context_hash(fresh)!=context_hash(json.loads(run["context"])): raise Conflict("CRM context changed. Refresh it and review the draft again.")
    stored=json.loads(run["context"])
    suppressed(db,wid,run["contact_id"],stored["contact"]["email"])


def approve(db,wid,sid,expected,fresh):
    with db.transaction():
        lock(db,wid)
        step=record(db,"steps",wid,sid)
        version(step,expected)
        run=record(db,"enrollments",wid,step["enrollment_id"])
        actionable(db,wid,step,run,fresh)
        if step["kind"]!="message": raise Conflict("Manual tasks do not have message approval.")
        db.execute("UPDATE steps SET approval=?,version=version+1 WHERE workspace_id=? AND id=?",(approval_value(step,fresh),wid,sid))
        audit(db,wid,run["id"],"approved","Exact recipient, rendered content, schedule and checked CRM context reviewed.")


def advance(db,wid,run):
    next_step=current_step(db,wid,run["id"])
    if next_step:
        db.execute("UPDATE steps SET due_at=?,approval=NULL,version=version+1 WHERE workspace_id=? AND id=?",((now()+timedelta(hours=next_step["delay_hours"])).isoformat(),wid,next_step["id"]))
        db.execute("UPDATE enrollments SET version=version+1 WHERE workspace_id=? AND id=?",(wid,run["id"]))
    else:
        db.execute("UPDATE enrollments SET status='Completed',version=version+1 WHERE workspace_id=? AND id=?",(wid,run["id"]))


def deliver(db,wid,sid,expected,fresh):
    with db.transaction():
        lock(db,wid)
        existing=db.one("SELECT * FROM receipts WHERE workspace_id=? AND step_id=?",(wid,sid))
        if existing: return existing["id"]
        step=record(db,"steps",wid,sid)
        version(step,expected)
        run=record(db,"enrollments",wid,step["enrollment_id"])
        actionable(db,wid,step,run,fresh)
        if step["kind"]!="message" or step["approval"]!=approval_value(step,fresh): raise Conflict("Review and approve this exact message before demo delivery.")
        cap(db,wid,"receipts")
        receipt=uid()
        db.execute("INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?)",(receipt,wid,run["id"],sid,fresh["contact"]["email"],step["subject"],step["body"],stamp()))
        db.execute("UPDATE steps SET status='Delivered',version=version+1 WHERE workspace_id=? AND id=?",(wid,sid))
        event(db,wid,run,"demo_delivery","Simulated delivery",f"Message '{step['subject']}' delivered to the demo inbox for {fresh['contact']['email']}. No email was sent.")
        advance(db,wid,run)
        audit(db,wid,run["id"],"delivered","Immutable demo receipt, next step and CRM event committed together.")
        return receipt


def finish_task(db,wid,sid,expected,note,skip=False):
    note=text(note,"Completion or skip reason",1024)
    with db.transaction():
        lock(db,wid)
        step=record(db,"steps",wid,sid)
        version(step,expected)
        run=record(db,"enrollments",wid,step["enrollment_id"])
        actionable(db,wid,step,run)
        if not skip and step["kind"]!="task": raise Conflict("This step is a message; review and deliver it instead.")
        db.execute("UPDATE steps SET status=?,approval=NULL,version=version+1 WHERE workspace_id=? AND id=?",("Skipped" if skip else "Done",wid,sid))
        event(db,wid,run,"skipped" if skip else "manual_task","Reviewer statement",note)
        advance(db,wid,run)
        audit(db,wid,run["id"],"step_finished",note)


OUTCOMES={"synthetic_reply","reviewer_reply","meeting","not_interested","opt_out","invalid_address","out_of_office","stopped"}


def outcome(db,wid,eid,expected,kind,note):
    if kind not in OUTCOMES: raise ValidationError("Choose a listed outcome.")
    note=text(note,"Outcome statement",1024)
    with db.transaction():
        lock(db,wid)
        run=record(db,"enrollments",wid,eid)
        if kind=="out_of_office":
            version(run,expected)
        else:
            # Stopping is monotonic: a just-completed delivery must not swallow
            # an already submitted reply/opt-out. Draft edits remain strict.
            submitted=security.positive_integer(expected)
            if submitted is None or submitted>run["version"]:
                raise Conflict("This outcome has no valid record version. Reload and try again.")
            last=db.one("SELECT kind,note FROM events WHERE workspace_id=? AND enrollment_id=? ORDER BY sequence DESC LIMIT 1",(wid,eid))
            if last and last["kind"]==kind and last["note"]==note:
                return
        stored=json.loads(run["context"])
        affected=[]
        if kind=="opt_out":
            key=address_key(stored["contact"]["email"])
            affected=[other for other in db.all("SELECT * FROM enrollments WHERE workspace_id=? AND status IN ('Active','Paused')",(wid,)) if other["id"]!=eid and (other["contact_id"]==run["contact_id"] or other["address_key"].casefold()==key.casefold())]
        critical=(kind!="out_of_office" and run["status"] in {"Active","Paused"}) or bool(affected)
        if kind=="out_of_office":
            if run["status"]!="Active": raise Conflict("Only an active run can be paused for out-of-office.")
            _pause(db,wid,run)
        else:
            reason="opt_out" if run["stop_reason"]=="opt_out" else kind
            db.execute("UPDATE enrollments SET status='Stopped',stop_reason=?,version=version+1 WHERE workspace_id=? AND id=?",(reason,wid,eid))
            db.execute("UPDATE steps SET status='Cancelled',approval=NULL,version=version+1 WHERE workspace_id=? AND enrollment_id=? AND status='Pending'",(wid,eid))
        if kind in {"opt_out","invalid_address"}:
            keys=[("address",address_key(stored["contact"]["email"]))]
            if kind=="opt_out": keys.append(("contact",run["contact_id"]))
            for key_type,identity in keys:
                db.execute("INSERT INTO suppressions VALUES (?,?,?,?,?) ON CONFLICT(workspace_id,key_type,identity) DO NOTHING",(wid,key_type,identity,kind,stamp()))
        for other in affected:
            db.execute("UPDATE enrollments SET status='Stopped',stop_reason='opt_out',version=version+1 WHERE workspace_id=? AND id=?",(wid,other["id"]))
            db.execute("UPDATE steps SET status='Cancelled',approval=NULL,version=version+1 WHERE workspace_id=? AND enrollment_id=? AND status='Pending'",(wid,other["id"]))
            event(db,wid,other,"opt_out","Reviewer statement","Contact/address opt-out also recorded on an earlier run: "+note,True)
            audit(db,wid,other["id"],"opt_out_propagated","Pending work cancelled due to contact/address opt-out.",True)
        event(db,wid,run,kind,"Synthetic inbox action" if kind=="synthetic_reply" else "Reviewer statement",note,critical)
        audit(db,wid,eid,"outcome",note,critical)


def _pause(db,wid,run):
    step=current_step(db,wid,run["id"])
    if not step: raise Conflict("No pending step to pause.")
    remaining=max(0,int((utc_value(step["due_at"])-now()).total_seconds()))
    db.execute("UPDATE enrollments SET status='Paused',remaining_seconds=?,version=version+1 WHERE workspace_id=? AND id=?",(remaining,wid,run["id"]))
    db.execute("UPDATE steps SET approval=NULL,version=version+1 WHERE workspace_id=? AND id=?",(wid,step["id"]))


def pause_resume(db,wid,eid,expected,note):
    note=text(note,"Pause or resume reason",1024)
    with db.transaction():
        lock(db,wid)
        run=record(db,"enrollments",wid,eid)
        version(run,expected)
        kind="paused" if run["status"]=="Active" else "resumed"
        if run["status"]=="Active": _pause(db,wid,run)
        elif run["status"]=="Paused":
            step=current_step(db,wid,eid)
            db.execute("UPDATE steps SET due_at=?,approval=NULL,version=version+1 WHERE workspace_id=? AND id=?",((now()+timedelta(seconds=run["remaining_seconds"] or 0)).isoformat(),wid,step["id"]))
            db.execute("UPDATE enrollments SET status='Active',remaining_seconds=NULL,version=version+1 WHERE workspace_id=? AND id=?",(wid,eid))
        else: raise Conflict("Only an active or paused run can change pause state.")
        event(db,wid,run,kind,"Reviewer statement",note)
        audit(db,wid,eid,kind,note)


def reschedule(db,wid,sid,expected,due_at,note):
    due=utc_value(due_at)
    if not now()-timedelta(minutes=5)<=due<=now()+timedelta(days=30): raise ValidationError("Choose a due time from now to 30 days ahead.")
    note=text(note,"Reschedule reason",1024)
    with db.transaction():
        lock(db,wid)
        step=record(db,"steps",wid,sid)
        version(step,expected)
        run=record(db,"enrollments",wid,step["enrollment_id"])
        if run["status"]!="Active" or not current_step(db,wid,run["id"]) or current_step(db,wid,run["id"])["id"]!=sid: raise Conflict("Only the current active step can be rescheduled.")
        db.execute("UPDATE steps SET due_at=?,approval=NULL,version=version+1 WHERE workspace_id=? AND id=?",(due.isoformat(),wid,sid))
        db.execute("UPDATE enrollments SET version=version+1 WHERE workspace_id=? AND id=?",(wid,run["id"]))
        audit(db,wid,run["id"],"rescheduled",note)


def report(db,wid):
    runs=db.all("SELECT * FROM enrollments WHERE workspace_id=?",(wid,))
    events=db.all("SELECT * FROM events WHERE workspace_id=? ORDER BY created_at,sequence,id",(wid,))
    return dict(runs=len(runs),active=sum(r["status"]=="Active" for r in runs),paused=sum(r["status"]=="Paused" for r in runs),stopped=sum(r["status"]=="Stopped" for r in runs),completed=sum(r["status"]=="Completed" for r in runs),deliveries=db.one("SELECT COUNT(*) AS n FROM receipts WHERE workspace_id=?",(wid,))["n"],replies=len({e["enrollment_id"] for e in events if e["kind"] in {"synthetic_reply","reviewer_reply"}}),meetings=len({e["enrollment_id"] for e in events if e["kind"]=="meeting"}),pending=sum(e["sync_status"]!="Synced" for e in events),as_of=stamp())


def csv_export(events):
    buffer=io.StringIO(newline="")
    writer=csv.writer(buffer)
    writer.writerow(["Event ID","Run ID","Recorded UTC","Kind","Origin","Statement","CRM sync"])
    for e in events:
        values=[e[k] for k in ("id","enrollment_id","created_at","kind","origin","note","sync_status")]
        writer.writerow(["'"+str(v) if str(v).lstrip().startswith(("=","+","-","@")) or str(v).startswith(("\t","\r","\n")) else str(v) for v in values])
    return "\ufeff"+buffer.getvalue()
