"""Check allowlisted archives without printing private comparison values."""
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json
import re
import time

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parent
TEXT={".py",".js",".mjs",".json",".html",".css",".md",".txt",".toml",".sql",".xml",".csv",".yml",".ps1",".cmd"}
FORBIDDEN_PARTS={"private","instance",".git",".venv",".vercel","node_modules","__pycache__",".pytest_cache"}


def verify():
    # Optional private comparisons stay local and never become archive content.
    forbidden=[b"mail.google.com"+b"/mail/u/0/#"]
    private=WORK/"loopdesk/private/cv-verification.json"
    if private.exists():
        cv=json.loads(private.read_text(encoding="utf-8"))
        forbidden.extend(value.split(":",1)[1].encode() for value in cv.get("links",[]) if value.startswith(("mailto:","tel:")))
    for project in ("loopdesk","scopedesk","followdesk"):
        folder=WORK/project/"instance"
        for name in ("session-secret","vault-key"):
            file=folder/name
            if file.exists() and len(file.read_bytes().strip())>=24:
                forbidden.append(file.read_bytes().strip())
        deployment_secrets=WORK/project/".local/deployment/secrets.json"
        if deployment_secrets.exists():
            private_values=json.loads(deployment_secrets.read_text(encoding="utf-8"))
            forbidden.extend(value.encode() for target in private_values.values() for value in target.values())
    reports=[]
    for filename in ("FollowDesk-Suite-Source.zip","FollowDesk-Suite-Windows-Offline.zip"):
        file=WORK/filename
        checked=0
        with ZipFile(file) as archive:
            assert archive.testzip() is None,"Archive integrity check failed"
            manifest=json.loads(archive.read("SOURCE-MANIFEST.json"))
            for item in manifest:
                raw=archive.read(item["path"])
                assert len(raw)==item["bytes"] and hashlib.sha256(raw).hexdigest()==item["sha256"],"Source manifest mismatch"
                current=WORK/item["path"]
                assert current.is_file() and hashlib.sha256(current.read_bytes()).hexdigest()==item["sha256"],f"Archive does not match current source: {item['path']}"
            for name in archive.namelist():
                path=Path(name)
                assert not path.is_absolute() and ".." not in path.parts,"Unsafe archive path"
                assert not set(path.parts)&FORBIDDEN_PARTS,"Private/runtime directory in archive"
                assert not any(part.startswith(".env") and part!=".env.example" for part in path.parts),"Environment secrets in archive"
                assert path.suffix.lower() not in {".sqlite3",".sqlite",".db",".pem",".key",".pyc"},"Runtime data in archive"
                if path.suffix.lower() in TEXT and "/.local/" not in name:
                    raw=archive.read(name)
                    assert not any(value and value in raw for value in forbidden),f"Private comparison matched in {name}"
                    # Actual private key material has no place in public source.
                    assert not re.search(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",raw),f"Private key marker in {name}"
                    checked+=1
            cold=json.loads(archive.read("OFFLINE-VERIFICATION.json"))
            assert cold["verified"] and cold["installedWithoutNetwork"]
        reports.append(dict(path=str(file),textFilesChecked=checked,manifestFilesVerified=len(manifest),bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    result=dict(verified=True,verifiedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),archives=reports,privateFilesExcluded=True,localKeysExcluded=True,knownPrivateContactComparison=private.exists(),scope="Allowlist, manifest hashes and textual private-data comparison. Binary recordings were reviewed separately; this is not a dependency-advisory or production penetration test.")
    (ROOT/"artifacts/public-release-verification.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__": verify()
