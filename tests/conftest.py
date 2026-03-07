import copy
import os
import uuid
from datetime import datetime,timezone

import pytest
from followdesk import create_app
from followdesk.db import Database,get_db,migrate
from followdesk import services as s


@pytest.fixture
def app(tmp_path):
    url=os.environ.get("FOLLOWDESK_TEST_DATABASE_URL")
    schema=None
    admin=None
    if url:
        if not url.startswith(("postgres://","postgresql://")): raise ValueError("Use a dedicated PostgreSQL test database.")
        from psycopg import sql
        schema="followdesk_test_"+uuid.uuid4().hex
        admin=Database(url)
        with admin.transaction(): admin.conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    clock=[datetime(2026,10,26,12,0,tzinfo=timezone.utc)]
    app=create_app(dict(TESTING=True,PRODUCTION=False,SECRET_KEY="isolated-tests-only-secret",DATABASE_URL=url or "sqlite:///"+str(tmp_path/"follow.sqlite3"),DATABASE_SCHEMA=schema,LOCAL_VAULT_FILE=str(tmp_path/"vault-key"),CLOCK=lambda:clock[0]))
    app.test_clock=clock
    with app.app_context(): migrate(get_db())
    try: yield app
    finally:
        if admin:
            with admin.transaction(): admin.conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            admin.close()


@pytest.fixture
def db(app):
    with app.app_context(): yield get_db()


@pytest.fixture
def workspace(db): return s.create_workspace(db)


@pytest.fixture
def context():
    return dict(id="1"*32,title="Two-site laptop refresh",stage="New",service="IT asset disposition",owner="Maya (demo)",next_action="Discuss remaining scope questions",version=1,organisation=dict(id="2"*32,name="Fictional Acacia",archived=False,version=1),contact=dict(id="3"*32,name="Alex Example",email="alex@acacia.example.com",archived=False,version=1),received_scopes=[dict(case_id="4"*32,revision=1,digest="a"*64,review_status="Reviewed with assumptions",assumption_count=1)])


@pytest.fixture
def plan(db,workspace): return db.one("SELECT id FROM plan_versions WHERE workspace_id=? AND name='Enquiry follow-up'",(workspace,))["id"]


def run(db,wid,pid,context): return s.enroll(db,wid,pid,copy.deepcopy(context),"5"*32)


def session_for(client,wid):
    with client.session_transaction() as session:
        session["workspace_id"]=wid
        session["csrf"]="fixture-csrf"
    return "fixture-csrf"
