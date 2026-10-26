import hmac
import json
import os
import secrets
import sqlite3
import re
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import click
import psycopg
from flask import Flask,Response,abort,flash,g,redirect,render_template,request,session,url_for
from werkzeug.exceptions import HTTPException,SecurityError
from itsdangerous import URLSafeTimedSerializer,BadSignature,SignatureExpired

from . import services as s,security,crm
from .contract import ContractError,strict_json,canonical
from .db import get_db,migrate


def create_app(config=None):
    root=Path(__file__).resolve().parents[1]
    app=Flask(__name__,static_folder=str(root/"public"/"assets"),static_url_path="/assets")
    production=os.environ.get("APP_ENV")=="production" or bool(os.environ.get("VERCEL"))
    app.config.update(PRODUCTION=production,DATABASE_URL=os.environ.get("FOLLOWDESK_DATABASE_URL",f"sqlite:///{root/'instance'/'followdesk.sqlite3'}"),SECRET_KEY=os.environ.get("FOLLOWDESK_SECRET_KEY"),VAULT_KEY=os.environ.get("FOLLOWDESK_VAULT_KEY"),LOOPDESK_URL=os.environ.get("FOLLOWDESK_LOOPDESK_URL","http://127.0.0.1:5055"),SESSION_COOKIE_NAME="followdesk_session",SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",SESSION_COOKIE_SECURE=production,PERMANENT_SESSION_LIFETIME=timedelta(hours=24),MAX_CONTENT_LENGTH=98304)
    if config: app.config.update(config)
    if app.config["PRODUCTION"]:
        if not app.config["DATABASE_URL"].startswith(("postgres://","postgresql://")):
            raise RuntimeError("Production requires persistent PostgreSQL.")
        if not app.config["VAULT_KEY"]:
            raise RuntimeError("Production requires FOLLOWDESK_VAULT_KEY for encrypted connection storage.")
        from cryptography.fernet import Fernet
        Fernet(app.config["VAULT_KEY"])
    elif not app.config["SECRET_KEY"]:
        folder=root/"instance"
        folder.mkdir(exist_ok=True)
        path=folder/"session-secret"
        try:
            with path.open("x",encoding="utf-8") as stream: stream.write(secrets.token_hex(32))
        except FileExistsError: pass
        app.config["SECRET_KEY"]=path.read_text().strip()
    security.configure(app,"FOLLOWDESK")
    # Five included steps use 30 fields plus plan metadata and CSRF. Their
    # bounded UTF-8 text can expand threefold in URL-encoded forms.
    app.config["MAX_FORM_PARTS"]=40
    if not app.config["PRODUCTION"]:
        key_path=Path(app.config.get("LOCAL_VAULT_FILE",root/"instance"/"vault-key"))
        key_path.parent.mkdir(parents=True,exist_ok=True)
        try:
            with key_path.open("x",encoding="utf-8") as stream: stream.write(secrets.token_hex(32))
        except FileExistsError: pass
        vault_key=key_path.read_text().strip()
        import re
        if not re.fullmatch(r"[a-f0-9]{64}",vault_key): raise RuntimeError("Local vault key is invalid.")
        app.config["LOCAL_VAULT_KEY"]=vault_key
    with app.app_context(): crm.base_url()

    @app.teardown_appcontext
    def close_db(error):
        if "db" in g: g.pop("db").close()

    def csrf_token():
        if "csrf" not in session: session["csrf"]=secrets.token_urlsafe(32)
        return session["csrf"]

    @app.before_request
    def protect():
        if isinstance(request.routing_exception,SecurityError): return Response("Untrusted request host.\n",400)
        if request.method=="POST":
            security.check_origin()
            token=request.form.get("csrf_token","")
            if not session.get("csrf") or not hmac.compare_digest(token.encode(),session["csrf"].encode()): abort(400,"This form expired or has an invalid security token. Reload and try again.")
        if request.endpoint not in {"landing","demo","static","health"}:
            workspace=security.active_workspace(get_db(),session.get("workspace_id"),s.stamp())
            if not workspace:
                session.pop("workspace_id",None)
                flash("Start a fresh demo. Workspaces expire after 24 hours.","info")
                return redirect(url_for("landing"),303)
            g.wid=workspace["id"]
            g.workspace=workspace
        if request.method=="POST" or getattr(g,"wid",None): security.enforce_rate_limits(get_db(),getattr(g,"wid",None),demo=request.endpoint=="demo")

    @app.after_request
    def headers(response):
        response.headers.update({"Cache-Control":"no-store","X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY","Referrer-Policy":"same-origin","Permissions-Policy":"camera=(), microphone=(), geolocation=()","Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"})
        if app.config["PRODUCTION"]: response.headers["Strict-Transport-Security"]="max-age=31536000"
        return response

    @app.context_processor
    def common():
        return dict(csrf_token=csrf_token,workspace=getattr(g,"workspace",None),crm_url=app.config["LOOPDESK_URL"],now=s.stamp())

    @app.template_filter("dubai")
    def dubai(value):
        return s.utc_value(value).astimezone(ZoneInfo("Asia/Dubai")).strftime("%d %b %Y · %H:%M") if value else "After previous step"

    @app.cli.command("migrate")
    def migrate_command():
        if app.config["DATABASE_URL"].startswith("sqlite:///"): Path(app.config["DATABASE_URL"].removeprefix("sqlite:///")).parent.mkdir(parents=True,exist_ok=True)
        migrate(get_db())
        click.echo("FollowDesk migrations applied.")

    @app.get("/health")
    def health():
        ready=get_db().one("SELECT version FROM schema_migrations WHERE version='001_initial'")
        return {"status":"ok" if ready else "migration_required","application":"followdesk"},200 if ready else 503

    @app.get("/")
    def landing(): return render_template("landing.html")

    @app.post("/demo")
    def demo():
        previous=session.get("workspace_id")
        active=security.active_workspace(get_db(),previous,s.stamp())
        if active and request.form.get("reset")!="1": return redirect(url_for("queue"),303)
        wid=s.create_workspace(get_db())
        revocation_warning=False
        if active:
            previous_connection=get_db().one("SELECT status FROM connections WHERE workspace_id=?",(previous,))
            if previous_connection and previous_connection["status"]=="Connected":
                revocation_warning=bool(crm.disconnect(get_db(),previous))
            security.revoke_workspace(get_db(),previous,s.stamp())
        session.clear()
        session["workspace_id"]=wid
        session.permanent=True
        if revocation_warning: flash("Previous workspace revoked locally. LoopDesk revocation was unconfirmed; revoke there or wait for its one-hour expiry.","info")
        return redirect(url_for("queue"),303)

    @app.get("/queue")
    def queue():
        rows=get_db().all("SELECT * FROM enrollments WHERE workspace_id=? ORDER BY created_at DESC,id",(g.wid,))
        for row in rows:
            row["context"]=json.loads(row["context"])
            row["step"]=s.current_step(get_db(),g.wid,row["id"])
        return render_template("queue.html",runs=rows,metrics=s.report(get_db(),g.wid),connection=get_db().one("SELECT source_workspace_id,expires_at,status FROM connections WHERE workspace_id=?",(g.wid,)))

    @app.route("/connection",methods=["GET","POST"])
    def connection():
        if request.method=="POST":
            if request.form.get("action")=="disconnect":
                error=crm.disconnect(get_db(),g.wid)
                flash("Disconnected locally. "+("LoopDesk revocation is unconfirmed; revoke there or wait for expiry." if error else "LoopDesk access revoked."),"info")
            else:
                crm.pair(get_db(),g.wid,request.form.get("pairing_code",""))
                flash("Connected to this LoopDesk demo with read and append-only access.","success")
            return redirect(url_for("connection"),303)
        return render_template("connection.html",connection=get_db().one("SELECT source_workspace_id,expires_at,status FROM connections WHERE workspace_id=?",(g.wid,)))

    @app.route("/enroll",methods=["GET","POST"])
    def enroll():
        plans=get_db().all("SELECT * FROM plan_versions WHERE workspace_id=? ORDER BY name,revision DESC",(g.wid,))
        error=None
        options=[]
        try:
            options=crm.call(get_db(),g.wid,"/opportunities")["items"]
            if request.method=="POST":
                context=crm.fresh_context(get_db(),g.wid,request.form.get("opportunity_id",""))
                conn=crm.connection(get_db(),g.wid)
                eid=s.enroll(get_db(),g.wid,request.form.get("plan_id",""),context,conn["source_workspace_id"])
                flash("Run created. Review the first draft; enrolment never sends a message.","success")
                return redirect(url_for("run_detail",eid=eid),303)
        except (crm.CRMError,ContractError) as exc:
            error=str(exc)
        return render_template("enroll.html",plans=plans,options=options,error=error),422 if error else 200

    def detail(eid,error=None,status=200,draft=None):
        run=s.record(get_db(),"enrollments",g.wid,eid)
        context=json.loads(run["context"])
        steps=get_db().all("SELECT * FROM steps WHERE workspace_id=? AND enrollment_id=? ORDER BY position",(g.wid,eid))
        plan=s.record(get_db(),"plan_versions",g.wid,run["plan_id"])
        return render_template("run.html",run=run,context=context,steps=steps,current=s.current_step(get_db(),g.wid,eid),events=get_db().all("SELECT * FROM events WHERE workspace_id=? AND enrollment_id=? ORDER BY sequence DESC",(g.wid,eid)),plan=plan,error=error,draft=draft),status

    @app.get("/runs/<eid>")
    def run_detail(eid): return detail(eid)

    @app.post("/runs/<eid>/action")
    def run_action(eid):
        run=s.record(get_db(),"enrollments",g.wid,eid)
        action=request.form.get("action")
        try:
            if action=="refresh": s.refresh_context(get_db(),g.wid,eid,request.form.get("version"),crm.fresh_context(get_db(),g.wid,run["opportunity_id"]))
            elif action=="pause": s.pause_resume(get_db(),g.wid,eid,request.form.get("version"),request.form.get("note",""))
            elif action=="outcome": s.outcome(get_db(),g.wid,eid,request.form.get("version"),request.form.get("kind"),request.form.get("note",""))
            else: abort(400,"Unknown run action.")
            flash("Run updated. History remains available; CRM sync is a separate action.","success")
        except (ContractError,crm.CRMError) as exc:
            return detail(eid,str(exc),409 if isinstance(exc,s.Conflict) else 422)
        return redirect(url_for("run_detail",eid=eid),303)

    @app.post("/steps/<sid>/action")
    def step_action(sid):
        step=s.record(get_db(),"steps",g.wid,sid)
        run=s.record(get_db(),"enrollments",g.wid,step["enrollment_id"])
        action=request.form.get("action")
        expected=request.form.get("version")
        try:
            if action=="draft": s.save_draft(get_db(),g.wid,sid,expected,request.form.get("subject",""),request.form.get("body",""))
            elif action=="approve":
                fresh=crm.fresh_context(get_db(),g.wid,run["opportunity_id"])
                serializer=URLSafeTimedSerializer(app.secret_key,salt="followdesk-message-review-v1")
                try: proof=serializer.loads(request.form.get("review_token",""),max_age=600)
                except (BadSignature,SignatureExpired): raise s.Conflict("Open the saved-message review and confirm it before approval.") from None
                if proof!={"wid":g.wid,"sid":sid,"version":step["version"],"hash":s.approval_value(step,fresh)}:
                    raise s.Conflict("This review snapshot changed. Open the saved-message review again.")
                s.approve(get_db(),g.wid,sid,expected,fresh)
            elif action=="deliver":
                receipt=s.deliver(get_db(),g.wid,sid,expected,crm.fresh_context(get_db(),g.wid,run["opportunity_id"]))
                flash("Delivered to the simulated inbox. No email was sent. CRM history is pending sync.","success")
                return redirect(url_for("mail",rid=receipt),303)
            elif action in {"task","skip"}: s.finish_task(get_db(),g.wid,sid,expected,request.form.get("note",""),action=="skip")
            elif action=="reschedule":
                # The UI explicitly labels this wall-clock value as Dubai time.
                from datetime import datetime,timezone
                try: due=datetime.strptime(request.form.get("due_at",""),"%Y-%m-%dT%H:%M").replace(tzinfo=ZoneInfo("Asia/Dubai")).astimezone(timezone.utc).isoformat()
                except ValueError: raise s.ValidationError("Choose a valid Dubai date and time.") from None
                s.reschedule(get_db(),g.wid,sid,expected,due,request.form.get("note",""))
            else: abort(400,"Unknown step action.")
            flash("Step updated.","success")
        except (ContractError,crm.CRMError) as exc:
            return detail(run["id"],str(exc),409 if isinstance(exc,s.Conflict) else 422,dict(request.form) if action=="draft" else None)
        return redirect(url_for("run_detail",eid=run["id"]),303)

    @app.get("/steps/<sid>/review")
    def review_message(sid):
        step=s.record(get_db(),"steps",g.wid,sid)
        run=s.record(get_db(),"enrollments",g.wid,step["enrollment_id"])
        try:
            fresh=crm.fresh_context(get_db(),g.wid,run["opportunity_id"])
            s.actionable(get_db(),g.wid,step,run,fresh)
            if step["kind"]!="message": raise s.Conflict("This step is a manual task.")
            serializer=URLSafeTimedSerializer(app.secret_key,salt="followdesk-message-review-v1")
            proof=serializer.dumps({"wid":g.wid,"sid":sid,"version":step["version"],"hash":s.approval_value(step,fresh)})
            return render_template("review.html",step=step,run=run,context=fresh,review_token=proof)
        except (ContractError,crm.CRMError) as exc:
            return detail(run["id"],str(exc),409 if isinstance(exc,s.Conflict) else 422)

    @app.get("/inbox")
    def inbox(): return render_template("inbox.html",receipts=get_db().all("SELECT * FROM receipts WHERE workspace_id=? ORDER BY created_at DESC,id",(g.wid,)))

    @app.get("/inbox/<rid>")
    def mail(rid):
        receipt=s.record(get_db(),"receipts",g.wid,rid)
        return render_template("mail.html",receipt=receipt,run=s.record(get_db(),"enrollments",g.wid,receipt["enrollment_id"]))

    @app.route("/plans",methods=["GET","POST"])
    def plans():
        if request.method=="POST":
            steps=[]
            for index in range(5):
                if request.form.get(f"include_{index}")!="1": continue
                delay=request.form.get(f"delay_{index}","")
                if not re.fullmatch(r"[0-9]{1,3}",delay): raise s.ValidationError("Use a whole delay from 0 to 720 hours.")
                steps.append(dict(kind=request.form.get(f"kind_{index}",""),title=request.form.get(f"title_{index}",""),delay_hours=int(delay),subject=request.form.get(f"subject_{index}",""),body=request.form.get(f"body_{index}","")))
            s.publish_plan(get_db(),g.wid,request.form.get("name",""),steps,request.form.get("family") or None)
            flash("New immutable plan version published. Existing runs are unchanged.","success")
            return redirect(url_for("plans"),303)
        rows=get_db().all("SELECT * FROM plan_versions WHERE workspace_id=? ORDER BY name,revision DESC",(g.wid,))
        for row in rows:
            row["editable_steps"]=json.loads(row["steps"])
            row["editable_steps"] += [None]*(5-len(row["editable_steps"]))
        return render_template("plans.html",plans=rows)

    @app.get("/reports")
    def reports(): return render_template("reports.html",metrics=s.report(get_db(),g.wid),events=get_db().all("SELECT * FROM events WHERE workspace_id=? ORDER BY created_at DESC,sequence DESC,id",(g.wid,)))

    @app.get("/reports.csv")
    def export():
        return Response(s.csv_export(get_db().all("SELECT * FROM events WHERE workspace_id=? ORDER BY created_at,sequence,id",(g.wid,))),content_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=followdesk-demo-events.csv"})

    @app.post("/sync")
    def sync():
        try: flash(f"Confirmed {crm.sync(get_db(),g.wid)} CRM history events. Delivery was not repeated.","success")
        except crm.CRMError as exc: flash(str(exc)+" Local events remain pending; retry after recovery.","error")
        return redirect(url_for("reports"),303)

    @app.errorhandler(ContractError)
    @app.errorhandler(crm.CRMError)
    def invalid(error): return render_template("error.html",code=409 if isinstance(error,s.Conflict) else 422,message=str(error)),409 if isinstance(error,s.Conflict) else 422

    @app.errorhandler(HTTPException)
    def http_error(error):
        response=error.get_response()
        response.set_data(render_template("error.html",code=error.code,message=error.description))
        response.content_type="text/html; charset=utf-8"
        return response

    def unavailable(error):
        app.logger.warning("Workspace database unavailable (%s)",type(error).__name__)
        return render_template("error.html",code=503,message="The database is temporarily unavailable. Please try again shortly."),503,{"Retry-After":"30"}
    for kind in (sqlite3.OperationalError,psycopg.OperationalError,psycopg.errors.UndefinedTable): app.register_error_handler(kind,unavailable)
    return app
