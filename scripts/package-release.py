"""Allowlisted three-app local checkpoint, verified from a clean D: extraction."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from email.parser import Parser
import hashlib
import http.cookiejar
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parent
PROJECTS=("loopdesk","scopedesk","followdesk")
EXCLUDED={".git",".venv",".local","instance","private","__pycache__",".pytest_cache",".vercel","node_modules","recording-raw"}


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files(project):
    singles={"app.py","requirements.txt","requirements-dev.txt","pyproject.toml","README.md","LICENSE","vercel.json",".gitignore",".vercelignore",".env.example","Start-ScopeDesk.cmd","Start-LoopDesk.cmd","Start-FollowDesk.cmd"}
    folders={project.name,"public","migrations","tests","scripts","docs","examples",".github"}
    for file in sorted(project.rglob("*")):
        rel=file.relative_to(project)
        if not file.is_file() or set(rel.parts)&EXCLUDED: continue
        if len(rel.parts)==1 and rel.name in singles: yield file
        elif rel.parts[0] in folders and file.suffix in {".py",".html",".css",".js",".mjs",".sql",".json",".md",".txt",".csv",".svg",".yml",".ps1"}: yield file
        elif rel.parts[0]=="artifacts" and len(rel.parts)==2 and file.suffix in {".json",".xml",".png",".webm",".html",".csv",".txt"} and not file.name.startswith(("initial-","browser-failure")) and file.name not in {"offline-verification.json","source-manifest.json","public-release-verification.json"}: yield file


def wheel_files(project):
    expected={}
    for filename in ("requirements.txt","requirements-dev.txt"):
        for line in (project/filename).read_text().splitlines():
            if "==" in line and not line.lstrip().startswith("#"):
                package,version=line.split(";",1)[0].strip().split("==")
                expected[package.lower().replace("-","_")]=version
    found={}
    for file in (ROOT/".local/wheels").glob("*.whl"):
        with ZipFile(file) as z:
            metadata=Parser().parsestr(z.read(next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))).decode())
            name=metadata["Name"].lower().replace("-","_")
            if expected.get(name)==metadata["Version"]: found[name]=file
    assert not set(expected)-set(found),f"Missing pinned wheels for {project.name}"
    return sorted(found.values())


def environment(project):
    env=os.environ.copy()
    for key in ("APP_ENV","VERCEL","DATABASE_URL","SECRET_KEY","SCOPEDESK_DATABASE_URL","SCOPEDESK_SECRET_KEY","FOLLOWDESK_DATABASE_URL","FOLLOWDESK_SECRET_KEY","FOLLOWDESK_VAULT_KEY","FOLLOWDESK_TEST_DATABASE_URL","LOOPDESK_TEST_DATABASE_URL","SCOPEDESK_TEST_DATABASE_URL"):
        env.pop(key,None)
    for name,tail in {"TEMP":"temp","TMP":"temp","TMPDIR":"temp","PIP_CACHE_DIR":"pip-cache","PYTHONPYCACHEPREFIX":"pycache","npm_config_cache":"npm-cache","XDG_CACHE_HOME":"cache"}.items():
        folder=project/".local"/tail
        folder.mkdir(parents=True,exist_ok=True)
        env[name]=str(folder)
    return env


def build():
    source=WORK/"FollowDesk-Suite-Source.zip"
    offline=WORK/"FollowDesk-Suite-Windows-Offline.zip"
    manifest=[]
    with ZipFile(source,"w",ZIP_DEFLATED) as z:
        for name in PROJECTS:
            project=WORK/name
            for file in source_files(project):
                relative=(Path(name)/file.relative_to(project)).as_posix()
                z.write(file,relative)
                manifest.append(dict(path=relative,bytes=file.stat().st_size,sha256=sha(file)))
        security_files={"README.md","probe.py","fuzz.py","serve.py","browser-security.mjs","baseline.json","replay-baseline.json","retest.json","retest-followdesk-integration.json","fuzz-results.json","browser-security.json","loopdesk-hostile-history.png","scopedesk-hostile-brief.png"}
        for name in sorted(security_files):
            file=WORK/"security-review"/name
            if not file.is_file(): continue
            relative="security-review/"+name
            z.write(file,relative)
            manifest.append(dict(path=relative,bytes=file.stat().st_size,sha256=sha(file)))
        z.writestr("SOURCE-MANIFEST.json",json.dumps(manifest,indent=2))
        z.writestr("START-HERE.txt","Local software portfolio checkpoint — 26 October 2026\n\nExtract to D:. Requires Windows x64 / Python 3.14 and Node.js 24 already installed.\nOpen loopdesk/Start-LoopDesk.cmd (5055), scopedesk/Start-ScopeDesk.cmd (5058), and followdesk/Start-FollowDesk.cmd (5059).\nFollow the FollowDesk README to pair an existing LoopDesk demo and execute reviewed simulated outreach.\nNo real email is sent. No publication or application submission is performed.\nPostgreSQL and Linux/hosted HTTPS remain unverified. Production Fernet is tested on Windows.\n")
    with ZipFile(source) as src,ZipFile(offline,"w",ZIP_DEFLATED) as dest:
        for name in src.namelist(): dest.writestr(name,src.read(name))
        for name in PROJECTS:
            for wheel in wheel_files(WORK/name): dest.write(wheel,f"{name}/.local/wheels/{wheel.name}")
    for file in (source,offline):
        with ZipFile(file) as z:
            assert z.testzip() is None
            for name in z.namelist():
                parts=set(Path(name).parts)
                assert not parts&{p for p in EXCLUDED if p!=".local"}
                if ".local" in parts: assert "/.local/wheels/" in name and name.endswith(".whl")
    return source,offline


def csrf(html): return re.search(r'name="csrf_token" value="([^"]+)"',html)[1]
def version(html): return re.search(r'name="version" value="(\d+)"',html)[1]


def verify(archive):
    folder=ROOT/".local"/("offline-checkpoint-"+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    with ZipFile(archive) as z:
        for name in z.namelist(): assert (folder/name).resolve().is_relative_to(folder.resolve())
        z.extractall(folder)
    ports={}
    for name in PROJECTS:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0));ports[name]=sock.getsockname()[1]
    processes=[]
    try:
        for name in PROJECTS:
            project=folder/name
            env=environment(project)
            result=subprocess.run([sys.executable,"-m","venv",str(project/".venv")],env=env,capture_output=True,text=True)
            assert result.returncode==0,"Clean environment creation failed"
            python=project/".venv/Scripts/python.exe"
            result=subprocess.run([str(python),"-m","pip","install","--no-index","--find-links",str(project/".local/wheels"),"-r","requirements-dev.txt"],cwd=project,env=env,capture_output=True,text=True)
            (project/".local/install.log").write_text(result.stdout+result.stderr,encoding="utf-8")
            assert result.returncode==0,f"Offline dependency installation failed for {name}"
            if name=="followdesk":
                # Verify the real production cipher from the clean installation,
                # without opening a database or printing generated key material.
                probe="import secrets\nfrom cryptography.fernet import Fernet\nfrom followdesk import create_app,vault\napp=create_app(dict(PRODUCTION=True,DATABASE_URL='postgresql://unused.invalid/not_connected',SECRET_KEY=secrets.token_hex(32),VAULT_KEY=Fernet.generate_key(),TRUSTED_HOSTS=['follow.example'],LOOPDESK_URL='https://crm.example'))\nwith app.app_context():\n token=vault.seal('fictional-cold-install-token')\n assert token.startswith('fernet:') and vault.open_token(token)=='fictional-cold-install-token'\n"
                result=subprocess.run([str(python),"-c",probe],cwd=project,env=env,capture_output=True,text=True)
                assert result.returncode==0,"Production vault failed in the clean offline installation"
            env["FOLLOWDESK_LOOPDESK_URL"]=f"http://127.0.0.1:{ports['loopdesk']}"
            result=subprocess.run([str(python),"-m","flask","--app","app","migrate"],cwd=project,env=env,capture_output=True,text=True)
            assert result.returncode==0,f"Migration failed for {name}"
            log=(project/".local/server.log").open("w",encoding="utf-8")
            nonce=uuid.uuid4().hex
            script="from app import app\noriginal=app.view_functions['health']\ndef tagged_health():\n response=app.make_response(original())\n response.headers['X-Checkpoint-Instance']="+repr(nonce)+"\n return response\napp.view_functions['health']=tagged_health\napp.run(host='127.0.0.1',port="+str(ports[name])+",debug=False)\n"
            proc=subprocess.Popen([str(python),"-c",script],cwd=project,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
            processes.append((proc,log))
            for attempt in range(100):
                assert proc.poll() is None,f"Extracted {name} exited"
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{ports[name]}/health",timeout=1) as response:
                        assert response.headers.get("X-Checkpoint-Instance")==nonce
                        break
                except OSError: time.sleep(.1)
            else: raise AssertionError(f"{name} did not start")
        jar=http.cookiejar.CookieJar()
        opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        urls={name:f"http://127.0.0.1:{port}" for name,port in ports.items()}
        def get(url): return opener.open(url,timeout=15).read().decode()
        def post(url,data): return opener.open(urllib.request.Request(url,data=urllib.parse.urlencode(data).encode()),timeout=15)
        sc,lp,fl=urls["scopedesk"],urls["loopdesk"],urls["followdesk"]
        cases=post(sc+"/demo",dict(csrf_token=csrf(get(sc)))).read().decode()
        cards=re.findall(r'<a class="case-card" href="([^"]+)"',cases)
        valid=next(url for url in cards if "Reuse equipment, destroy embedded media" in get(sc+url))
        case=get(sc+valid)
        review=post(sc+valid+"/review",dict(csrf_token=csrf(case),version=version(case))).read().decode()
        assert "Reviewed · Revision 1" in review
        raw=opener.open(sc+valid+"/handoff/1.json").read()
        post(lp+"/demo",dict(csrf_token=csrf(get(lp)))).read()
        upload=get(lp+"/scope-import")
        boundary="Checkpoint"+uuid.uuid4().hex
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="csrf_token"\r\n\r\n{csrf(upload)}\r\n--{boundary}\r\nContent-Disposition: form-data; name="handoff"; filename="scope.json"\r\nContent-Type: application/json\r\n\r\n').encode()+raw+f'\r\n--{boundary}--\r\n'.encode()
        response=opener.open(urllib.request.Request(lp+"/scope-import",data=body,headers={"Content-Type":"multipart/form-data; boundary="+boundary}),timeout=15)
        preview_url=response.url;preview=response.read().decode()
        org=re.search(r'<option value="([^"]+)">Cedar Circuit</option>',preview)[1]
        contact=re.search(r'<option value="([^"]+)" data-organisation="'+org+r'">',preview)[1]
        fields=dict(csrf_token=csrf(preview),organisation_id=org,contact_id=contact,owner="Maya (demo)")
        response=post(preview_url,fields);opportunity=response.url;response.read()
        assert post(preview_url,fields).url==opportunity
        settings=get(lp+"/integrations/followdesk")
        issued=post(lp+"/integrations/followdesk",dict(csrf_token=csrf(settings),action="pair")).read().decode()
        code=re.search(r'id="pair-code" value="([^"]+)"',issued)[1]
        post(fl+"/demo",dict(csrf_token=csrf(get(fl)))).read()
        conn=get(fl+"/connection")
        paired=post(fl+"/connection",dict(csrf_token=csrf(conn),pairing_code=code)).read().decode()
        assert "Connected to this LoopDesk demo" in paired
        selection=get(fl+"/enroll")
        plan=re.search(r'<option value="([^"]+)">Reviewed scope next discussion · v1</option>',selection)[1]
        response=post(fl+"/enroll",dict(csrf_token=csrf(selection),plan_id=plan,opportunity_id=opportunity.rsplit("/",1)[1]))
        run_url=response.url;run=response.read().decode()
        review_path=re.search(r'href="(/steps/[^\"]+/review)"',run)[1]
        saved=get(fl+review_path)
        proof=re.search(r'name="review_token" value="([^"]+)"',saved)[1]
        sid=review_path.split("/")[2]
        reviewed=post(fl+f"/steps/{sid}/action",dict(csrf_token=csrf(saved),version=version(saved),review_token=proof,action="approve")).read().decode()
        delivery_version=re.search(r'data-deliver[^>]*',reviewed)
        # Approval is the only step edit so far: its stored version advanced once.
        response=post(fl+f"/steps/{sid}/action",dict(csrf_token=csrf(reviewed),version=int(version(saved))+1,action="deliver"))
        receipt_url=response.url;receipt=response.read().decode()
        assert "/inbox/" in receipt_url and "NO EMAIL SENT" in receipt
        response=post(fl+f"/steps/{sid}/action",dict(csrf_token=csrf(reviewed),version=int(version(saved))+1,action="deliver"))
        assert response.url==receipt_url
        reply=post(fl+f"/runs/{run_url.rsplit('/',1)[1]}/action",dict(csrf_token=csrf(receipt),version=version(receipt),action="outcome",kind="synthetic_reply",note="Fictional reply in clean offline package.")).read().decode()
        assert "Stopped · synthetic reply" in reply and "Cancelled" in reply
        reports=get(fl+"/reports")
        synced=post(fl+"/sync",dict(csrf_token=csrf(reports))).read().decode()
        assert "Confirmed 2 CRM history events" in synced
        repeat=post(fl+"/sync",dict(csrf_token=csrf(synced))).read().decode()
        assert "Confirmed 0 CRM history events" in repeat
        detail=get(opportunity)
        assert detail.count("FollowDesk · ")==2 and "Not estimated" in detail
        assert {cookie.name for cookie in jar}=={"session","scopedesk_session","followdesk_session"}
        return dict(verified=True,python=sys.version.split()[0],platform=sys.platform,cleanVirtualEnvironments=3,installedWithoutNetwork=True,healthEndpoints=3,childInstanceIdentityVerified=True,reviewedScopeExport=True,realScopeImport=True,realPairingAndEncryptedGrant=True,exactMessageReview=True,simulatedDelivery=True,repeatDeliverySameReceipt=True,replyCancelsPending=True,crmSyncEvents=2,repeatedSyncNoDuplicates=True,separateCookies=3,generatedFilesUnder=str(folder),postgres="not run",hosted="not run")
    finally:
        for proc,log in processes:
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill();proc.wait()
            log.close()


def main():
    for name in PROJECTS:
        suites=ET.parse(WORK/name/"artifacts/pytest-sqlite.xml").getroot().findall("testsuite")
        assert suites and all(int(x.attrib["failures"])==int(x.attrib["errors"])==0 for x in suites)
    source,offline=build()
    verification=verify(offline)
    verification["productionVaultColdInstall"]=True
    verification["verifiedAt"]=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    for archive in (source,offline):
        with ZipFile(archive,"a",ZIP_DEFLATED) as z: z.writestr("OFFLINE-VERIFICATION.json",json.dumps(verification,indent=2))
    report=dict(kind="local-preparation-checkpoint",published=False,source=dict(path=str(source),bytes=source.stat().st_size,sha256=sha(source)),offline=dict(path=str(offline),bytes=offline.stat().st_size,sha256=sha(offline)),verification=verification)
    (ROOT/"artifacts/offline-verification.json").write_text(json.dumps(verification,indent=2),encoding="utf-8")
    (WORK/"FollowDesk-Release.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__": main()
