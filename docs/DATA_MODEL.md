# Docflow Data Model

Logical design only. Do not generate all models during Phase 0. Final fields/indexes/migrations need review before implementation. Use UUID primary keys for API-exposed records and UTC timestamps. **Never store PDF bytes.**

## 1. Tenancy and users

### `User`
- Use a custom Django user from the first migration (`AUTH_USER_MODEL` configured before migrations).
- Fields: `id` UUID, normalized unique `email`, `display_name`, `is_active`, `is_platform_admin`, `last_login`, `created_at`, `updated_at`.
- Django manages password hashing. Never store plaintext passwords.

### `Organization`
- Fields: `id`, `name`, unique `slug`, `status` (`pending`, `active`, `suspended`, `closed`), `timezone`, `created_at`, `updated_at`, `created_by`.
- Organization is the tenant boundary/customer account.

### `OrganizationMembership`
- Fields: `id`, `organization_id`, `user_id`, `role` (`organization_admin`, `branch_manager`, `operator`, `viewer`, `auditor`), `status`, timestamps.
- Unique `(organization_id, user_id)`. Platform-admin access is separate and audited.

### `Lab`
- Fields: `id`, `organization_id`, `name`, `code` unique within organization, `lab_type` (V1 `diagnostic`), `support_phone`, `status`, timestamps.
- A Lab is a V1 diagnostic-lab profile, not a separate tenant. Future non-lab businesses need a general business/document-sender profile or an explicit type strategy; do not mislabel invoices as lab reports.

### `Branch`
- Fields: `id`, `organization_id`, `lab_id`, `name`, `code` (choose uniqueness scope and enforce consistently), optional `address`, `support_phone`, `timezone`, `status`, timestamps.
- Lab and branch must belong to the same organization. Enforce in service/model validation and tests.

## 2. Devices and activation

### `Device`
- Fields: `id`, `organization_id`, `branch_id`, `name`, `status` (`pending_activation`, `active`, `revoked`, `disabled`), `agent_version`, `platform` (`windows` in V1), `last_seen_at`, optional restricted `last_ip`, `activated_at`, `revoked_at`, timestamps.
- Server derives tenant and branch from this record after device authentication. Never return secret material from this model.

### `DeviceActivationCode`
- Fields: `id`, `organization_id`, `branch_id`, `device_id`, `code_hash`, `expires_at`, `consumed_at`, `created_by`, `attempt_count`, `created_at`, `revoked_at`.
- Single-use, short-lived (initial default 10 minutes), hashed at rest, rate-limited, revocable and audited. Never store/log the raw code.

### `DeviceRefreshCredential` (or equivalent)
- Fields: `id`, `device_id`, `credential_hash`, `issued_at`, `expires_at`, `rotated_at`, `revoked_at`, `replaced_by_id`.
- Store a hash of the rotating refresh secret, not the raw value. Access token is short-lived.

## 3. WhatsApp accounts and assignments

### `WhatsAppAccount`
- Fields: `id`, `organization_id`, `provider_key` (initially existing platform adapter), optional `provider_account_reference`, `phone_number_id`, restricted `display_phone_number`, `display_name`, `credential_mode` (`platform_managed`, `backend_secret`, `pending_contract`), opaque `credential_secret_ref`, `status` (`pending_verification`, `verified`, `disabled`, `error`), verification timestamps, `created_by`, timestamps.
- `(provider_key, phone_number_id)` should be unique where the actual provider's uniqueness scope supports it.
- **Verification mode:** Production requires provider-confirmed verification. A development-only test verification override (`DEV_ACCOUNT_VERIFICATION_OVERRIDE=true`, default `false`) permits an explicitly allowlisted test account to transition to `verified` in development only. Production rejects this override and fails closed at startup.
- Do not store a raw token in ordinary fields. Default to platform-managed credentials until credential provisioning is confirmed. If direct account-token custody is later approved, require write-only submission, encryption with a separately held key, rotation and redaction.

### `BranchWhatsAppAssignment`
- Fields: `id`, `organization_id`, `branch_id`, `whatsapp_account_id`, `status` (`active`, `inactive`), `assigned_by`, `assigned_at`, `ended_at`.
- One active sender assignment per branch in V1, with history. Verify branch and account belong to the same organization in a transaction. Do not choose sender from Agent input.

## 4. Reports and delivery

### `Report`
- Fields: `id`, `organization_id`, `lab_id`, `branch_id`, `device_id`, `branch_assignment_id` (assignment snapshot/reference), `recipient_phone_e164` (PII, access-controlled), optional non-identifying `source_file_label` (strictly opaque; no phone numbers, patient names, or local disk paths), `document_type` (`diagnostic_report` in V1), `content_sha256`, `file_size_bytes`, `idempotency_key` (Agent-provided 64-hex key), `fingerprint` (canonical versioned SHA-256), `status`, timestamps, `accepted_at`, `delivered_at`, `read_at`, optional `expires_at`, `quarantined_reason_code`.
- **Data minimization & filename privacy:** The original phone-bearing filename is never transmitted to Django or persisted in this model. The delivered attachment filename in WhatsApp is separate and standardized (`Diagnostic_Report.pdf`), validated and safe.
- **Uniqueness & Idempotency constraints:** Unique `(organization_id, idempotency_key)` and unique `(organization_id, fingerprint)`. Replay of the same key and same canonical request returns the existing report without a second send. Submitting the same fingerprint with a different key is rejected with `409 idempotency_conflict`. Submitting the same key with different payload is rejected with `409 idempotency_conflict`.

### `MediaReference`
- Fields: `id`, `report_id`, `kind` (`development_download_url`, `provider_media_id`, `provider_upload_reference`), encrypted reference/opaque reference, `expires_at` (mandatory ISO 8601 UTC timestamp for temporary media), `created_at`, `deleted_at`.
- Holds only a temporary direct-download URL or provider media ID/reference, never bytes. A public URL is a bearer-like secret; encrypt/restrict, redact, and delete promptly. `development_download_url` is fake-data-only and dev-only, with an explicit `expires_at` derived from upload timestamp and conservative TTL (~60 min tmpfiles lifetime). This `expires_at` is strictly a local operational estimate, not an upstream provider guarantee; tmpfiles.org may purge files earlier without notice. The URL must be the direct-download binary URL (`https://tmpfiles.org/dl/...`), never the HTML landing page. Host must match `TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`. Production media ID/upload authorization is still unconfirmed.
- **Pre-send expiry, fetch failure, and re-upload recovery:** Before external dispatch starts, the system checks whether `expires_at` has expired or is nearing expiry (within `TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`, default 300s). If expired, nearing expiry, or if the provider rejects the media URL / reports early fetch failure, the Agent re-uploads from the retained local source PDF to create a fresh reference before delivery. If the source PDF is missing/corrupted, transitions to `failed` with code `source_file_unavailable`. Temporary URLs must never be used to reconstruct source PDFs.

### `DeliveryAttempt`
- Fields: `id`, `organization_id`, `report_id`, `attempt_number`, `status`, `provider_key`, optional `provider_message_id` (`wamid`/platform ID), optional `provider_request_id`, `request_started_at`, `accepted_at`, `finished_at`, normalized `error_code`, `error_category` (`transient`, `permanent`, `ambiguous`, `configuration`), `retry_after`, timestamps.
- Unique `(report_id, attempt_number)`. Index provider ID when useful; uniqueness only where provider semantics make it safe. A resend creates a new attempt; never erase previous attempt history.

### `DeliveryEvent`
- Fields: `id`, `organization_id`, `report_id`, `delivery_attempt_id`, `event_type`, `source` (`agent`, `docflow`, `platform`, `meta`, `admin`), optional `provider_event_id`, `provider_timestamp`, `received_at`, allowlisted `safe_payload_summary`, normalized `error_code`.
- Deduplicate by provider event ID or a documented stable compound key. Do not persist raw webhook payloads without a reviewed policy.

### `DispatchOutbox`
- Fields: `id`, `organization_id`, `report_id`, `delivery_attempt_id`, `event_type`, `state` (`pending`, `claimed`, `completed`, `retry_wait`, `dead_letter`), `available_at`, `claimed_at`, `claim_expires_at`, `attempt_count`, `last_error_code`, timestamps.
- Create the first `DeliveryAttempt` and matching outbox item transactionally when a valid media reference transitions the report from `queued` to `uploaded`. Persist request-start evidence before the external call. A reclaimed item with no request-start marker can be dispatched; if request start may have occurred without a conclusive result, require reconciliation rather than a blind resend. A new externally attempted retry/resend gets a new `DeliveryAttempt` and durable work item. Redis/Celery is not the source of truth.

## 5. Audit and callback idempotency

### `AuditEvent`
- Fields: `id`, `organization_id` (nullable only for platform-level action), `actor_user_id` or `actor_device_id`, `action`, `target_type`, `target_id`, `request_id`, `timestamp`, allowlisted `safe_metadata`.
- Record account assignment, test verification override (`whatsapp_account_dev_verification_override`), device activation/revocation, resend, role/config changes and relevant security failures. Never record tokens, public URLs, PDF contents or raw patient details in metadata.

### `WebhookReceipt`
- Fields: `id`, `provider_key`, `external_event_key`, `received_at`, `processed_at`, `processing_state`, safe error code.
- Unique event key for duplicate suppression. Signature/payload contract remains provider-dependent and unconfirmed.

## 6. Relationships

- `Organization` 1—N memberships, labs, branches, devices, WhatsApp accounts, reports and audit events.
- `Lab` 1—N branches.
- `Branch` 1—N devices and historical assignments; only one active assignment in V1.
- `WhatsAppAccount` 1—N assignment history rows.
- `Device` 1—N activation/refresh credential history and reports.
- `Report` 1—N media references, attempts, delivery events and dispatch outbox entries.
- Every relationship path must be tenant-consistent. A foreign key alone does not prove cross-table organization consistency.

## 7. Indexing, deletion and retention

- Index tenant ID with common list/filter columns: `(organization_id, created_at)`, `(organization_id, status)`, `device_id`, and provider message ID as appropriate.
- Do not retain/index phone numbers or filenames unnecessarily. Define access, audit and retention policy for PII.
- **Local PDF retention & cleanup lifecycle:** On the Windows Agent PC, local source PDFs are tracked in SQLite with `terminal_confirmed_at`, `cleanup_eligible_at`, `cleanup_status`, and `operator_hold`. Provider acceptance alone (`accepted`) MUST NOT permit deletion. The source PDF is retained during in-flight operations (`queued`, `uploading`, `retrying`, `reconciliation_required`). Delivered/read reports are retained for `AGENT_CLEANUP_RETENTION_HOURS` (default 24h, clock starts upon confirmed delivery) before best-effort file deletion. Failed/quarantined reports are retained for `AGENT_FAILED_RETENTION_DAYS` (default 14d, configurable 1–90d, clock starts upon transition to `failed`/`quarantined`) for operator triage before cleanup. Retries cancel previous cleanup eligibility (`cleanup_eligible_at = NULL`). An operator hold (`operator_hold = 1`) suspends cleanup indefinitely across service restarts; releasing hold recalculates eligibility. Pre-deletion checklist verifies terminal state, no active worker lease, no active retry, no operator hold, and no unresolved operation depends on the file. Host storage should use full-disk encryption (BitLocker); deletion is best-effort file deletion, not guaranteed erasure on modern flash/journaled storage. State is persisted in SQLite across service restarts.
- Prefer deactivation/soft-close for records needed for audit continuity. Define lawful retention/deletion policy for metadata, phone numbers and temporary URLs before production.
- Run migrations/schema tests on SQLite for local work and PostgreSQL before production to identify portability/concurrency differences.
