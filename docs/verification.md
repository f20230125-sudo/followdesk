## Hosted verification, 27 October 2026

Run against all three public origins (<https://followdesk-phi.vercel.app>, <https://loopdesk-sigma.vercel.app>, <https://scopedesk-chi.vercel.app>; Vercel Hobby plus one Neon PostgreSQL database each, all free plans). Migrations were applied before the deployments. `scripts/live-smoke.py` passed **15/15** checks. The three-app browser journey (`scripts/browser-check.mjs` with `FOLLOWDESK_URL`, `LOOPDESK_URL` and `SCOPEDESK_URL` set to the hosted origins) passed **96 checks** with **32 axe scans reporting no automated violations** and no page errors or HTTP 5xx responses: ScopeDesk review and download, LoopDesk import, one-use pairing, the guided checklist, plan preview and publication, message review and delivery, reply recording, CRM sync, remote revocation, and the JavaScript-disabled flow.

Load time with the cross-app call: after pairing, the queue page took a median of 0.61 s (six loads, 0.53–0.73 s) against 0.42 s before pairing, so the LoopDesk status call costs about 0.2 s; the connection and plans pages had medians of 0.55 s and 0.45 s. All responses were HTTP 200. These are page loads from one PC in Dubai through Chromium, not a load test.

Record: `artifacts/hosted-verification-2026-10-27.json` (the journey script prints a fixed "hosted: not run" string left over from the local runs; the JSON file supersedes it). Not verified: that the Vercel client-address header changes the rate-limit key in production, behaviour under real traffic, and any assistive-technology review.

# Local preparation verification — 26 October 2026

Current executable evidence is in `artifacts/pytest-sqlite.xml` and `artifacts/2026-10-27-after-browser-verification.json`; these files record the actual check counts, timestamps and results. The original `artifacts/browser-verification.json` is retained as historical evidence. This report distinguishes implementation from release verification.

## Improvements verified locally on 27 October 2026

- Full SQLite suite: `135 passed`, compared with 89 before this work (the last added test covers client-address handling behind Vercel). No tests were removed. Added coverage includes all checklist states and workspace isolation; saved versus generated drafts; partial/complete sync; exact grant-expiry boundaries, remote revocation and outage; every placeholder; all five preview slots; UTF-8 byte limits; malformed/hostile inputs; preview CSRF/origin checks and foreign plan denial; metadata, 404 navigation and redacted 500/503 responses.
- Real three-app browser journey: 96 checks passed, 32 axe scans, zero automated violations, no browser exceptions or server failures. The original journey contained 44 checks; additional screenshots also contribute explicit overflow checks. The separate before capture run passed 59 checks because it added baseline screenshots to the original workflow.
- The browser verifies each next-step action, two-tab instructions, post-pairing redirect, Dubai expiry, previews before publication, pinned existing runs, completed native disclosure, receipt counts, metadata and remote revocation. A separate JavaScript-disabled browser context completes the FollowDesk flow through CRM sync and previews a plan.
- Before/after evidence uses new `2026-10-27-before-*` / `2026-10-27-after-*` filenames. Normal screenshots are viewport captures at 1440×900 and 390×844; the print artifact is separate. All pages affected by shared metadata have both baseline and updated desktop/mobile captures. Preview and mobile event-table captures scroll to the relevant content.
- Final services used isolated SQLite databases under FollowDesk's `.local/journey-2026-10-27/` and local ports 15055 / 15058 / 15059. The standard ports became shared with other processes; those processes were left running. Sibling source was used only to execute and understand the existing journey. No sibling source, database or key was edited by this work. FollowDesk was started with `scripts/manage.py run`; small disposable runners loaded the sibling app factories with storage inside FollowDesk. All servers started for this work were stopped.
- No new dependency, table or migration. No provider settings, Neon access, push or deployment in the local work; the hosted run above covers these additions on PostgreSQL, and the pull request's PostgreSQL CI job runs the suite. The CI figures below (89 checks) are historical.

The checklist aggregates milestones across this private workspace. A generated enrolment draft does not count as a saved draft; an explicit `draft_saved` audit record does. Sync is complete only when at least one event exists and every event is synced. Live connection checks are read-only; an outage shows the saved expiry with a warning and keeps connection as the next step. They use the existing four-second CRM request timeout.

## Local SQLite

- The 32 authored fixtures cover valid lifecycle, blocking conflicts, boundary/recovery cases and security rules, with expectations fixed before final UI verification.
- Additional tests race delivery, reply and enrolment commands using independent database connections. They test code exchange/event-receipt races on the LoopDesk side, and actual local HTTP with a deliberately lost acknowledgement after a committed CRM activity.
- Tests cover plain-text placeholders rather than executable Jinja; native browser CRLF normalisation; exact saved-message review; stale edits; approval invalidation; suppression propagation; bounded safety-stop capacity; private mailbox access; expiry cleanup; CSRF/host/origin rules; token encryption and safe CSV.
- The browser journey corrects and reviews the fictional 120-laptop/two-site scope, imports it into LoopDesk, pairs FollowDesk, saves/reviews/delivers a message, records a synthetic reply, verifies cancellation and synchronises exactly two CRM events. Repeated delivery/sync produce no additional effect.
- Desktop/mobile screenshots, print output, keyboard skip navigation and automated axe scans are recorded. No human usability timing or full accessibility certification is claimed.
- Mobile navigation now wraps all six destinations without sideways scrolling, and workspace reset remains available. Both controls are verified in the actual browser journey.

Issues found during implementation were corrected before proceeding: accent contrast; same-origin POST compatibility with strict origin checks; native multiline form line endings; unsaved draft versus saved approval ambiguity; malformed kind types; stop/delivery races; opt-out propagation from old runs; expiry graph cleanup and reset-grant revocation. Final adversarial review also found that CRM placeholder text could introduce a newline into a subject; enrolment now rejects this atomically for LF, CRLF and tab separators. Regression cases cover these behaviours.

## Existing projects

ScopeDesk retains its 92-test security baseline. LoopDesk retains its original behaviours and extends its suite with the additive outreach API, grant and idempotency/concurrency checks. The exact migration assertion now includes `005_followdesk`; no older migration or behavioural regression check was removed. Both original browser workflows were run again locally. The dedicated existing security report remains in `../../security-review/README.md`.

## Dependency advisories

The [successful audit run](https://github.com/f20230125-sudo/followdesk/actions/runs/40379579882) used pip-audit 2.10.1 against the PyPI advisory service. It checked every exact version in all three runtime and test dependency locks, including Windows-only/conditional pins: 20 packages, zero known vulnerabilities reported. The first result omitted `packaging`; it was rejected by the new coverage verifier. Auditing the complete explicit pin set and requiring an exact package/version match closed that gap. No advisory was ignored and no vulnerability exit code was suppressed.

`artifacts/dependency-audit.json` records the package findings; `dependency-audit-verification.json` records scope, timestamp and workflow evidence. This is a known-advisory check, not malicious-package detection or a guarantee of application security. Shared browser tools, GitHub Actions and the deployed system have separate security boundaries.

## PostgreSQL / hosting

All three applications now pass both SQLite and PostgreSQL CI jobs on Linux: LoopDesk 121, ScopeDesk 100 and FollowDesk 89 checks per backend. Exact tested commits, run URLs, job IDs and log summaries are in each application's `artifacts/ci-verification.json`. ScopeDesk's initial CI run failed because its direct pytest command did not create the temporary directory; the corrected workflow uses the project launcher and passed both jobs. No test assertions were removed.

Production Fernet dependencies are pinned and installed offline on Windows from previously cached, unmodified wheels after checking their recorded hashes. Tests exercise actual Fernet encryption, tampering/wrong-key rejection, no local fallback, fail-closed production configuration and HTTPS-base cookie/header settings. These tests also pass in the Linux CI jobs. See `artifacts/crypto-wheel-verification.json` and the current JUnit/CI reports. The CI jobs do not establish real TLS or Vercel execution; the hosted run on 27 October 2026 (top of this file) does, for the three deployed applications and their Neon databases. No production security certification or availability guarantee is claimed.

The FollowDesk CI jobs include the sibling LoopDesk checkout so integration tests cannot silently disappear. Its passing PostgreSQL job gives both apps separate disposable schemas on a real PostgreSQL service, including the HTTP lost-acknowledgement test. Production Neon connectivity, pooling and TLS were exercised by the hosted run; provider limits on the free plans still apply (see `deployment.md`).

## Reproduction

All test temporary directories and caches are created under D: by `scripts/manage.py`. Live integration tests require the sibling LoopDesk source and launch a real temporary local HTTP server with an isolated synthetic database. Browser verification uses the existing Playwright/axe package specified by `FOLLOWDESK_BROWSER_PACKAGE`; it does not download a browser. Use dedicated test schemas when running `test-postgres`, never a user or production schema.
