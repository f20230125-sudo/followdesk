# Deployment runbook

Hosted since 27 October 2026 at <https://followdesk-phi.vercel.app>.

| App | Hosted at |
| --- | --- |
| LoopDesk | <https://loopdesk-sigma.vercel.app> |
| ScopeDesk | <https://scopedesk-chi.vercel.app> |
| FollowDesk | <https://followdesk-phi.vercel.app> |

## Where it runs

- **Application:** a Vercel project on the free Hobby plan (Python/Flask runtime; `app.py` exports `app`, `pyproject.toml` declares the entrypoint and the dependencies Vercel installs, including `cryptography` for the Fernet vault).
- **Database:** a Neon PostgreSQL database on Neon's free plan, added through the Vercel Marketplace, separate from the other two apps. The app uses Neon's pooled endpoint; migrations use the direct, unpooled endpoint.

Nothing here needs a paid plan. If a free limit blocks a step, stop and change the design instead of upgrading.

## Environment

| App | Database credential | Session secret | Other required production settings |
| --- | --- | --- | --- |
| LoopDesk | `DATABASE_URL` | `SECRET_KEY` | `APP_ENV`, `LOOPDESK_TRUSTED_HOSTS`, `LOOPDESK_FOLLOWDESK_URL` |
| ScopeDesk | `SCOPEDESK_DATABASE_URL` | `SCOPEDESK_SECRET_KEY` | `APP_ENV`, `SCOPEDESK_TRUSTED_HOSTS`, `SCOPEDESK_LOOPDESK_URL` |
| FollowDesk | `FOLLOWDESK_DATABASE_URL` | `FOLLOWDESK_SECRET_KEY` | `APP_ENV`, `FOLLOWDESK_TRUSTED_HOSTS`, `FOLLOWDESK_LOOPDESK_URL`, `FOLLOWDESK_VAULT_KEY` |

Session secrets (at least 32 characters) and FollowDesk's Fernet vault key are generated randomly per environment and stored as write-only (sensitive) variables; the vault key encrypts the CRM grant tokens at rest. Credentials live in the provider's settings, never in source, chat or logs. Production and preview use separate databases and secrets. Production refuses SQLite and missing or placeholder secrets, trusted hosts or vault key. Request limits are keyed on the visitor's address: behind Vercel that is the platform-set `X-Vercel-Forwarded-For` header (Vercel overwrites client-supplied values), elsewhere forwarding headers are ignored because anyone could spoof them.

## Release procedure, in order

1. Run each app's suite (`python scripts/manage.py test`; the PostgreSQL jobs run in GitHub Actions) and the local three-app browser journey (`python scripts/manage.py browser`).
2. Apply migrations before deploying code that needs them: `python -m flask --app app migrate` in each app, with its database variable set to the unpooled Neon URL. Migrations never run at import or during a build, and are additive, so the previous deployment keeps working while the new schema is in place.
3. Run `python scripts/prepare-suite.py --target production` from this repository. It reads each project's link, writes the allowlisted runtime payload (runtime code, assets, migrations, dependency configuration) with a checksum manifest bound to the project, and excludes tests, screenshots, databases, credentials and private material. Deploy each payload through Vercel's deployments API.
4. Verify the hosted apps: `python scripts/live-smoke.py`, then the three-app browser journey with `FOLLOWDESK_URL`, `LOOPDESK_URL` and `SCOPEDESK_URL` set to the hosted origins. Record the results in [verification](verification.md).

A weekly GitHub Actions workflow (`live-smoke.yml`) runs the smoke check against the hosted app. FollowDesk's CI checks out LoopDesk next to it, so the integration tests run against the real CRM code on both SQLite and PostgreSQL. A coverage-checked advisory scan covers all 20 pinned runtime and test packages across the three apps (`artifacts/dependency-audit-verification.json`).

## Defects that only showed up when hosted

- Vercel installs from `pyproject.toml`, not `requirements.txt`, so the dependency list is duplicated there.
- A function-local `import re` inside the non-production branch of `create_app` made `re` unbound in the production branch, and publishing a plan returned a 500 on the hosted app only. Production-only branches are not covered by the local suite, so every deployment is followed by the hosted journey.

## Free-tier behaviour

Neon suspends an idle database, so the first request after a quiet period can take a second or two longer. FollowDesk calls LoopDesk's API for connection status and CRM context (four-second timeout); if LoopDesk is unavailable, local pausing, stopping and recording outcomes keep working and the connection page says the status could not be checked.
