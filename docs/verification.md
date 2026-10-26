# Local preparation verification — 26 October 2026

Current executable evidence is in `artifacts/pytest-sqlite.xml` and `artifacts/browser-verification.json`; these files record the actual check counts, timestamps and results. This report distinguishes implementation from release verification.

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

## PostgreSQL / hosting

All three applications now pass both SQLite and PostgreSQL CI jobs on Linux: LoopDesk 121, ScopeDesk 100 and FollowDesk 89 checks per backend. Exact tested commits, run URLs, job IDs and log summaries are in each application's `artifacts/ci-verification.json`. ScopeDesk's initial CI run failed because its direct pytest command did not create the temporary directory; the corrected workflow uses the project launcher and passed both jobs. No test assertions were removed.

Production Fernet dependencies are pinned and installed offline on Windows from previously cached, unmodified wheels after checking their recorded hashes. Tests exercise actual Fernet encryption, tampering/wrong-key rejection, no local fallback, fail-closed production configuration and HTTPS-base cookie/header settings. These tests also pass in the Linux CI jobs. See `artifacts/crypto-wheel-verification.json` and the current JUnit/CI reports. This does not establish real TLS or Vercel execution. Three Vercel projects are linked and their public production configuration is set; source is published on GitHub. Neon is not connected. Edge/proxy behaviour, runtime secrets, production migrations and actual deployed applications remain release gates. No live application availability or production security certification is claimed.

The FollowDesk CI jobs include the sibling LoopDesk checkout so integration tests cannot silently disappear. Its passing PostgreSQL job gives both apps separate disposable schemas on a real PostgreSQL service, including the HTTP lost-acknowledgement test. Production Neon connectivity, pooling, TLS and provider limits still require their own checks.

## Reproduction

All test temporary directories and caches are created under D: by `scripts/manage.py`. Live integration tests require the sibling LoopDesk source and launch a real temporary local HTTP server with an isolated synthetic database. Browser verification uses the existing Playwright/axe package specified by `FOLLOWDESK_BROWSER_PACKAGE`; it does not download a browser. Use dedicated test schemas when running `test-postgres`, never a user or production schema.
