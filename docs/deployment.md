# Deployment preparation — 26 October 2026

Publication is already authorised. Vercel team access now works, and the following new Flask projects have been created, read back and linked in the approved team. These are assigned hostnames, **not live applications**.

| App | Verified project ID | Assigned production hostname |
| --- | --- | --- |
| LoopDesk | `prj_PBu1fIAONvCoQBLbLptQDntykAUp` | `loopdesk-sigma.vercel.app` |
| ScopeDesk | `prj_3ZZAml6EwIlwO9DAZTPkS7ip1XjX` | `scopedesk-chi.vercel.app` |
| FollowDesk | `prj_RWkG4vd3qu37euRqOmJ6JToV6m58` | `followdesk-phi.vercel.app` |

Production `APP_ENV`, exact trusted hosts and cross-app origins are configured. No database or session/vault secret was sent to Vercel, and no deployment was created. Preview configuration remains separate and incomplete. Do not point a preview at production data.

## Required environment names

| App | Database credential | Session secret | Other required production settings |
| --- | --- | --- | --- |
| LoopDesk | `DATABASE_URL` | `SECRET_KEY` | `APP_ENV`, `LOOPDESK_TRUSTED_HOSTS`, `LOOPDESK_FOLLOWDESK_URL` |
| ScopeDesk | `SCOPEDESK_DATABASE_URL` | `SCOPEDESK_SECRET_KEY` | `APP_ENV`, `SCOPEDESK_TRUSTED_HOSTS`, `SCOPEDESK_LOOPDESK_URL` |
| FollowDesk | `FOLLOWDESK_DATABASE_URL` | `FOLLOWDESK_SECRET_KEY` | `APP_ENV`, `FOLLOWDESK_TRUSTED_HOSTS`, `FOLLOWDESK_LOOPDESK_URL`, `FOLLOWDESK_VAULT_KEY` |

Session secrets and FollowDesk's Fernet key have been generated separately for production and preview under each project's ignored `.local/deployment/secrets.json`. Values were not printed. Retain existing generated values when configuring their matching environment; do not regenerate or expose them in source, screenshots or chat. Store runtime secrets as protected provider variables. This file is not silently loaded by Flask and is excluded from archives/deployments.

## Remaining execution

1. Connect the Neon app or provision the integration through Vercel. No Neon integration is currently installed in the team. Confirm any paid plan before creating a charge. Use new app-specific database credentials, separate preview/production data and a dedicated test database. Do not repurpose another project's database.
2. Configure the database credentials and protected runtime secrets. Verify required variable names without printing their values. Provider Secret values may not be available through a normal environment pull; use explicitly authorised migration credentials rather than assuming a pull reproduces production secrets.
3. SQLite and PostgreSQL suites now pass for all three apps in CI. FollowDesk checks out LoopDesk alongside it and gives both sides disposable schemas for actual HTTP integration tests. See `artifacts/ci-verification.json` for tested commits and run links. Verify connectivity/TLS and the relevant provider-specific behaviour against dedicated Neon test credentials after provisioning.
4. Apply the versioned migrations once, before traffic, using `python -m flask --app app migrate` from each correctly configured app. No migrations run at import or deployment build time. Record the schema/migration version and test results.
5. Run `python scripts/prepare-suite.py --target preview` from FollowDesk after any source change. It reads verified `.vercel/project.json` links and writes each app's allowlisted `.local/deployment/runtime-payload.json` and checksum manifest. Inspect exact project IDs and targets before using the authenticated Vercel deployment tool. Private data, secrets, databases, tests and recordings are excluded.
6. Linux dependency installation and real production Fernet tests now pass in CI using the pinned [cryptography release](https://pypi.org/project/cryptography/50.0.2/). Confirm installation on the actual Vercel runtime as well. The Flask entrypoint and public asset arrangement follow the [Vercel Flask guide](https://vercel.com/docs/frameworks/backend/flask).
7. Execute the deployed browser journey across all three apps, including pairing, exact review, a simulated receipt, a synthetic reply and repeat-safe CRM history. Verify real HTTPS, cookies, host/origin controls, cross-workspace denial, outage recovery and provider request limits. Resolve any deployment protection using the existing account's authorised access. Do not weaken protection just to pass an automated check.
8. Publish/promote only after those checks pass. Add tested public links to the CV only under the user's separate CV instructions. Submission remains manual.

The GitHub repositories `f20230125-sudo/loopdesk`, `scopedesk` and `followdesk` now contain the reviewed source, screenshots and recordings, and their CI suites pass. Publication permission does not supply missing provider connections. No full dependency-advisory scan, human five-minute usability study or production security certification is claimed.
