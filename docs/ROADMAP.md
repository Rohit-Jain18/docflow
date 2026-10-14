# Docflow Roadmap (Phases 0–5)

Phases are sequential gates. Only one phase may be active at a time unless the user explicitly approves parallel work. End each phase with a review and factual `progress.md` entry.

## Phase 0 — Repository inspection and contract baseline

**Deliverables**
- Inspect project tree, Git status and existing files; preserve all useful work.
- Confirm target monorepo (`dashboard/`, `backend/`, `agent/`, `infrastructure/`, `docs/`); do not create duplicate `web/` and `dashboard/` roots.
- Review this pack; list contradictions, missing decisions and external blockers.
- Enforce read-only tooling on Claude review subagents (`.claude/agents/*.md` with `tools: Read, Grep, Glob`).
- Propose app/API boundaries and file-by-file Phase 1 plan.
- Confirm tool/runtime versions and commands from actual repository state; do not assume versions.

**Done criteria**
- [ ] Git tree inspected; no destructive changes.
- [ ] Existing code (if any) summarized accurately.
- [ ] Review subagents restricted to read-only tools without file editing or write capabilities.
- [ ] Contract gaps/open questions listed.
- [ ] Phase 1 tasks have scope and acceptance criteria.
- [ ] No application code written in Phase 0 without approval.
- [ ] User reviewed and approved Phase 1.

## Phase 1 — Backend and tenant-safe control plane

**Deliverables**
- Django settings with SQLite development and PostgreSQL production configuration.
- Startup configuration validator failing closed in production for unsafe settings, including rejection of development verification overrides.
- Choose custom Django user model before first migration; model memberships/roles.
- Models/migrations for organizations, labs, branches, devices, activation, WhatsApp accounts/assignments, report metadata (without phone-bearing filenames, with unique `idempotency_key` and canonical `fingerprint` constraints), attempts/events, audit and durable dispatch outbox as approved.
- DRF authentication, permission/queryset patterns and tenant-safe services.
- Device activation exchange, refresh/revocation, configuration, heartbeat and report-metadata APIs (rejecting `file_name`, validating key against canonical fingerprint, rejecting mismatches with 409).
- Development account verification override setting (`DEV_ACCOUNT_VERIFICATION_OVERRIDE`) for allowlisted test accounts, with mandatory audit logging and production rejection.
- Standardized backend developer token configuration (`WA_PLATFORM_DEVELOPER_TOKEN`), completely isolated from customer account tokens.
- Minimal admin workflow for organization/branch/device/account setup.
- Tests for tenant isolation, device ownership, account mapping and secret redaction.

**Done criteria**
- [ ] Fresh SQLite setup/migrations work locally.
- [ ] Production settings select PostgreSQL without source edits and fail closed when required config is unsafe/missing or dev override is enabled.
- [ ] Cross-tenant API/query tests pass.
- [ ] Agent cannot select organization, branch, account or `phone_number_id`.
- [ ] Activation codes expire, are single-use, hashed, rate-limited and audited.
- [ ] Report registration accepts metadata only, rejects `file_name`, validates `Idempotency-Key` against canonical fingerprint, and rejects mismatches with `409 idempotency_conflict`.
- [ ] Development verification override functions only in development for allowlisted test accounts, records audit events, and is rejected in production.
- [ ] Secrets (`WA_PLATFORM_DEVELOPER_TOKEN`, account tokens) absent from responses and logs.
- [ ] Unknown WhatsApp contracts remain behind interfaces; nothing invented.
- [ ] User review before Phase 2.

## Phase 2 — Windows Agent core

**Deliverables**
- Configuration validation and Windows Credential Manager/DPAPI credential storage.
- Folder watcher, stable-file detection, filename parser (recipient normalized locally), phone normalization and PDF validation.
- Data minimization: original phone-bearing filename strictly local; never transmitted to Django.
- Local source PDF retention policy: provider acceptance alone (`accepted`) MUST NOT delete the local PDF; retain on disk through all in-flight states (queued, uploading, retrying, awaiting delivery confirmation, reconciliation) to support re-upload.
- Finite, configurable source-PDF cleanup: configurable retention after confirmed delivery (`AGENT_CLEANUP_RETENTION_HOURS`, default 24h) and quarantine retention for failed reports (`AGENT_FAILED_RETENTION_DAYS`, default 14d) before best-effort file deletion; retries cancel previous eligibility; operator hold suspends cleanup.
- Pre-deletion verification checklist (terminal state, no active lease, no active retry, no operator hold, no pending reconciliation, elapsed retention timer) with SQLite persistence surviving service restarts; full-disk encryption (BitLocker) for Agent storage.
- Versioned local SQLite schema, durable queue, canonical fingerprint/dedup (`docflow_report_id` tracking), event log and restart recovery.
- Authenticated Django client, heartbeat/config sync and metadata submission (metadata-first registration order).
- Operational temporary upload TTL handling (~60 min tmpfiles operational estimate) and pre-send expiry validation.
- Pre-send re-upload renewal from retained local PDF when temporary media has expired or is nearing expiry buffer.
- Error handling for missing/corrupted source files during re-upload (`source_file_unavailable`).
- Standardized patient-facing document attachment name (`Diagnostic_Report.pdf`), validated and safe.
- Retry/backoff, error classification, quarantine and safe archive policy.
- Redacted logs and tests using temporary folders/fictional PDFs.
- Windows Service/PyInstaller packaging plan; do not claim installer readiness until tested on Windows.

**Done criteria**
- [ ] Slow copy not submitted before stability.
- [ ] Invalid file/name quarantined and never sent.
- [ ] Duplicate watcher events/restarts do not duplicate jobs or sends.
- [ ] Queue survives forced termination and resumes safely.
- [ ] Provider acceptance alone does NOT delete local PDF; source retained while awaiting delivery confirmation or reconciliation.
- [ ] Delivered/read reports arm cleanup retention timer (`AGENT_CLEANUP_RETENTION_HOURS`); failed reports retain for `AGENT_FAILED_RETENTION_DAYS`; retries cancel eligibility and operator hold suspends cleanup.
- [ ] Pre-deletion verification checklist verified; cleanup state survives Agent restarts.
- [ ] Missing source PDF on re-upload fails closed with `source_file_unavailable`.
- [ ] No phone-bearing filenames sent in API metadata or delivered to patients.
- [ ] No WhatsApp credentials on Agent.
- [ ] No PDF bytes in Agent SQLite or Django requests.
- [ ] Retry/quarantine/log-redaction tests pass.
- [ ] Windows-only behavior tested on Windows or marked unverified.

## Phase 3 — WhatsApp/media adapters and development delivery

**Deliverables**
- Adapter interfaces for account verification, media reference/upload, send, status mapping and reconciliation.
- Development-only tmpfiles adapter: multipart upload to `POST https://tmpfiles.org/api/v1/upload` (field `file`), direct-download binary URL (`/dl/`) resolution, ordinary HTML landing-page URL rejection in WhatsApp payloads, HTTPS and host validation (`TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`), operational explicit `expires_at` (~60 min TTL estimate, unconfirmed upstream guarantee), fictional-data safety flag and host allow-list.
- Pre-send media reference expiry check and re-upload renewal flow before dispatch.
- Architectural evaluation of Docflow-owned private object storage with scoped presigned upload URLs alongside platform media API.
- Development account verification override adapter path for allowlisted test accounts.
- Existing platform adapter only for confirmed/tested wrapper behavior; global developer token (`WA_PLATFORM_DEVELOPER_TOKEN`) backend-only.
- `lab_report_ready` document-header template payload with approved `en` language, configured lab variables, and standardized patient-facing attachment filename (`Diagnostic_Report.pdf`).
- Durable database outbox/dispatcher, attempt ledger and reconcile-before-resend handling. Even if media reference expired during `reconciliation_required`, reconcile prior attempt before resending.
- Fake-provider contract tests and manual sandbox runbook.
- Status callback endpoint disabled/mocked until payload/auth contract is confirmed.

**Done criteria**
- [ ] Tests cover success, 4xx/5xx, timeout, ambiguous acceptance and malformed responses.
- [ ] Ambiguous timeout becomes `reconciliation_required`, not a blind resend.
- [ ] Direct-download URL resolution from tmpfiles response validated; landing-page URL rejected.
- [ ] Expired temporary media references are detected and renewed before external send begins.
- [ ] Sender route comes from verified server-side branch assignment (or audited test-mode override).
- [ ] Development verification override tested and fails closed in production.
- [ ] Tokens absent from Agent/front-end/logs.
- [ ] tmpfiles disabled outside explicit development with fictional data only.
- [ ] API acceptance never displayed as delivery and never triggers local source deletion.
- [ ] Production media/credential/callback contracts remain explicit blockers when unconfirmed.

## Phase 4 — Dashboard and admin workflows

**Deliverables**
- Session login/logout and role-aware navigation.
- Organization/lab/branch management; device activation/revocation; account assignment/verification (displaying test-mode badge when dev override active); report list/detail, attempts, filters, health and audit screens.
- Truthful status labels and accessible empty/loading/error states.
- Confirmation/reason flows for resend, revoke and quarantine release.
- Frontend tests for role-specific rendering/API errors; backend still enforces authorization.

**Done criteria**
- [ ] No token in browser bundle/network responses.
- [ ] Crafted requests cannot cross tenant boundaries.
- [ ] Assignment/resend operations are permission-checked and audited.
- [ ] UI never claims delivery without supported evidence.
- [ ] Sensitive URLs/provider payloads not exposed in toast/errors.
- [ ] Relevant tests pass.

## Phase 5 — Production hardening and controlled pilot

**Deliverables**
- PostgreSQL integration tests and migration/backup/restore runbooks.
- Confirmed production media endpoint and secure direct-upload mechanism preserving the no-PDF-through-Django rule (evaluating platform media API vs Docflow-owned object storage with presigned URLs).
- Confirmed credential ownership/rotation, routing, status callbacks and signature verification.
- HTTPS, secure cookies/CSRF, rate limits, CORS/host configuration, secrets management, least privilege, dependency scanning, monitoring/alerts.
- Retention/deletion/privacy review, operational playbooks, incident/revocation procedures and rollback plan.
- Tested Windows installer and upgrade/recovery process.
- Controlled pilot with an explicitly approved test lab and synthetic test data where feasible.

**Done criteria**
- [ ] All production questions resolved with evidence and documented contracts.
- [ ] No real patient data on tmpfiles.org or any unapproved host.
- [ ] Production upload sends directly from Agent to approved media destination without exposing long-lived global/account credentials or passing bytes through Django.
- [ ] Production uses PostgreSQL; backups/restores verified.
- [ ] Tenant isolation, token leakage, retry, duplicate and crash tests pass.
- [ ] Delivery states match real API/callback evidence.
- [ ] Monitoring, revocation, rollback and operator procedures exercised.
- [ ] User signs off pilot readiness.

## Phase gate rule

Code existing is not enough to pass a phase. Report completed, failed, skipped and unverified criteria separately. Ask for approval at each gate; never advance automatically.
