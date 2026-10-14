# Docflow Security Specification

## 1. Threat model

Assume a customer Windows PC can be compromised, requests can be modified, duplicate requests/callbacks occur, temporary links can be copied, and one tenant may attempt to access another tenant's reports/account. External APIs may time out after accepting a request. Security must not depend on hiding a UI control.

## 2. Tenant isolation

- `Organization` is the tenant boundary. Tenant users are authorized through explicit membership/role.
- Each Agent identity maps server-side to one active device, organization and branch. Reject/ignore client-supplied routing fields.
- Scope querysets at the data access layer before retrieving objects. Apply object-level checks on detail/update/delete/actions.
- Validate cross-table consistency: branch's lab, device's branch, assignment's account, report's device/branch and attempt's report must share the same organization.
- Use transactions for assignment changes, activation redemption, idempotency uniqueness, report and outbox creation.
- Unknown/cross-tenant IDs should return safe generic not-found where revealing existence creates risk.
- Roles and platform support access must be explicit. Privileged support actions are audited.

## 3. Device activation and credentials

- Create device in `pending_activation` before issuing a code.
- Generate cryptographically random one-time code; initial expiry 10 minutes. Store hash, not raw code. Rate-limit by IP/device/record and consume atomically once.
- Exchange only over HTTPS. Bind code to intended device/branch/org; request cannot select tenant.
- Issue short-lived access token plus rotating refresh secret. Store refresh-secret hash server-side; return raw secret once. Reuse of rotated token follows documented revocation/alert policy.
- On Windows, store refresh credential via Credential Manager or DPAPI. Never plaintext `.env`, JSON, source code, logs, registry value or bundled constant.
- Revoke refresh credentials immediately. Check device revocation per request or bound access token lifetime to documented revocation SLA.
- Audit activation/revocation/reuse without logging secrets.

## 4. WhatsApp credentials and account routing

- Global platform developer token (`WA_PLATFORM_DEVELOPER_TOKEN`) is backend-only in environment/secret manager; never expose it to frontend, Windows Agent, installer, or logs.
- Per-account Meta access tokens stay managed by the existing platform unless an approved contract explicitly requires Docflow backend custody. Never return them from APIs or logs.
- Never accept `phone_number_id`/account ID from Agent as sender selection. Resolve authenticated device -> branch -> active verified assignment -> adapter.
- `phone_number_id` is an identifier, not proof of authorization. Verify account ownership through supported provider mechanism before enabling production sends.
- **Development verification override safety:** To unblock development testing without inventing external endpoints, an explicit server setting `DEV_ACCOUNT_VERIFICATION_OVERRIDE=true` (defaults to `false`) permits verifying an allowlisted test account. Production settings must reject this override, and configuration validation must fail closed if enabled when `DOCFLOW_ENV=production`. The override is restricted to designated test identifiers (`DEV_TEST_ORGANIZATION_ID`, `DEV_TEST_ACCOUNT_ID`), cannot verify arbitrary customer accounts, and logs an audit event (`whatsapp_account_dev_verification_override`) without logging tokens. It is an internal test-mode authorization mechanism, not proof of real account ownership.
- If Docflow must store a token, use a secret manager or encryption with a key stored separately from database; define rotation/expiry/revocation and redaction.
- The platform contract is incomplete; production sending stays disabled until credential ownership/routing is confirmed.

## 5. Patient/document privacy, retention, and media security

- PDF bytes stay on Agent PC until uploaded directly to an approved destination. Django, PostgreSQL, dashboard APIs, telemetry and logs hold no PDF bytes.
- **Filename privacy and data minimization:** The local PDF filename containing the patient's phone number (e.g. `919876543210.pdf`) is strictly local to the customer machine. The Agent never transmits phone-bearing filenames or local file paths in API registration metadata or headers.
- **Delivered document filename:** The document delivered to the patient over WhatsApp uses a separate, sanitized filename (`Diagnostic_Report.pdf`), validated and safe, never the patient's phone number.
- **Source-PDF retention and cleanup lifecycle:**
  - **No deletion upon provider acceptance:** Provider API acceptance (`accepted`) alone MUST NOT permit deletion of the local source PDF. The source PDF must be retained while the report is queued, uploading, retrying, awaiting delivery confirmation (`delivered` or `read`), or undergoing reconciliation (`reconciliation_required`).
  - **Delivered/read reports cleanup:** When a report reaches confirmed delivery (`delivered` or `read`), the Agent initiates a configurable retention window (`AGENT_CLEANUP_RETENTION_HOURS`, default 24h, min 1h) before best-effort file deletion. The retention clock starts only after delivery confirmation is recorded (`cleanup_eligible_at = terminal_confirmed_at + AGENT_CLEANUP_RETENTION_HOURS`).
  - **Failed and quarantined reports retention:** Permanently failed (`failed`) and quarantined (`quarantined`) reports are moved to an isolated quarantine folder and retained for `AGENT_FAILED_RETENTION_DAYS` (default 14d, configurable 1–90d) for operator triage, retry, or deletion. The retention clock starts at the precise event when the report transitions to terminal `failed` or `quarantined`, recording `terminal_confirmed_at` and setting `cleanup_eligible_at = terminal_confirmed_at + (AGENT_FAILED_RETENTION_DAYS * 86400)`. A retry cancels and clears previous cleanup eligibility (`cleanup_eligible_at = NULL`). An operator hold (`operator_hold = 1`) suspends cleanup indefinitely across service restarts; releasing the hold recalculates eligibility.
  - **Pre-deletion verification checklist:** Before deleting any local source PDF, the Agent must verify against SQLite that: the job is in a confirmed terminal state; no active worker lease exists; no active retry is pending; no operator hold is active; no active or unresolved operation depends on the source (not in `reconciliation_required`, `uploading`, or attaching); and the retention timer has elapsed (`now >= cleanup_eligible_at`). State is persisted in SQLite across service restarts to prevent premature deletion.
  - **Best-effort file deletion and disk encryption:** Deletion of local source files is **best-effort file deletion**, not guaranteed secure erasure. File overwriting before unlinking cannot reliably guarantee erasure on modern storage devices due to SSD wear-leveling and block remapping, journaled filesystems (e.g. NTFS), copy-on-write architectures, volume snapshots (e.g. VSS), or backup systems. Full-disk encryption (such as Windows BitLocker or OS-level volume encryption) should be enabled on the Windows Agent's host storage, backed by protected encryption keys (e.g. TPM) and restrictive filesystem access controls (ACLs). Neither full-disk encryption nor best-effort file deletion alone guarantees that all copies or residual blocks of a PDF have been erased.
  - **Finite, configurable retention:** Patient documents must NOT be retained indefinitely by default.
  - **Missing or corrupt file:** If the source file is missing or corrupt when required, fail closed with error code `source_file_unavailable`. Never attempt to reconstruct the original report from a temporary media URL.
- **Temporary media lifecycle and uploader contract:**
  - tmpfiles.org is strictly fictional-test-data-only and development-only. Files on tmpfiles.org expire and are automatically deleted after approximately 60 minutes, but upstream retention is NOT guaranteed and files may be deleted earlier by the host without notice.
  - Endpoint: `POST https://tmpfiles.org/api/v1/upload` (multipart/form-data with field `file`). Pass `expire` parameter only if supported; do not claim custom expiry is guaranteed.
  - The direct-download binary URL (`https://tmpfiles.org/dl/...`) must be extracted and validated. The ordinary HTML landing-page URL (`https://tmpfiles.org/...`) MUST NEVER be passed to WhatsApp.
  - Require HTTPS and exact host allow-list (`TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`). Reject arbitrary, unexpected, or loopback hosts.
  - **Operational estimate for expires_at:** The Agent computes and stores an explicit `expires_at` timestamp based on configured development TTL (`TEMP_UPLOAD_TTL_SECONDS=3600`). This timestamp is strictly a **local operational estimate**, not an upstream provider guarantee. The 5-minute safety buffer (`TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS=300`) reduces in-flight expiry risk but cannot guarantee URL availability.
  - **Pre-send validation and fetch failure:** Before dispatch begins, verify the reference is not expired; if expired or nearing expiry (`< TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`), re-upload from retained local source and attach fresh reference. If the provider rejects the media URL, cannot fetch the document, or reports early expiry (provider-side fetch failure), handle the failure explicitly: preserve the source PDF and retry/re-upload under backoff policy.
  - **Reconcile before resend:** An ambiguous send timeout triggers `reconciliation_required`. Even if the temporary media reference expires, reconcile the prior attempt outcome before attempting any resend. Never blindly resend.
  - Fail closed if tmpfiles is enabled in production. No real patient reports, names, identifiers or real LIS samples may ever be uploaded to tmpfiles.org.
- Temporary media URLs are bearer-like secrets. Encrypt/restrict if persisted, never log, do not show in dashboard, delete when no longer needed/expired.
- Phone numbers are personal data. Restrict access, redact in lists/logs, define retention/deletion/access policy before production.
- Log opaque report/device IDs and normalized error codes. Never log report contents, absolute source paths, raw filenames, full phone numbers, credentials, auth headers, cookies, direct media URLs or raw provider payloads.
- Errors/toasts must not echo sensitive fields. Define Agent DB ACL, archive/quarantine permissions, local retention and disk-security expectations.

## 6. Transport and sessions

- HTTPS outside local development. Correct proxy settings; no insecure production requests.
- Dashboard sessions use Secure, HttpOnly and appropriate SameSite cookies; CSRF protection for unsafe requests; explicit allowed host/CORS/CSRF origins. Avoid reusable auth tokens in localStorage.
- Agent uses bearer access token over TLS; refresh token is rotated/stored securely. Rate-limit activation/refresh and sensitive admin actions.
- Production: `DEBUG=False`, strong secret key from secret storage, no default credentials, restrictive `ALLOWED_HOSTS`, safe database config and least-privilege DB user.
- Pin/update dependencies and add security/dependency scanning before launch.

## 7. Webhooks and provider responses

- Do not expose/enable unsigned callback endpoint. Obtain documented signature/auth header, payload, replay/timestamp and retry semantics.
- Authenticate before matching event to report. Deduplicate callbacks; callback cannot supply tenant routing.
- Normalize errors; don't persist raw upstream bodies. Sanitize untrusted strings before logging.
- Timeout after possible acceptance is ambiguous. No automatic retry until reliable reconciliation is possible.

## 8. Audit and incident response

Audit account assignment, development verification overrides, device activation/revocation, role/config changes, resend, quarantine release and relevant security failures. Audit metadata is allowlisted and contains no credentials/URLs/patient report body. Protect audit access and treat events as append-only.

Document lost-PC procedure: revoke device, rotate/revoke affected secrets if exposure is possible, check attempted sends, record incident. Before production, provide backup/restore, secret rotation and tenant data export/deletion runbooks.

## 9. Mandatory tests

See `TESTING.md` and `.claude/agents/`. At minimum: cross-tenant CRUD/actions, spoofed phone ID, secret serialization/logging, revocation, one-use activation, idempotency races and key-mismatch 409 rejection, authenticated callback dedupe, PDF pass-through prevention, production tmpfiles disablement, dev verification override production rejection and allowlist enforcement, media expiration and pre-send re-upload renewal, and ambiguous timeout handling.
