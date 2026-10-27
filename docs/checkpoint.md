# Preparation checkpoint — 26 October 2026

FollowDesk has a working local core. Source publication and Vercel project setup are separate from live application deployment. The existing two applications retain their tested local workflows. The CV and application submission have not been changed.

## Run and inspect

Start the three launchers from an extraction on D:, with Windows x64, Python 3.14 and Node.js 24 installed:

- `loopdesk/Start-LoopDesk.cmd` → http://127.0.0.1:5055
- `scopedesk/Start-ScopeDesk.cmd` → http://127.0.0.1:5058
- `followdesk/Start-FollowDesk.cmd` → http://127.0.0.1:5059

FollowDesk's README contains the pairing and review journey. The source CRM remains the place to manage contacts and opportunities. FollowDesk's built-in inbox sends no email. All data in the demonstration is fictional.

Watch `artifacts/FollowDesk-Demo.webm`: the verified playable recording lasts 76.48 seconds and covers the imported scope, exact-message review, simulated delivery, reply cancellation and CRM history. Pairing credentials were prepared before recording. Desktop/mobile screenshots and print output are in the same folder.

## Evidence

| Area | Local result |
| --- | --- |
| FollowDesk SQLite suite | 89 passing checks, including 32 authored domain/security fixtures, production vault/configuration and maximum UTF-8 plan checks |
| LoopDesk SQLite suite | 121 passing checks; original regression checks retained |
| ScopeDesk SQLite suite | 100 passing checks, including hosted-navigation configuration |
| Linux SQLite and PostgreSQL CI | All three projects pass both jobs: 121 LoopDesk, 100 ScopeDesk and 89 FollowDesk checks per backend |
| Python dependency advisories | All 20 runtime/test pins audited, including conditional platform pins; zero known vulnerabilities reported |
| Three-app browser journey | 44 checks; 12 automated accessibility scans with zero detected violations |
| Original ScopeDesk browser journey | 43 checks; 11 scans with zero detected violations |
| Original LoopDesk browser journey | 20 checks; 10 scans with zero detected violations |
| Offline package | Three clean virtual environments, network-free dependency installation and actual handoff/pair/review/delivery/reply/sync journey |
| Publication boundaries | Allowlisted source, source-manifest SHA-256 checks and known private-data comparisons |

Executable reports, not this table, are the authority. `artifacts/pytest-sqlite.xml`, `browser-verification.json`, `offline-verification.json` and `public-release-verification.json` record outcomes and timestamps. The final two reports are generated after packaging; the archive contains `OFFLINE-VERIFICATION.json` and `SOURCE-MANIFEST.json` at its root.

## Material limits and next work

The existing scoped connection is live between local apps. Since 27 October 2026 it is also exercised between the three hosted applications (see [verification](verification.md)). The workflow checks the latest scope received by LoopDesk; it cannot discover a ScopeDesk revision that has never been exported. A live CRM precheck and a local delivery transaction do not form a distributed transaction. CRM outages block new enrolment, approval and delivery; local stops and recorded outcomes remain available.

All three source repositories are published on GitHub with screenshots and recordings. Vercel team access is working and three new Flask projects are created and linked. Their verified domains, trusted-host settings and production links between apps are configured; at that point no application had been deployed. Those steps were completed on 27 October 2026; this paragraph describes the state before hosting. The local vault uses Node's standard AES-256-GCM implementation. The separate production Fernet vault and its pinned dependencies pass Windows and Linux checks; Vercel execution still requires verification. The complete 20-package Python lock advisory scan passes; deployed security and production operations still require verification. Automated accessibility results do not establish full conformance; a human five-minute workflow assessment has not been performed.

The overnight work should address those gates, deployment configuration, failure handling on real providers and further human usability review. Scope remains the reviewed sales-outreach prototype; real outbound messaging and AI are outside this version. CV changes should use only the demonstrated local features and remain subject to the user's next instructions.
