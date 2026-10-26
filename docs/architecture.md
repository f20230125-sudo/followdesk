# Architecture and integration boundaries

FollowDesk is an independent Flask/Jinja application. `services.py` owns validation, plan publication, enrolment, approval, allocation of steps, outcomes, suppression, reports and atomic changes. HTTP handlers and tests call the same services. The small DB-API adapter follows the existing SQLite/psycopg approach; no runtime import from the LoopDesk source is required.

Relational records persist workspace ownership, encrypted connections, immutable plan versions, enrolments, copied steps and approvals, immutable demo receipts, append-only outcome/outbox events, suppressions and audit history. All owned lookups include the server-established workspace. Foreign identifiers fail without revealing another workspace. Workspace locks serialize check/write operations; unique indexes guard active contact/destination enrolments and receipts. Normal record limits are bounded, with a small reserve for monotonic stop events. Expiry cleanup removes child receipts/events before deleting workspaces in one transaction.

Only the current due step is actionable. Schedule times are UTC and displayed as Dubai wall-clock times. Delays are elapsed hours anchored to actual previous completion, not business-day/holiday rules. Pausing preserves the remaining wait; resuming changes the schedule and clears approval. Source/plan data is never silently regenerated at delivery.

The saved-message review page renders read-only content and issues an app-signed, ten-minute snapshot proof. Confirming it performs fresh context/step checks before storing approval. Delivery checks the same frozen content and CRM context again. A local transaction writes one unique receipt, advances the step and queues one immutable CRM event. No network call runs under that write lock.

Reply/opt-out/stop actions are monotonic and may rebase over a lower submitted version when delivery just advanced the run. Invalid/future versions are rejected. Pausing, editing and scheduling remain strict optimistic edits. An identical repeated outcome is idempotent. A later opt-out can be recorded on a stopped run and cancels matching active work; suppressions are not removed in v1.

`crm.py` only calls the operator-configured LoopDesk origin, rejects unsafe origin configuration, follows no redirects and bounds time/response size. Invalid/empty hostnames, whitespace and invalid ports fail during configuration. Its reusable access token is encrypted at rest. Local encryption delegates AES-256-GCM to Node's standard library, using a separate random key in ignored `instance/`. The production Fernet path is tested locally with pinned cryptography dependencies, including wrong-key and tampering rejection, secure-cookie settings and no local fallback. Its Linux/hosted execution remains unverified. Keys/tokens are never put in browser cookies, URLs, logs or exports.

## Version-one LoopDesk API

An additive LoopDesk migration `005_followdesk` stores one-use hashed pairing codes, hashed revocable grants and immutable source-event receipts. Browser setup/revocation retains normal session + CSRF protections. Named service API routes exclusively require their own authentication and never fall back to browser cookies.

| Method / path under `/api/followdesk/v1` | Behaviour |
| --- | --- |
| POST `/exchange` | Consume five-minute code once; bind grant to client/source workspace and expire within one hour |
| GET `/opportunities` | Bounded opportunity selection list from grant-derived workspace |
| GET `/opportunities/<id>` | Current linked contact/org/status/version and latest scope metadata received by CRM |
| POST `/events` | Strict typed event append; no business-field updates or record creation |
| POST `/revoke` | Revoke current grant |

Events contain schema/source identity, stable event/run IDs, sequence, target opportunity, kind, recorded UTC, bounded summary and a canonical-payload SHA-256 digest. The digest checks integrity; the grant establishes API access. Neither proves customer identity or approval. The deduplication key is issuer workspace + source workspace + event ID, independent of rotating grant IDs. Same event/content returns the previous receipt; altered content under the same ID returns 409. Historical events can append after an opportunity closes without reopening it.

Live context checks reflect CRM state at the check time, not atomic cross-application consistency. Unexported ScopeDesk changes are invisible. CRM sync is a separate bounded action processing up to three pending events; failure never repeats a message. Disconnection disables local credentials immediately and attempts source revocation. Unconfirmed revocation is labelled, and the issuer grant expires within one hour.
