"""Audit every pinned runtime/test dependency, including conditional platform pins."""
from pathlib import Path
import argparse
import json
import re

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify",action="store_true")
    parser.add_argument("--report",type=Path,default=ROOT/"artifacts/dependency-audit.json")
    args=parser.parse_args()
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
    if args.verify:
        audit=json.loads(args.report.read_text(encoding="utf-8"))
        rows=audit["dependencies"]
        actual={re.sub(r"[-_.]+","-",row["name"]).lower():row.get("version") for row in rows}
        missing=sorted(set(pins)-set(actual))
        if actual!=pins or len(actual)!=len(rows) or any(row.get("skip_reason") or not isinstance(row.get("vulns"),list) for row in rows):
            raise ValueError("Audit coverage does not match all locked versions; missing: "+", ".join(missing))
        if any(row.get("vulns") for row in rows):raise ValueError("Known vulnerabilities found; review the audit JSON before release")
        report.update(allLockedVersionsAudited=True,knownVulnerabilities=0)
    print(json.dumps(report))


if __name__=="__main__":main()
