"""Audit every pinned runtime/test dependency, including conditional platform pins."""
from pathlib import Path
import json
import re

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parent


def main():
    pins={}
    sources=[]
    for project in ("loopdesk","scopedesk","followdesk"):
        for filename in ("requirements.txt","requirements-dev.txt"):
            path=WORK/project/filename
            for original in path.read_text(encoding="utf-8").splitlines():
                line=original.strip()
                if not line or line.startswith(("#","-r ")):continue
                # Include Windows-only and older-Python pins too: auditing on
                # Linux must not silently exclude dependencies shipped offline.
                pin=line.split(";",1)[0].strip()
                match=re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)",pin)
                if not match:raise ValueError("Audit requires explicit package/version pins")
                name,version=match.groups()
                name=re.sub(r"[-_.]+","-",name).lower()
                if name in pins and pins[name]!=version:raise ValueError("Conflicting versions need separate dependency audits")
                pins[name]=version
            sources.append(str(Path(project)/filename))
    folder=ROOT/".local/dependency-audit"
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"requirements.txt").write_text("".join(f"{name}=={pins[name]}\n" for name in sorted(pins)),encoding="utf-8")
    report=dict(packageCount=len(pins),locks=sources,conditionalPinsIncluded=True,scope="All three runtime and test dependency locks; browser tooling and GitHub Actions are separate tools")
    (folder/"scope.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))


if __name__=="__main__":main()
