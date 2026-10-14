# Docflow Testing Strategy

## 1. Test layers

- **Backend unit:** model invariants, phone normalization, fingerprinting, status-transition validator, secret redaction, adapter normalization.
- **DRF API:** auth/roles/tenant isolation, schema/error codes, idempotency, device activation/revocation, assignment and report endpoints.
- **DB integration:** SQLite locally; PostgreSQL integration before production. Do not assume SQLite locking/constraint behavior is identical.
- **Agent unit:** filename parsing, stable file, PDF validation, fingerprint, retry/backoff, quarantine, SQLite schema and log redaction.
- **Agent integration:** temporary folders, fake server/uploader/provider, duplicate events, locked/copying files, process restart/network recovery.
- **Adapter tests:** fake HTTP responses and sanitized requests; no real credentials.
- **Frontend tests:** role-based UI, API errors, disabled resend during ambiguity, no token/URL leakage, accessibility smoke tests.
- **Security tests:** all seven rules in `RULES.md`.
- **Manual sandbox:** fictional sample PDF and explicitly controlled test recipient/account only.

## 2. Expected commands after scaffolding

Phase 0 must inspect actual tooling; these examples are not claimed to work yet.

### Backend (`backend/`)
- `python -m venv .venv`
- `python -m pip install -r requirements/development.txt`
- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- `python manage.py migrate`
- `python manage.py test`

If pytest is selected, document pytest/coverage and choose one authoritative test runner.

### Dashboard (`dashboard/`)
- `npm ci`
- `npm run lint`
- `npm run typecheck` (add script if selected)
- `npm test` (once configured)
- `npm run build`

Use the repository's one package manager/lockfile, not mixed package managers.

### Agent (`agent/`)
- Create/activate virtual environment.
- `python -m pip install -e ".[dev]"` if packaging supports it.
- `python -m pytest`
- Formatting/lint/type checks once configured, e.g. Ruff and mypy/pyright.
- Windows Service/installer tests run on Windows or remain explicitly marked unverified.

### Repository checks
- `git diff --check`
- Secret/dependency scans once tooling is chosen.
- Ensure no actual credentials, patient data, public temp URLs or real PDF samples are committed.
- CI includes PostgreSQL integration tests before production.

## 3. Mandatory tests

### Tenant isolation
- Org A cannot list/read/update/resend Org B reports.
- Device A cannot access Org B records.
- Cross-tenant Branch ↔ Lab and Branch ↔ WhatsApp assignment rejected.
- `organization_id`, `branch_id` or `device_id` query cannot widen scope.
- Tenant audit history cannot reveal another tenant's activity.

### Device lifecycle
- Activation code expires, is single-use and stored hashed.
- Concurrent attempts cannot redeem the same code twice.
- Rate limiting works without revealing tenant/device existence.
- Revocation stops requests within documented SLA.
- Old rotated refresh credential cannot be reused silently.

### Agent file handling and privacy
- `919876543210.pdf` and supported region formats normalize correctly on local PC.
- Ambiguous/invalid phone, wrong extension, corrupt/empty/oversized PDF is quarantined.
- Slow file copy is not submitted before stable samples pass.
- Duplicate watcher events/restart rescan create one job.
- Queue survives forced termination at state boundaries.
- Archive/quarantine is collision-safe; delete disabled by default.
- **Filename privacy:** Original phone-bearing filenames are never transmitted to Django in report registration or any metadata API; schema rejects `file_name` field.
- **Patient-facing filename:** Attachment filename delivered in WhatsApp template is standardized (`Diagnostic_Report.pdf`), validated and safe, containing no recipient phone number.
- **Source-PDF retention and cleanup lifecycle:**
  - Provider API acceptance alone (`accepted`) MUST NOT permit deletion of the local source PDF.
  - Source PDF must remain accessible while the report is `queued`, `uploading`, `retrying`, awaiting delivery confirmation (`delivered` or `read`), or undergoing reconciliation (`reconciliation_required`).
  - Delivered/read reports arm cleanup timer (`AGENT_CLEANUP_RETENTION_HOURS`, default 24h); retention clock starts only after delivery confirmation is recorded (`cleanup_eligible_at = terminal_confirmed_at + AGENT_CLEANUP_RETENTION_HOURS`); source file remains intact until timer elapses.
  - Failed-retention deadline calculation: for permanently failed (`failed`) or quarantined (`quarantined`) reports, retention clock starts at the precise event when transitioning to `failed`/`quarantined` (`cleanup_eligible_at = terminal_confirmed_at + (AGENT_FAILED_RETENTION_DAYS * 86400)`).
  - Retry cancelling previous cleanup eligibility: retrying or re-queueing a failed/quarantined report resets `cleanup_eligible_at = NULL` and `cleanup_status = 'retained_in_flight'`. Retains source PDF while in-flight; new cleanup deadline calculated only after subsequent confirmed terminal outcome.
  - Operator hold suspending cleanup: placing a report on hold (`operator_hold = 1`, `cleanup_status = 'operator_hold'`) blocks deletion regardless of elapsed time; releasing hold re-evaluates `cleanup_eligible_at` with grace window if expired.
  - Hold and retention state surviving restart: `cleanup_eligible_at`, `cleanup_status`, and `operator_hold` persisted in SQLite survive Agent restart and prevent premature deletion.
  - Pre-deletion verification checklist: confirms terminal status, no active worker lease, no active retry, no operator hold, no pending reconciliation (`reconciliation_required`), and `now >= cleanup_eligible_at` before deletion.
  - Best-effort file deletion: deletion is verified as best-effort file deletion (unlinking with optional best-effort byte overwrite). Full-disk encryption (BitLocker) must be enabled on Agent storage. Overwrite alone is not claimed as guaranteed erasure on modern SSD/flash/journaled filesystems.
  - Missing/corrupt source PDF: fails closed with normalized code `source_file_unavailable`; temporary URLs are never used to reconstruct source files.

### Idempotency and registration concurrency
- Same key + same canonical request returns existing report with no new outbox/send (`duplicate: true`).
- Same key + different normalized request returns `409 idempotency_conflict`.
- Same canonical fingerprint submitted with a different key returns `409 idempotency_conflict` (or `409 fingerprint_key_mismatch`), never silently treated as a successful replay.
- Malformed key returns `400 validation_error`.
- Concurrent duplicate registration requests are prevented by transactional database constraints: `unique(organization_id, idempotency_key)` and `unique(organization_id, fingerprint)`.
- Registration retry uses the same key.
- Explicit resend requires permission, reason, audit event and new attempt.

### Temporary media uploader contract, expiration, and recovery
- Multipart form upload to `POST https://tmpfiles.org/api/v1/upload` with field `file`.
- Response parsing validates `status == "success"` and extracts `data.url`.
- Direct-download URL resolution parses landing-page URL (`https://tmpfiles.org/{id}/{name}`) and transforms to direct-download binary URL (`https://tmpfiles.org/dl/{id}/{name}`).
- Reject ordinary HTML landing-page URL in WhatsApp payload; only direct-download `/dl/` URL is accepted.
- Enforce HTTPS and expected host (`TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`); reject unexpected hosts, loopback/private IPs, and arbitrary schemes.
- Handle malformed responses: non-JSON, missing fields, HTTP error codes, or `status != "success"`.
- Explicit `expires_at` timestamp is a local operational estimate (~60 min default); not an upstream guarantee. Custom `expire` parameter is not assumed guaranteed.
- An expired temporary reference before first send is detected and renewed via re-upload from retained local PDF before send attempt starts.
- A temporary reference nearing its configured expiry buffer (`TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`, default 300s) triggers rejection and re-upload renewal before dispatch.
- Provider-side early expiry or media fetch failure: provider rejects URL or cannot fetch PDF; test verifies Agent preserves local source PDF, handles error explicitly, and retries via re-upload and reference renewal under backoff policy.
- Failed re-upload triggers transient backoff and retry without losing durable job.
- Attachment failure triggers retry for the same report without registering a duplicate report.
- Agent restart while a temporary reference exists verifies expiration and re-uploads if expired.
- If retained local PDF is missing, corrupt, or unavailable when re-upload is needed, job fails closed with normalized code `source_file_unavailable`. Reconstructing source PDF from temporary URL is strictly prohibited.
- **Reconcile before resend:** Timeout after a send may have been accepted transitions to `reconciliation_required`; no blind resend, even if the temporary media reference has expired while in `reconciliation_required`.
- No real patient report may be sent to tmpfiles.org; fail closed if `TEMP_UPLOAD_MODE=tmpfiles` in production.

### WhatsApp and account verification
- Development account verification override is enabled only in development (`DOCFLOW_ENV=development` and `DEV_ACCOUNT_VERIFICATION_OVERRIDE=true`); production settings reject override and fail closed at startup.
- Development override creates an audit event (`whatsapp_account_dev_verification_override`) without logging tokens.
- Development override functions only for allowlisted test organization/account (`DEV_TEST_ORGANIZATION_ID`, `DEV_TEST_ACCOUNT_ID`) and cannot verify arbitrary customer accounts.
- Production account verification returns `503 provider_unavailable` and blocks production sending until provider contract is confirmed.
- Agent-supplied phone-number/account/org/branch IDs cannot alter sender route.
- Correct server-side branch assignment is used.
- Global developer token (`WA_PLATFORM_DEVELOPER_TOKEN`) and account tokens never enter Agent bundle/config, frontend payload, or logs.
- There is only one documented name for the global developer token (`WA_PLATFORM_DEVELOPER_TOKEN`); no obsolete or alternate token variable names exist.
- API acceptance alone does not mark delivered; distinct states `accepted`, `sent`, `delivered`, `read`.
- Duplicate/out-of-order status events are idempotent and never downgrade known later status.
- Unsigned/invalid callbacks rejected once contract is confirmed; don't invent signature test before then.
- Arbitrary media URLs rejected; tmpfiles unavailable outside safe dev mode.

### PDF privacy and data minimization
- Agent registration contains metadata only (no PDF bytes, no media URL, no phone in filename).
- Django never accepts/stores/proxies PDF content.
- Logs/traces/test failures contain no temp URL, tokens, full phone numbers, raw filenames, or PDF content.
- No real patient report or real patient destination used in tests.

### Specification and tooling consistency
- Review subagents (`.claude/agents/*.md`) have strictly read-only tools (`tools: Read, Grep, Glob`) with no `Edit`, `Write`, or unrestricted `Bash`.
- No obsolete product identifiers or legacy report ID prefixes remain in Docflow-owned specifications.
- All diagrams (Mermaid) and prose documentation follow the same metadata-first delivery sequence.

## 4. Test data rules

Use synthetic names/numbers, synthetic results and fictional PDFs. Do not commit a PDF from a real LIS. Add clear fictional watermark to visually relevant fixtures. Use placeholders such as `TEST_TOKEN_NOT_VALID`, never real tokens.

## 5. Reporting results

For each phase report exact commands, environment, exit status, passed/failed/skipped tests and checks not run/why. Do not say “all tests passed” based only on compilation. Record outcomes in `progress.md`.
