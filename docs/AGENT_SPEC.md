# Windows Agent Specification

## 1. Responsibility boundary

The Agent runs on a customer Windows PC near the LIS export folder. It watches files, waits for stability, validates PDF/name, normalizes recipients, creates durable local jobs, registers metadata with Docflow first, uploads directly to an approved media destination, attaches the resulting media reference to the registered report, syncs status and recovers after restart.

It must not hold WhatsApp account tokens or the global developer token, choose the sender account, generate/alter diagnostic results, store PDF bytes in SQLite, send PDF bytes to Django, build an inbox, or upload real patient files to tmpfiles.org.

## 2. Configuration

- Local settings: watch folder, SQLite path, archive/quarantine folders, Docflow base URL, secure credential-store reference, phone region (`IN` for initial India V1), stability/file-size/retry policies and log level.
- Absolute folder paths remain local and are not sent to Django by default.
- Device/branch IDs may be cached as non-secret identifiers. Refresh secret must use Windows Credential Manager or DPAPI; never plaintext JSON/.env.
- Proposed stability defaults: sample every 2 seconds, require 3 consecutive unchanged samples (size and `mtime_ns`), 120-second stability timeout. Make configurable and test against actual LIS behavior.
- Proposed max PDF size: 50 MiB until provider limits are confirmed; provider/server remain authoritative.

## 3. Stable-file algorithm

1. Watcher events are hints. Notifications may be lost/duplicated; rescan on service start and periodically.
2. Only regular files with `.pdf` extension (case-insensitive) are candidates. Ignore temporary suffixes and inaccessible files.
3. Deduplicate discovery using normalized local path/filesystem identity; do not queue another job from repeated events.
4. Wait until file can be opened read-only without a sharing violation. Sample size and `mtime_ns`; require configured identical consecutive samples spaced by the configured interval. Reset stable count if either changes.
5. If stable within timeout, validate. If not, remain pending/retry-wait with normalized error code. Do not read/upload partial files. Do not quarantine solely because an LIS takes longer than the initial default without explicit policy.
6. Validate PDF structure/signature where practical, size, calculate SHA-256; never log contents.
7. Parse recipient. Permanent invalid input becomes `quarantined`, move safely to quarantine if possible, reason code only; never send.
8. Commit local job state before network action. Only one worker claims a job using a transactional lease/atomic update.

## 4. Filename, recipient privacy, and document naming

Initial example: `919876543210.pdf`. Filename stem represents only the recipient phone number; do not infer patient name or report type from arbitrary text.

- Require `.pdf` extension ignoring case; parse basename only on the local machine.
- Allowed stem characters: digits, optional leading `+`, spaces, hyphens, periods and parentheses. Reject letters, multiple numbers, commas, suffixes like `_report`, path separators and ambiguous formats.
- Strip formatting and parse through maintained phone-number library (recommended `phonenumbers`) using configured default region `IN` for national input; require valid number and normalize to E.164, such as `+919876543210`.
- Accept valid international `+` format. A 10-digit national number is interpreted using configured region. An India country-code stem like `919876543210` must be parsed/validated, not blindly prefixed.
- Do not infer every 12-digit number is Indian. Reject invalid lengths/regions; non-India deployments require explicit country config.
- **Privacy and data minimization:** The original phone-bearing filename is strictly local to the Agent PC. The Agent NEVER transmits the phone-bearing filename or original file path to Django in report registration or any API metadata. Only normalized `recipient_phone_e164`, content hash, file size, document type, and timestamps are transmitted.
- **Separate patient-facing document filename:** The delivered attachment filename in WhatsApp is separate and standardized, such as `Diagnostic_Report.pdf` (or an administrator-configured non-identifying safe label). The patient's phone number or local path must NEVER be used as the delivered attachment filename.
- Same content + recipient + branch is duplicate by default. An intentional resend must use the audited admin resend process, not a renamed file.
- Logs must use a redacted phone such as `+91******1417` or opaque fingerprint only. Never log raw filenames, absolute paths, or full recipient phone numbers.

## 5. Local SQLite schema (logical)

Use schema versioning/migrations, transactions, foreign keys, reasonable busy timeout and safe single-worker claiming.

### `schema_migrations`
`version`, `applied_at`.

### `agent_settings`
`key`, `value`, `updated_at`. Never store refresh secrets here.

### `jobs`
- `id` UUID; `source_path` (local only, restricted); `source_basename` (sensitive, local only); `recipient_e164` (restrict/encrypt where feasible); `content_sha256`; `file_size_bytes`; `mtime_ns`.
- `idempotency_key` unique; `status` (`discovered`, `waiting_stability`, `validated`, `metadata_registering`, `metadata_registered`, `uploading`, `media_uploaded`, `media_reference_attaching`, `registered`, `retry_wait`, `reconciliation_required`, `accepted`, `delivered`, `read`, `quarantined`, `failed`, `archived`). Local statuses describe local work only; they are not provider-delivery evidence.
- `docflow_report_id` nullable (stores the registered Docflow backend report UUID); encrypted/transient `media_reference` with explicit `expires_at`; `attempt_count`, `next_attempt_at`, `lease_owner`, `lease_expires_at`, `last_error_code`, timestamps, `accepted_at`, `archived_at`.
- `terminal_confirmed_at` nullable timestamp (recorded when delivery reaches confirmed `delivered`/`read`, or when a report enters terminal `failed` or `quarantined`); `cleanup_eligible_at` nullable timestamp (`terminal_confirmed_at` + configured retention window); `cleanup_status` (`retained_in_flight`, `retention_active`, `operator_hold`, `eligible_for_deletion`, `deleted`); `operator_hold` boolean default 0 (persisted flag suspending cleanup); `deletion_verified_at` nullable timestamp.
- **Source retention policy:** The local source PDF at `source_path` is retained and kept accessible throughout the entire delivery lifecycle. Provider API acceptance (`accepted`) alone MUST NOT permit deletion of the local source PDF. The source PDF must be retained while the report is queued, uploading, retrying, awaiting delivery confirmation (`delivered` or `read`), or undergoing reconciliation (`reconciliation_required`), as well as when an expired temporary media reference requires renewal before a safe send. Deletion is permitted only after delivery confirmation (`delivered`/`read`) or final operator resolution, followed by a finite configurable retention window.
- No PDF bytes in SQLite. Unique fingerprint/key prevents duplicate watcher events.

### `job_events`
`id`, `job_id`, `event_type`, `occurred_at`, allowlisted `safe_details_json`, `error_code`.

### `processed_fingerprints`
`fingerprint` unique, `job_id`, `first_seen_at`, `last_seen_at`, optional hashed source path. Do not retain paths unnecessarily.

Protect DB file with Windows ACL/disk-security controls and define retention. Do not keep long-lived public URLs.

## 6. Fingerprint and idempotency

Use a versioned, deterministic canonical fingerprint algorithm:
`fingerprint = sha256("v1|" + branch_id + "|" + recipient_phone_e164 + "|" + content_sha256)`
encoded unambiguously with length-prefixed or delimiter-safe formatting. The fingerprint contains no raw patient name and is not an authorization secret.

- The Agent derives the `Idempotency-Key` (64 lowercase hex characters) matching this canonical fingerprint and submits it in the `Idempotency-Key` header.
- Django derives `branch_id` from the authenticated device, recomputes the canonical fingerprint, and independently validates the supplied `Idempotency-Key`.
- **Idempotency contract:**
  1. The same idempotency key and same canonical request return the existing report without creating another delivery (`duplicate: true`).
  2. The same key used with a different request returns `409 idempotency_conflict`.
  3. The same fingerprint submitted with a different key is rejected with a documented `409 idempotency_conflict` (or `409 fingerprint_key_mismatch`), rather than silently treated as a replay.
  4. A malformed key or key/fingerprint mismatch is rejected with a documented validation error.
- Database unique constraints `unique(organization_id, idempotency_key)` and `unique(organization_id, fingerprint)` prevent concurrent duplicate registrations.
- Agent-side deduplication (local SQLite `processed_fingerprints`) and server-side idempotency are separate safeguards.
- Idempotency deduplicates registrations; it does NOT guarantee exactly-once delivery to WhatsApp. Safely reconciling uncertain external send outcomes is a distinct lifecycle requirement.

## 7. Register, upload and attach reference

The order is deliberate and must match `API_CONTRACTS.md`:

1. **Register metadata first.** POST metadata only to `/api/v1/agent/reports` with a deterministic `Idempotency-Key`. No PDF bytes, media URL, `file_name`, `phone_number_id`, WhatsApp account ID, organization ID or branch ID may be in this request. The server derives tenant/account and returns a `queued` report ID only if an active, verified sender assignment is currently available.
2. **Upload second.** Use a replaceable uploader interface. In explicitly enabled development only:
   - Endpoint: `POST https://tmpfiles.org/api/v1/upload` using multipart form data with field name `file`.
   - Default lifetime and operational estimate: tmpfiles.org documents a default retention lifetime of 60 minutes (~3600 seconds). However, tmpfiles.org provides NO service-level agreement or upstream guarantee; files may be deleted earlier by the host without notice.
   - Expiration parameter: Pass the configured `expire` parameter only if supported by the current uploader contract; do not claim custom expiry is guaranteed merely because client requested it. Treat upstream retention behavior as unconfirmed and uncertain.
   - Response validation: Validate the upload response JSON (`status == "success"`, extract `data.url`).
   - Direct-download URL resolution: The raw `data.url` returned by tmpfiles is an HTML landing-page URL (`https://tmpfiles.org/{id}/{filename}`). The Agent must transform this into the direct-download URL by inserting `/dl/` (`https://tmpfiles.org/dl/{id}/{filename}`).
   - Host and scheme validation: The direct-download URL must use HTTPS and match the expected host (`TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`). Reject arbitrary, unexpected, private/loopback, or unapproved hosts.
   - NEVER pass the ordinary HTML landing-page URL to WhatsApp; only the validated direct-download URL is permitted.
   - Store the returned media reference and an explicit `expires_at` timestamp calculated from upload time and configured development TTL (`TEMP_UPLOAD_TTL_SECONDS=3600`). This timestamp is strictly a **local operational estimate**, NOT a provider guarantee. The five-minute safety buffer (`TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS=300`) reduces the risk of in-flight expiration but cannot guarantee that the URL remains available upstream.
   - This temporary upload happens strictly on the Agent-to-host path, never through Django.
3. **Attach reference third.** PUT the resulting reference to `/api/v1/agent/reports/{report_id}/media-reference` using the same device identity and documented reference idempotency key. Request payload must include explicit `expires_at` timestamp; `expires_at: null` is forbidden for temporary media. Django validates/accepts only a permitted reference and never fetches it. A successful transaction stores the protected reference, changes `queued` to `uploaded`, creates the first `DeliveryAttempt` and dispatch-outbox item, then returns status. The branch's verified assignment must still be active.
4. **Handle expiration, recovery, and re-upload before send:**
   - **Source retention:** Provider API acceptance (`accepted`) alone MUST NOT permit deletion of the local source PDF. The source PDF must be retained on disk and kept accessible while the report is queued, uploading, retrying, awaiting delivery confirmation (`delivered` or `read`), or undergoing reconciliation (`reconciliation_required`).
   - Before any send attempt begins, the delivery system checks whether the media reference has expired or is nearing expiry (within configured safety buffer threshold `TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`, default 300 seconds). Reject expired or near-expiry references.
   - If the media reference is expired or within the safety buffer, the Agent re-uploads from the retained local source PDF to obtain a fresh direct-download URL and attaches the new reference with renewed `expires_at` before dispatch proceeds.
   - If the provider rejects the media URL, cannot fetch the document, or reports that it has expired (provider-side early expiry or fetch failure): handle the failure explicitly. Preserve the source PDF and apply the defined retry policy (re-upload and attach fresh reference) or transition to `failed` for operator review if retry budget is exhausted. Never discard the source PDF on media-fetch failure.
   - If the retained local PDF is missing, corrupt, or unavailable when needed for re-upload or dispatch: transition job to `failed` with normalized error code `source_file_unavailable`, log audit/error event, and mark report `failed` requiring operator intervention. Never attempt to reconstruct the original report from a temporary URL.
   - If an upload or attachment fails, retain the local job and retry according to the defined transient backoff policy without losing the durable job.
   - **Reconcile before resend:** Never blindly retry a send when a previous attempt may already have been accepted by the provider. An ambiguous send timeout triggers `reconciliation_required`. Even if the temporary media reference expires while in `reconciliation_required`, reconcile the outcome of the earlier attempt before attempting any resend. Do not trigger a duplicate message merely because the media reference expired.
5. **Recover idempotently.** On metadata registration timeout, retry the identical metadata request with the same key. If upload succeeded but reference attachment timed out, retry the same attachment for that report; do not register a second report. If media upload itself times out ambiguously, preserve the local job and follow the uploader's documented recovery policy; do not lose the report.

- tmpfiles.org is forbidden in production, staging with real data and all real patient report flows. Fictional PDFs only.
- Production uploader needs a confirmed media-upload contract and secure direct-upload authorization. No global or long-lived account token in Agent. If the external API cannot support this, stop and report the architectural conflict.
- The server creates dispatch work only after reference attachment succeeds. No send is dispatched for a report still in `queued`.
- Provider API acceptance alone (`accepted`) MUST NOT permit deletion or archiving of the local source PDF. Retain the source file until delivery is confirmed (`delivered`/`read`) plus retention window, or operator resolves a permanent failure.

## 8. Retry/backoff classes

- **Transient:** network unavailable, reset, HTTP 429, selected 5xx, temporary DNS/provider outage. Exponential backoff with full jitter; proposed 2-second base, multiplier 2, cap 15 minutes; respect `Retry-After` and configure a retry budget.
- **Permanent input:** bad filename/phone, corrupt/empty/unsupported/oversized PDF. Quarantine; no network send.
- **Permanent configuration/auth:** revoked device or invalid configuration/credential. Pause and surface action required; do not retry rapidly.
- **Ambiguous send:** timeout/lost response after request may have arrived. Set `reconciliation_required`; query supported provider status if available. Never automatically resend without reliable evidence that prior attempt was not accepted.
- **Registration timeout:** retry same idempotency key; server returns existing report if committed.
- **Media expiry or fetch failure before/during send:** if media reference is expired or within safety buffer, or if provider reports early expiry or media fetch failure, preserve local source PDF, re-upload to obtain a fresh reference, and attach renewed reference. If source PDF missing/corrupted, mark `source_file_unavailable` and fail closed. Never reconstruct source PDF from a temporary link.
- Exhausted transient retry budget marks `failed`/operator intervention, not invalid-input quarantine by default.

## 9. Quarantine, archive, and source-PDF cleanup

- Archive/quarantine folders must not be inside a recursive watch folder. Check configuration at startup.
- Reason codes include `invalid_filename`, `invalid_phone`, `invalid_pdf`, `empty_file`, `file_too_large`, `stability_timeout_after_policy`, `source_file_unavailable`, `operator_hold`.
- Moves are collision-safe and preserve extension; if file is locked, retain durable state and retry move later. Never discard source.
- Archived/quarantined filenames use opaque job UUID, not a full patient phone number. Keep ACLs restrictive.

### Source-PDF retention and cleanup rules:
1. **No deletion upon provider acceptance:** Provider API acceptance (`accepted`) alone MUST NOT permit deletion of the local source PDF. The source PDF must be retained while the report is queued, uploading, retrying, awaiting delivery confirmation (`delivered` or `read`), or undergoing reconciliation (`reconciliation_required`), as well as when an expired temporary media reference requires renewal before a safe send.
2. **Delivered/read reports cleanup:** When a report reaches a confirmed delivery terminal state (`delivered` or `read`), the Agent records `terminal_confirmed_at` and calculates `cleanup_eligible_at = terminal_confirmed_at + AGENT_CLEANUP_RETENTION_HOURS` (default: 24 hours, minimum: 1 hour). The retention clock starts only after delivery confirmation is recorded. The source file remains intact during this retention window.
3. **Failed and quarantined reports cleanup:** Permanently failed reports (`failed`) and quarantined reports (`quarantined`) are retained for a configurable operator-retention window (`AGENT_FAILED_RETENTION_DAYS`, default: 14 days, configurable 1–90 days). The retention clock starts at the precise event when the report transitions to terminal `failed` or `quarantined`, at which point the Agent records `terminal_confirmed_at` and calculates `cleanup_eligible_at = terminal_confirmed_at + (AGENT_FAILED_RETENTION_DAYS * 86400)`. During this period, operators can inspect, correct, retry (re-queueing with a fresh attempt), or place on hold.
4. **Retry cancels cleanup eligibility:** Any retry or re-queueing of a failed or quarantined report immediately cancels and invalidates previous cleanup eligibility: set `cleanup_eligible_at = NULL` and `cleanup_status = 'retained_in_flight'`. While the report returns to an in-flight state (`queued`, `uploading`, `retrying`, etc.), the source PDF is retained. A new cleanup deadline is calculated and persisted only after a subsequent confirmed terminal outcome (`delivered`, `read`, `failed`, or `quarantined`).
5. **Operator hold suspends cleanup:** If an operator places a report on hold (e.g. for audit or dispute resolution), cleanup is suspended: set `operator_hold = 1` and `cleanup_status = 'operator_hold'`. While on hold, the cleanup worker is strictly blocked from deleting the source PDF, even if `cleanup_eligible_at` has passed. Hold state is persisted in SQLite across service restarts. When the hold is released at `hold_released_at`: if `cleanup_eligible_at` has already expired or has less than 24 hours remaining, recalculate `cleanup_eligible_at = hold_released_at + 24 hours` (or re-apply the full configured retention window); otherwise restore the original unexpired `cleanup_eligible_at`. Set `operator_hold = 0` and `cleanup_status = 'retention_active'`.
6. **Pre-deletion verification checklist:**
   Before deleting any local source PDF, the cleanup worker MUST verify against SQLite that:
   - The job is in a valid terminal state (`delivered`, `read`, or expired `failed`/`quarantined`).
   - No active worker lease exists (`lease_owner IS NULL` or lease is expired).
   - No active retry is in progress or pending.
   - No operator hold is active (`operator_hold == 0` and `cleanup_status != 'operator_hold'`).
   - No active or unresolved operation depends on the source (must NOT be in `reconciliation_required`, `uploading`, or `media_reference_attaching`).
   - The current time has reached or passed `cleanup_eligible_at`.
   If any condition fails, deletion is aborted and the file remains protected.
7. **Durable cleanup state across restarts:** The Agent persists cleanup eligibility timestamps, operator hold flags, and status (`cleanup_status`: `retained_in_flight` → `retention_active` → `operator_hold` → `eligible_for_deletion` → `deleted`) in SQLite. Agent service restarts will resume from persisted state and will never cause premature deletion.
8. **Finite, configurable retention:** Sensitive patient reports must NOT be retained indefinitely by default. Both successful delivery retention (`AGENT_CLEANUP_RETENTION_HOURS`) and failed/quarantine retention (`AGENT_FAILED_RETENTION_DAYS`) must be finite and administrator-configurable.
9. **Best-effort file deletion and disk encryption:** Deletion of local source files is **best-effort file deletion**, not guaranteed secure erasure. File overwriting before unlinking cannot reliably guarantee erasure on modern storage devices due to solid-state drive (SSD) wear-leveling and block remapping, journaled filesystems (e.g. NTFS journaling), copy-on-write (CoW) filesystems, volume snapshots (e.g. VSS), and automated backups. Therefore, full-disk encryption (such as Windows BitLocker or OS-level volume encryption) should be enabled on the Windows Agent host storage, with appropriate filesystem access controls (ACLs) and protected encryption keys (e.g. TPM). Neither disk encryption nor best-effort file deletion alone guarantees that every transient block or backup copy of a PDF has been eliminated.
10. **Missing or corrupt source file:** If a source file is missing, prematurely deleted, or corrupt when required for re-upload, verification, or dispatch, the job transitions to `failed` with standardized error code `source_file_unavailable` and flags the record for operator review. The Agent must never attempt to reconstruct the original PDF from a temporary media URL.

## 10. Restart recovery

1. Open/version/migrate SQLite, validate settings and secure credential availability.
2. Reclaim expired worker leases.
3. Reconcile `metadata_registering`, `uploading` and `media_reference_attaching` using the same metadata idempotency key/report ID, durable media reference if available, and backend report state.
4. If a temporary media reference exists for a pending job, check its `expires_at`; if expired or nearing expiry, re-upload the retained local PDF and update reference before initiating send.
5. If send could have reached provider, enter `reconciliation_required`; never issue a new send blindly.
6. Re-scan watch folder to recover missed events; fingerprint-deduplicate.
7. Resume eligible transient retries when due.

Use one active worker/service per installation unless concurrency is proven by tests. On DB corruption, stop sending and preserve DB for diagnosis; do not silently create an empty queue.

## 11. Windows Service and PyInstaller

- Run as least-privileged Windows user with only necessary LIS read and local DB/archive/quarantine write permissions.
- Graceful stop records current state, releases leases and closes DB. Configure service recovery behavior.
- PyInstaller build must not include secrets, reports, public URLs or developer tokens.
- Test install/uninstall/upgrade/restart on supported Windows version before claiming production readiness; record tested OS/Python/build versions.
