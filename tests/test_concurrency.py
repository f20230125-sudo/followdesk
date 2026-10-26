from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from werkzeug.exceptions import HTTPException
from followdesk import services as s
from followdesk.contract import ContractError
from followdesk.db import get_db
from conftest import run
from test_domain import deliver


def test_concurrent_delivery_has_one_effect(app,db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    step=s.current_step(db,workspace,eid)
    s.approve(db,workspace,step["id"],step["version"],context)
    step=s.current_step(db,workspace,eid)
    barrier=Barrier(6)
    def worker(_):
        with app.app_context():
            barrier.wait(timeout=10)
            return s.deliver(get_db(),workspace,step["id"],step["version"],context)
    with ThreadPoolExecutor(max_workers=6) as pool: receipts=list(pool.map(worker,range(6)))
    assert len(set(receipts))==1
    assert s.report(db,workspace)["deliveries"]==s.report(db,workspace)["pending"]==1


def test_reply_racing_delivery_always_stops_future_work(app,db,workspace,plan,context):
    eid=run(db,workspace,plan,context)
    step=s.current_step(db,workspace,eid)
    s.approve(db,workspace,step["id"],step["version"],context)
    step=s.current_step(db,workspace,eid)
    barrier=Barrier(2)
    def worker(kind):
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                if kind=="delivery": return s.deliver(get_db(),workspace,step["id"],step["version"],context)
                s.outcome(get_db(),workspace,eid,1,"reviewer_reply","Concurrent fictional reply.")
                return "reply recorded"
            except s.Conflict:
                assert kind=="delivery"
                return "delivery stopped"
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(worker,["delivery","reply"]))
    assert "reply recorded" in results
    assert s.record(db,"enrollments",workspace,eid)["status"]=="Stopped"
    assert s.current_step(db,workspace,eid) is None
    assert s.report(db,workspace)["deliveries"] in (0,1)
    assert s.report(db,workspace)["replies"]==1


def test_concurrent_enrollment_has_one_run(app,db,workspace,plan,context):
    barrier=Barrier(5)
    def worker(_):
        with app.app_context():
            barrier.wait(timeout=10)
            try: return run(get_db(),workspace,plan,context)
            except s.Conflict: return None
    with ThreadPoolExecutor(max_workers=5) as pool: values=list(pool.map(worker,range(5)))
    assert len([x for x in values if x])==1 and s.report(db,workspace)["runs"]==1
