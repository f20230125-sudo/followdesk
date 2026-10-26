"""Fixed-origin, bounded server-to-server client. Never follows redirects."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from flask import current_app
from .contract import ContractError, canonical, strict_json, identifier
from .vault import open_token, seal


class CRMError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def base_url():
    try:
        value=current_app.config["LOOPDESK_URL"].rstrip("/")
        parsed=urlsplit(value)
        local=(parsed.hostname in {"127.0.0.1","localhost","::1"})
        if not parsed.hostname or parsed.port==0 or any(ord(c)<=32 for c in value) or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path or parsed.scheme not in {"http","https"} or (parsed.scheme != "https" and (current_app.config["PRODUCTION"] or not local)):
            raise ValueError()
    except (AttributeError,TypeError,ValueError):
        raise CRMError("Configure a fixed HTTPS LoopDesk origin, or loopback HTTP for local use.") from None
    return value


def request_api(path, method="GET", token=None, payload=None):
    # Paths are built internally from verified IDs, never supplied by a form.
    url=base_url()+"/api/followdesk/v1"+path
    headers={"Accept":"application/json"}
    data=None
    if payload is not None:
        data=canonical(payload).encode()
        headers["Content-Type"]="application/json"
    if token:
        headers["Authorization"]="Bearer "+token
    try:
        opener=build_opener(ProxyHandler({}),NoRedirect())
        with opener.open(Request(url,data=data,headers=headers,method=method),timeout=4) as response:
            if response.headers.get_content_type() != "application/json":
                raise CRMError("LoopDesk did not return the expected integration response.")
            return strict_json(response.read(262145),262144)
    except HTTPError as exc:
        if exc.code in (401,403):
            raise CRMError("LoopDesk access expired or was revoked. Create a fresh pairing code.") from None
        raise CRMError(f"LoopDesk could not accept this request (HTTP {exc.code}). No CRM field was overwritten.") from None
    except (URLError,TimeoutError,OSError,ContractError) as exc:
        raise CRMError("LoopDesk is unavailable or returned an invalid response. Pending work is retained.") from None


def connection(db,wid):
    row=db.one("SELECT * FROM connections WHERE workspace_id=?",(wid,))
    if not row or row["status"] != "Connected":
        raise CRMError("Connect this workspace to LoopDesk first.")
    return row


def pair(db,wid,code):
    from . import services as s
    result=request_api("/exchange","POST",payload={"pairing_code":code,"client_workspace_id":wid})
    try:
        identifier(result["source_workspace_id"])
        previous=db.one("SELECT source_workspace_id FROM connections WHERE workspace_id=?",(wid,))
        if previous and previous["source_workspace_id"]!=result["source_workspace_id"] and db.one("SELECT id FROM enrollments WHERE workspace_id=? LIMIT 1",(wid,)):
            try: request_api("/revoke","POST",result["access_token"],{})
            except CRMError: pass
            raise CRMError("Existing runs belong to another CRM workspace. Start a fresh FollowDesk demo to connect elsewhere; the new grant was not retained.")
        encrypted=seal(result["access_token"])
        expires=s.utc_value(result["expires_at"]).isoformat()
    except (KeyError,TypeError,ValueError,RuntimeError) as exc:
        raise CRMError("The connection could not be stored securely. Create a fresh code and reconnect.") from None
    with db.transaction():
        s.lock(db,wid)
        previous=db.one("SELECT * FROM connections WHERE workspace_id=?",(wid,))
        if previous and previous["source_workspace_id"] != result["source_workspace_id"] and db.one("SELECT id FROM enrollments WHERE workspace_id=? LIMIT 1",(wid,)):
            raise CRMError("Existing runs belong to another CRM workspace. Start a fresh FollowDesk demo to connect elsewhere.")
        db.execute("INSERT INTO connections VALUES (?,?,?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET source_workspace_id=excluded.source_workspace_id,encrypted_token=excluded.encrypted_token,expires_at=excluded.expires_at,status='Connected'",(wid,result["source_workspace_id"],encrypted,expires,"Connected"))
        s.audit(db,wid,None,"connected","Scoped LoopDesk connection established.")


def call(db,wid,path,method="GET",payload=None):
    row=connection(db,wid)
    from .services import now, utc_value
    if utc_value(row["expires_at"]) <= now():
        raise CRMError("Connection expired. Reconnect from LoopDesk; history stays intact.")
    try:
        token=open_token(row["encrypted_token"])
    except Exception:
        raise CRMError("Connection cannot be decrypted. Reconnect from LoopDesk.") from None
    return request_api(path,method,token,payload)


def fresh_context(db,wid,oid):
    from .services import validate_context
    result=call(db,wid,"/opportunities/"+identifier(oid))
    try:
        return validate_context(result["context"])
    except (KeyError,TypeError,ValueError):
        raise CRMError("CRM context is incomplete or invalid. No delivery was made.") from None


def sync(db,wid):
    from . import services as s
    pending=db.all("SELECT * FROM events WHERE workspace_id=? AND sync_status<>'Synced' ORDER BY created_at,enrollment_id,sequence LIMIT 3",(wid,))
    count=0
    for event in pending:
        result=call(db,wid,"/events","POST",json.loads(event["payload"]))
        try:
            receipt=identifier(result["receipt_id"])
        except (KeyError,TypeError,ValueError):
            raise CRMError("CRM receipt is invalid. The event remains pending.") from None
        with db.transaction():
            s.lock(db,wid)
            db.execute("UPDATE events SET sync_status='Synced',crm_receipt=? WHERE workspace_id=? AND id=?",(receipt,wid,event["id"]))
        count+=1
    return count


def disconnect(db,wid):
    from . import services as s
    error=None
    try:
        call(db,wid,"/revoke","POST",{})
    except CRMError as exc:
        error=str(exc)
    with db.transaction():
        s.lock(db,wid)
        db.execute("UPDATE connections SET status='Disconnected',encrypted_token='' WHERE workspace_id=?",(wid,))
        s.audit(db,wid,None,"disconnected","Local connection disabled. "+("Issuer revocation unconfirmed; revoke in LoopDesk or wait for expiry." if error else "Issuer access revoked."),True)
    return error
