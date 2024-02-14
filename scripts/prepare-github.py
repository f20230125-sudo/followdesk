"""Freeze and privacy-check the public source allowlist; perform no network writes."""
from pathlib import Path
import hashlib
import json
import runpy

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parent
TEXT={".py",".html",".css",".js",".mjs",".sql",".json",".md",".txt",".csv",".svg",".yml",".ps1",".xml",".toml",".cmd",".example"}


def main():
    exports=runpy.run_path(str(ROOT/"scripts/package-release.py"))
    forbidden=[]
    cv=WORK/"loopdesk/private/cv-verification.json"
    if cv.exists():
        forbidden.extend(value.split(":",1)[1].encode() for value in json.loads(cv.read_text()).get("links",[]) if value.startswith(("mailto:","tel:")))
    for name in exports["PROJECTS"]:
        project=WORK/name
        for key in ("session-secret","vault-key"):
            file=project/"instance"/key
            if file.exists():forbidden.append(file.read_bytes().strip())
        secrets=project/".local/deployment/secrets.json"
        if secrets.exists():forbidden.extend(value.encode() for target in json.loads(secrets.read_text()).values() for value in target.values())
    folder=ROOT/".local/publication"
    folder.mkdir(parents=True,exist_ok=True)
    for name in exports["PROJECTS"]:
        project=WORK/name
        text_files=[]
        binaries=[]
        for file in exports["source_files"](project):
            path=file.relative_to(project).as_posix()
            raw=file.read_bytes()
            assert not any(value and value in raw for value in forbidden),f"Private data comparison failed for {name}/{path}"
            git_sha=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
            if file.suffix in TEXT or file.name in {".gitignore",".vercelignore"}:
                text_files.append(dict(path=path,mode="100644",type="blob",content=raw.decode("utf-8")))
            else:
                binaries.append(dict(path=path,bytes=len(raw),gitSha=git_sha,sha256=hashlib.sha256(raw).hexdigest()))
        payload=dict(application=name,repository="f20230125-sudo/"+name,textFiles=text_files,binaryFiles=binaries,privateComparisonsPassed=True)
        (folder/(name+".json")).write_text(json.dumps(payload,ensure_ascii=True),encoding="utf-8")
        print(json.dumps(dict(application=name,textFiles=len(text_files),binaryFiles=len(binaries),binaryBytes=sum(x["bytes"] for x in binaries),privateComparisonsPassed=True)))


if __name__=="__main__":main()
