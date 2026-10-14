# Docflow Non-Negotiable Rules (Testable)

These seven rules are release gates. Every relevant code review maps changes and tests to them.

## Rule 1 — Tenant isolation is mandatory

**Statement:** Every organization-owned object is loaded and mutated only within the authenticated user's/device's tenant scope. Never rely on frontend filtering or a client-supplied organization ID.

**Tests:** Org A cannot list/read/update/delete/resend/assign or infer Org B records by changing path, query, body or headers. Cover reports, branches, devices, account assignments, attempts and audit records at API and service/query levels.

## Rule 2 — Sender routing is server-authoritative

**Statement:** No Agent endpoint accepts `phone_number_id`, WhatsApp account ID, access token, organization ID or branch ID as sender-selection authority. Django derives tenant/branch/account from the authenticated device. Security-sensitive unknown fields must be explicitly rejected or proven to have no effect.

**Tests:** Send an Agent payload containing another account's IDs; it must reject the payload or still route only to the authenticated device's assigned account. Test cross-organization assignments.

## Rule 3 — Secrets never reach untrusted surfaces

**Statement:** Global developer token (`WA_PLATFORM_DEVELOPER_TOKEN`), account tokens, device refresh secrets and secret-manager values never appear in browser payloads, Agent config/installer, logs, exceptions, telemetry or audit text. Global platform credentials are backend-only. Account credentials are platform-managed or backend-controlled under a confirmed contract.

**Tests:** Secret-redaction tests for normal/error paths; API serialization tests prove secrets are write-only/non-readable; build/package scan checks Agent distribution; scan fixtures/config for credential patterns. Never use real tokens in tests.

## Rule 4 — PDF bytes bypass Django

**Statement:** No Django endpoint accepts/proxies PDF bytes; no PDF content is stored in Django/PostgreSQL, logs, traces or dashboard responses. Agent uploads directly to an approved media destination. Django receives metadata and a validated reference/ID only.

**Tests:** No file/binary field in report registration schema; binary requests rejected; no model stores PDF bytes; integration test observes upload directly from Agent to media destination and metadata only to Django. Production is blocked until direct-upload contract is confirmed.

## Rule 5 — Report creation and delivery are idempotent and durable

**Statement:** Every Agent report registration uses a deterministic fingerprint/Idempotency-Key and tenant-scoped unique constraints. Duplicate file events, network retries and restarts do not create duplicate sends. Submitting an existing fingerprint under a different key is rejected with a 409 conflict, never silently replayed. An ambiguous timeout transitions to `reconciliation_required`; no blind resend.

**Tests:** Duplicate event/API POST, same key/same body, same key/different body (409 conflict), same fingerprint/different key (409 conflict), concurrent requests, crash after persistence, crash after provider acceptance and lost response. Ambiguous requests cannot resend until reconciled.

## Rule 6 — Statuses reflect evidence, not assumptions

**Statement:** `accepted` means provider API acknowledged the request; it does not mean sent/delivered/read. Provider API acceptance alone MUST NOT permit deletion of the local source PDF; the source must be retained until delivery confirmation (`delivered`/`read`) or final operator resolution. `sent`, `delivered`, `read` require trusted status evidence. Duplicate/out-of-order callbacks are idempotent. Unsupported callback behavior is not fabricated.

**Tests:** API acceptance alone remains `accepted` and preserves local source PDF; duplicate callbacks don't duplicate events; delivered/read can advance when earlier events are absent; malformed/unauthenticated callbacks are rejected; history records source/timestamp.

## Rule 7 — Patient privacy, local retention, and development safety are enforced

**Statement:** tmpfiles.org runs only in explicitly enabled development with fictional data; endpoint is `POST https://tmpfiles.org/api/v1/upload` (multipart field `file`); direct-download binary URL (`https://tmpfiles.org/dl/...`) must be validated against expected host (`TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`); ordinary HTML landing-page URLs are prohibited in WhatsApp payloads. Files expire automatically after ~60 minutes (a local operational estimate, not an upstream guarantee) and must be renewed via re-upload if expired before send. Real patient data must never be uploaded there. Phone-bearing filenames are never transmitted in API metadata or logged; patient-facing WhatsApp attachments use a separate standardized filename (`Diagnostic_Report.pdf`). Local source PDFs are retained across all in-flight states (`queued`, `uploading`, `retrying`, `reconciliation_required`) and are never deleted upon provider acceptance alone; delivered/read reports become eligible for best-effort file deletion only after a configurable retention period (`AGENT_CLEANUP_RETENTION_HOURS`). Missing or corrupt source files return `source_file_unavailable`.

**Tests:** Production rejects `TEMP_UPLOAD_MODE=tmpfiles`; dev verification override rejected in production; uploader requires dev + safety acknowledgement; direct-download URL resolution validated and landing-page URL rejected; host allow-list blocks arbitrary URLs; log snapshots omit full phone/token/URL/raw filenames; expired temporary references are renewed before send; source PDF retained during in-flight and reconciliation states; invalid files are quarantined and never sent.

## Review checklist

For every PR, list applicable rules, test names/commands and outcomes, plus untested risks. If an external contract prevents a rule from being met, disable the production capability and record the blocker in `OPEN_QUESTIONS.md`.
