# Claude Code Instructions for Docflow

You are helping build **Docflow**, a production SaaS product. Read this file and the source-of-truth documents before changing code.

## Required reading

1. `README.md`
2. `docs/DECISIONS.md`
3. `docs/OPEN_QUESTIONS.md`
4. `docs/ARCHITECTURE.md`
5. `docs/RULES.md`
6. `docs/ROADMAP.md`
7. Relevant phase-specific docs
8. `progress.md` before and after a work session

## Work mode

- This repository begins as a planning pack; application code may not exist yet.
- Start with **Phase 0 only**: inspect the repository and Git status, summarize current state and risks, reconcile the planned tree, identify gaps, and propose a concrete Phase 1 plan.
- Do not implement Phase 1 or later until the user explicitly approves it.
- Work incrementally; preserve existing work and never overwrite/delete files blindly.
- After each implementation task or cohesive file-change batch, append to `progress.md`: each file changed, what changed, why, exact commands actually run, observed test/check results, security/reliability consequences, decisions and unresolved issues. Include failed commands and corrected attempts; do not fabricate a command transcript you did not collect. Keep entries factual and append-only. Never claim a test passed unless it ran and passed.
- When requirements conflict, stop and explain the conflict. Do not guess.
- If an external contract is unknown, record it in `docs/OPEN_QUESTIONS.md`; use only a narrow interface or fake/test adapter where appropriate.

## Approved decisions

- Product: Docflow. V1: diagnostic labs; recipient phone number in a PDF filename, initially `919876543210.pdf`.
- Authorized administrators configure and verify WhatsApp account assignments.
- Dashboard: Next.js App Router + TypeScript + Tailwind + shadcn/ui under `dashboard/`.
- Backend: Django + DRF under `backend/`.
- Development database: Django-default SQLite. Production database: PostgreSQL selected through environment configuration.
- Agent: Python Windows service, watchdog, local SQLite durable queue, HTTPX, Pydantic, Windows Service support and PyInstaller packaging.
- Existing WhatsApp platform owns delivery integration and inbox/replies. No second inbox.
- PDF bytes bypass Django. Django stores metadata, delivery state and control-plane records only.
- tmpfiles.org is development-only and fictional-PDF-only.
- Redis/Celery may support maintenance, analytics and background work, but must not be the sole source of truth or a single mandatory per-send dependency. Use durable database state/outbox and recovery.

## Security rules

`docs/RULES.md` contains seven testable non-negotiables. `docs/SECURITY.md` and `docs/DELIVERY_STATE_MACHINE.md` are required references for delivery changes. Tenant isolation is enforced in every queryset, serializer, service operation and object permission check. Tests must prove cross-tenant access is denied.

Never expose the global developer token or an account access token to the browser or Windows Agent. Do not invent a media-upload endpoint, token provisioning mechanism, provider status callback, webhook signature scheme or account-routing behavior. The existing wrapper was tested using a backend-held global developer token; the platform developer separately confirmed that accounts have different phone-number IDs and access tokens. Exactly how Docflow is meant to provision/use those credentials remains unconfirmed.

Do not upload real patient reports to tmpfiles.org. Do not write PDF bytes into Django, PostgreSQL, logs, telemetry or the dashboard. A temporary public download URL is sensitive; redact it and restrict the development adapter to the expected host.

## Definition of done

- Requirements/acceptance criteria are understood and scope matches the approved phase.
- Relevant specs were read and are not contradicted.
- Tests are added/updated for new behavior and security boundaries.
- Relevant checks are actually run; results are accurately recorded.
- Docs are updated when a contract/decision changes, with approval where required.
- `progress.md` has a factual entry.
- Final report lists changed files, actual tests/results, limitations and next step.
