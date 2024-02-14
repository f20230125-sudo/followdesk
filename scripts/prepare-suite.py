"""Build three runtime payloads for verified links; sends nothing and reads no secrets."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parent
PROJECTS=("loopdesk","scopedesk","followdesk")
EXTENSIONS={".py",".html",".css",".js",".mjs",".svg",".sql"}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target",choices=["preview","production"],default="preview")
    args=parser.parse_args()
    links={name:json.loads((WORK/name/".vercel/project.json").read_text()) for name in PROJECTS}
    assert len({item["orgId"] for item in links.values()})==1,"Projects must be linked to the same approved team"
    assert len({item["projectId"] for item in links.values()})==3,"Use three independent projects"
    reports=[]
    for name in PROJECTS:
        project=WORK/name
        paths=[project/filename for filename in ("app.py","pyproject.toml","requirements.txt","vercel.json")]
        for folder in (name,"migrations","public"):
            paths.extend(p for p in (project/folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix in EXTENSIONS)
        manifest=[]
        files=[]
        combined=hashlib.sha256()
        for path in sorted(paths):
            relative=path.relative_to(project).as_posix()
            raw=path.read_bytes()
            combined.update(relative.encode()+b"\0"+raw)
            files.append(dict(file=relative,data=base64.b64encode(raw).decode(),encoding="base64"))
            manifest.append(dict(path=relative,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        fingerprint=combined.hexdigest()
        payload=dict(name=name,project=links[name]["projectId"],target=args.target,files=files,projectSettings=dict(framework="flask"),meta=dict(suiteSourceSha256=fingerprint))
        folder=project/".local/deployment"
        folder.mkdir(parents=True,exist_ok=True)
        (folder/"runtime-payload.json").write_text(json.dumps(payload),encoding="utf-8")
        report=dict(application=name,teamId=links[name]["orgId"],projectId=links[name]["projectId"],target=args.target,sent=False,sourceSha256=fingerprint,files=manifest)
        (folder/"manifest.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        reports.append(dict(application=name,projectId=links[name]["projectId"],files=len(files),bytes=sum(item["bytes"] for item in manifest),sourceSha256=fingerprint,sent=False))
    result=dict(projectsLinked=True,credentialsIncluded=False,databasesIncluded=False,published=False,target=args.target,applications=reports)
    (ROOT/"artifacts/deployment-preparation.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
