CREATE TABLE workspaces (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE revoked_workspaces (workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE, revoked_at TEXT NOT NULL);
CREATE TABLE security_buckets (bucket TEXT PRIMARY KEY, hits INTEGER NOT NULL CHECK(hits>0), expires_at BIGINT NOT NULL);
CREATE INDEX ix_security_expiry ON security_buckets(expires_at);
CREATE TABLE connections (
 workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
 source_workspace_id TEXT NOT NULL,
 encrypted_token TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Connected'
);
CREATE TABLE plan_versions (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 name TEXT NOT NULL,
 family TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>0),
 steps TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(workspace_id,id),
 UNIQUE(workspace_id,family,revision)
);
CREATE TABLE enrollments (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 source_workspace_id TEXT NOT NULL,
 opportunity_id TEXT NOT NULL,
 contact_id TEXT NOT NULL,
 address_key TEXT NOT NULL,
 context TEXT NOT NULL,
 plan_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('Active','Paused','Stopped','Completed')),
 stop_reason TEXT NOT NULL DEFAULT '',
 remaining_seconds BIGINT,
 version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 UNIQUE(workspace_id,id),
 FOREIGN KEY(workspace_id,plan_id) REFERENCES plan_versions(workspace_id,id)
);
CREATE UNIQUE INDEX ix_active_contact ON enrollments(workspace_id,source_workspace_id,contact_id) WHERE status IN ('Active','Paused');
CREATE UNIQUE INDEX ix_active_address ON enrollments(workspace_id,address_key) WHERE status IN ('Active','Paused');
CREATE TABLE steps (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL,
 enrollment_id TEXT NOT NULL,
 position INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('message','task')),
 title TEXT NOT NULL,
 delay_hours INTEGER NOT NULL CHECK(delay_hours BETWEEN 0 AND 720),
 due_at TEXT,
 status TEXT NOT NULL CHECK(status IN ('Pending','Delivered','Done','Skipped','Cancelled')),
 subject TEXT NOT NULL,
 body TEXT NOT NULL,
 approval TEXT,
 version INTEGER NOT NULL DEFAULT 1,
 UNIQUE(workspace_id,id),
 UNIQUE(workspace_id,enrollment_id,position),
 FOREIGN KEY(workspace_id,enrollment_id) REFERENCES enrollments(workspace_id,id) ON DELETE CASCADE
);
CREATE TABLE receipts (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL,
 enrollment_id TEXT NOT NULL,
 step_id TEXT NOT NULL,
 recipient TEXT NOT NULL,
 subject TEXT NOT NULL,
 body TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(workspace_id,id),
 UNIQUE(workspace_id,step_id),
 FOREIGN KEY(workspace_id,step_id) REFERENCES steps(workspace_id,id),
 FOREIGN KEY(workspace_id,enrollment_id) REFERENCES enrollments(workspace_id,id)
);
CREATE TABLE events (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL,
 enrollment_id TEXT NOT NULL,
 sequence INTEGER NOT NULL,
 kind TEXT NOT NULL,
 origin TEXT NOT NULL,
 note TEXT NOT NULL,
 payload TEXT NOT NULL,
 created_at TEXT NOT NULL,
 sync_status TEXT NOT NULL DEFAULT 'Pending' CHECK(sync_status IN ('Pending','Synced','Failed')),
 crm_receipt TEXT,
 UNIQUE(workspace_id,enrollment_id,sequence),
 FOREIGN KEY(workspace_id,enrollment_id) REFERENCES enrollments(workspace_id,id)
);
CREATE TABLE suppressions (
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 key_type TEXT NOT NULL CHECK(key_type IN ('contact','address')),
 identity TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(workspace_id,key_type,identity)
);
CREATE TABLE audit_events (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 enrollment_id TEXT,
 action TEXT NOT NULL,
 note TEXT NOT NULL,
 created_at TEXT NOT NULL
);
