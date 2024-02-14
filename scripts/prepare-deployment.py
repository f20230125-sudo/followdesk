"""Prepare an allowlisted Vercel payload, without secrets or network actions."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def prepare(project="followdesk",target="preview"):
    paths=[ROOT/name for name in ("app.py","pyproject.toml","requirements.txt","vercel.json")]
    for folder in ("followdesk","migrations","public"):
        paths.extend(p for p in (ROOT/folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix in {".py",".html",".css",".js",".mjs",".svg",".sql"})
    files=[]
    manifest=[]
    combined=hashlib.sha256()
    for path in sorted(paths):
        relative=path.relative_to(ROOT).as_posix()
        raw=path.read_bytes()
        combined.update(relative.encode()+b"\0"+raw)
        files.append(dict(file=relative,data=base64.b64encode(raw).decode(),encoding="base64"))
        manifest.append(dict(path=relative,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    fingerprint=combined.hexdigest()
    payload=dict(name="followdesk",project=project,target=target,files=files,projectSettings=dict(framework="flask"),meta=dict(followdeskSourceSha256=fingerprint))
    folder=ROOT/".local/deployment"
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"runtime-payload.json").write_text(json.dumps(payload),encoding="utf-8")
    (folder/"manifest.json").write_text(json.dumps(dict(sent=False,project=project,target=target,sourceSha256=fingerprint,files=manifest),indent=2),encoding="utf-8")
    return dict(sent=False,files=len(files),bytes=sum(p["bytes"] for p in manifest),sourceSha256=fingerprint,payload=".local/deployment/runtime-payload.json")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",default="followdesk")
    parser.add_argument("--target",choices=["preview","production"],default="preview")
    args=parser.parse_args()
    print(json.dumps(prepare(args.project,args.target),indent=2))
