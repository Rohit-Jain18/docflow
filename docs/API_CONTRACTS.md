# Docflow Internal API Contracts

**Status:** Proposed internal V1 contract for future implementation, not a description of an already deployed Docflow API. Implement endpoints incrementally. The external WhatsApp media/token/status contract is separate and not confirmed.

## 1. Conventions

- Base path `/api/v1`; UTF-8 JSON only. No Django endpoint accepts PDF bytes.
- UUIDs for Docflow IDs; ISO 8601 UTC timestamps ending in `Z`.
- Accept or generate `X-Request-ID` and return it in responses; it must contain no PII/secrets.
- Pagination: `page` (default 1) and `page_size` (default 25, max 100); stable ordering by `created_at`, then ID.
- Browser APIs: secure HttpOnly Django session cookies plus CSRF checks for unsafe methods. Agent APIs: `Authorization: Bearer <short-lived-device-access-token>`. Webhook auth remains disabled until the platform signature/auth contract is confirmed.
- Agent tenant, branch and account are derived from its authenticated device. Agent request body cannot choose tenant/account routing.

### Standard error response

```json
{
  "type": "about:blank",
  "title": "Validation failed",
  "status": 400,
  "code": "validation_error",
  "detail": "One or more fields are invalid.",
  "request_id": "req_opaque_value",
  "field_errors": {"recipient_phone": ["Invalid phone number."]}
}
```

Do not echo submitted tokens, public PDF URLs, full phone numbers, sensitive request bodies or raw upstream responses in error text.

## 2. Error codes

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `validation_error` | Field/body validation failed; no side effect. |
| 401 | `authentication_required` | Missing, invalid or expired identity. |
| 403 | `permission_denied` | Authenticated but not allowed; revoked Agent also stops. |
| 404 | `not_found` | Object absent or outside scope; do not leak cross-tenant existence. |
| 409 | `idempotency_conflict` | Same key reused with different normalized request. |
| 409 | `state_conflict` | Invalid action for state, e.g. resend while ambiguous. |
| 410 | `activation_expired` | Activation code expired or already consumed. |
| 413 | `payload_too_large` | Oversized metadata body; there is no PDF-upload endpoint in Django. |
| 415 | `unsupported_media_type` | Endpoint expects JSON rather than binary upload. |
| 422 | `account_not_verified` | No active, verified sender assignment for branch. |
| 429 | `rate_limited` | Obey `Retry-After`; especially activation/refresh. |
| 502 | `provider_error` | Confirmed upstream failure; return normalized safe code. |
| 503 | `provider_unavailable` | Provider/config capability unavailable. |
| 504 | `provider_timeout_ambiguous` | Provider may have accepted; attempt becomes `reconciliation_required`. |

Never return stack traces, credentials or raw external response bodies.

## 3. Authentication endpoints

### `POST /api/v1/auth/login` — browser
- Auth: no session; rate limited; use configured CSRF/session-establishment protection.
- Request: `{"email":"admin@example.test","password":"<submitted securely>"}`.
- Response `200`: user summary `{id,email,display_name,is_platform_admin,memberships:[{organization_id,organization_name,role}]}` and secure session cookie. No long-lived browser bearer token in JSON.
- Errors: `400`, `401`, `429` using common codes.

### `POST /api/v1/auth/logout` — browser
- Auth: session + CSRF.
- Request `{}`; response `204` and server invalidates session.

### `GET /api/v1/auth/me` — browser
- Auth: session.
- Response `200`: login user summary plus safe permissions. No secrets.

### `POST /api/v1/agent/activation/exchange` — first activation
- Auth: one-time activation code; HTTPS and rate limit required.
- Request:

```json
{"activation_code":"one-time-code","installation_id":"f94fe6c0-bdbb-47ba-9f61-6d1c6ae5b1a2","agent_version":"0.1.0","platform":"windows"}
```

The code is checked against a hash, expiry, attempt limit and intended device/branch; success consumes it atomically. `installation_id` is not proof of tenant identity.

- Response `201` (tokens are shape examples):

```json
{"device":{"id":"uuid","name":"Main lab PC","status":"active","branch_id":"uuid"},"access_token":"short-lived-device-token","access_token_expires_at":"2026-10-12T10:00:00Z","refresh_token":"rotating-secret-returned-once","refresh_token_expires_at":"2026-11-11T10:00:00Z","configuration_version":1}
```

Token lifetime policy: Device access token lifetime is 10 minutes. Device refresh token lifetime is 30 days, rotating on every successful refresh. Agent stores refresh secret only in Windows Credential Manager/DPAPI. If secure storage fails, activation fails closed.
- Errors: `400`, `410`, `429`.

### `POST /api/v1/agent/auth/refresh` — Agent
- Auth: valid rotating refresh token over TLS; rate limited.
- Request `{"refresh_token":"<current-secret>"}`.
- Response `200`: new short-lived access token, rotated refresh token and expiry timestamps; old refresh token invalidated atomically.
- Errors: `401`, `409 state_conflict` on reuse/theft policy, `429`.

### `POST /api/v1/agent/auth/revoke-self` — Agent
- Auth: device access token; request `{}`; response `204`. Revoke credentials and device where policy permits. Dashboard revocation is the primary mechanism.

## 4. Admin/control-plane endpoints

Browser endpoints below use session + CSRF on unsafe methods, followed by backend role/tenant authorization. Standard list response: `{results:[...],page,page_size,total}`. Create `201`, read/update `200`, deactivation `204`/`200`. Unknown fields must not be mass-assigned.

### Organizations
- `GET /api/v1/organizations`: platform admin sees all; tenant users see only their memberships.
- `POST /api/v1/organizations`: platform admin only. Request `{name,slug,timezone}`; response safe `{id,name,slug,status,timezone,created_at}`.
- `GET /api/v1/organizations/{organization_id}`: scoped read.
- `PATCH /api/v1/organizations/{organization_id}`: allowlisted name/timezone/status-transition fields only; never reassign tenant identity.

### Labs
- `GET /api/v1/labs?organization_id=<uuid>`: optional filter for platform admin; never widens tenant scope.
- `POST /api/v1/labs`: organization admin/platform admin. Request `{organization_id?,name,code,lab_type:"diagnostic",support_phone?}`. For tenant admin derive/check organization from membership.
- `GET /api/v1/labs/{lab_id}`.
- `PATCH /api/v1/labs/{lab_id}`: allowlisted name/code/support_phone/status only.

### Branches
- `GET /api/v1/branches?lab_id=<uuid>`.
- `POST /api/v1/branches`: request `{lab_id,name,code,address?,support_phone?,timezone?}`; derive organization from the Lab.
- `GET /api/v1/branches/{branch_id}`.
- `PATCH /api/v1/branches/{branch_id}`: allowlisted non-identity fields; reparenting is not a generic PATCH.

### WhatsApp accounts and assignments
- `GET /api/v1/whatsapp-accounts`: only accounts visible to authorized admins; no tokens.
- `POST /api/v1/whatsapp-accounts`: admin only. Proposed body `{display_name,provider_key:"existing_platform",provider_account_reference?,phone_number_id,display_phone_number?}`. Response safe metadata and `pending_verification`. **Do not accept/return raw token until the credential contract is approved.**
- `GET /api/v1/whatsapp-accounts/{account_id}`: safe metadata only.
- `POST /api/v1/whatsapp-accounts/{account_id}/verify`: admin action. In production, returns `503 provider_unavailable` because real verification contract is unconfirmed (OQ-004) and production sends remain blocked without verified provider ownership. In development ONLY: when the server-side configuration `DEV_ACCOUNT_VERIFICATION_OVERRIDE=true` is explicitly set (defaults to `false`), an authorized administrator can verify an allowlisted test account. Production settings must strictly reject this override, and configuration/startup must fail closed if enabled in production (`DOCFLOW_ENV=production`). The override functions only for an explicitly allowlisted test organization and account (`DEV_TEST_ORGANIZATION_ID`, `DEV_TEST_ACCOUNT_ID`) and cannot verify arbitrary accounts. An audit event is recorded (`whatsapp_account_dev_verification_override`); no tokens are logged. This development override is a test-mode authorization mechanism, not proof of real account ownership.
- `POST /api/v1/branches/{branch_id}/whatsapp-assignment`: request `{whatsapp_account_id}`. Validate both records belong to same org; transactionally deactivate previous active assignment, create new assignment and audit. Response `{branch_id,whatsapp_account_id,status:"active",assigned_at}`.
- `DELETE /api/v1/branches/{branch_id}/whatsapp-assignment`: deactivate current mapping; preserve history and audit.

### Devices
- `GET /api/v1/devices?branch_id=<uuid>`: authorized visible devices.
- `POST /api/v1/devices`: admin; request `{branch_id,name}`; organization derived from branch; response device `pending_activation`.
- `POST /api/v1/devices/{device_id}/activation-code`: admin; request `{expires_in_seconds?:600}` within server bounds. Response displays code once with expiry; never logs or returns it again. Audit issuance without raw code.
- `POST /api/v1/devices/{device_id}/revoke`: admin, idempotent; request `{reason_code}`; immediately revoke refresh credential and either check device revocation per request or bound access-token lifetime.
- `GET /api/v1/devices/{device_id}` and `PATCH /api/v1/devices/{device_id}`: safe metadata only; allowlist fields. No credentials returned.

## 5. Agent endpoints

All except activation exchange require device Bearer token. Tenant and branch are derived from authenticated device.

### `GET /api/v1/agent/config`
Response `200` shape (values are initial defaults, not fixed commitments):

```json
{"device_id":"uuid","branch_id":"uuid","configuration_version":1,"watch_folder_policy":"locally_configured","filename_pattern":"phone_number.pdf","default_phone_region":"IN","stability_sample_seconds":2,"stability_required_samples":3,"stability_timeout_seconds":120,"max_pdf_size_bytes":52428800,"archive_policy":"after_provider_accepted","quarantine_policy":"move_invalid_files"}
```

No credentials, other-tenant data or unnecessary patient data. Watch-folder absolute paths stay local by default.

### `POST /api/v1/agent/heartbeat`
- Request `{agent_version,installation_id,service_state,queue_counts:{queued,retry_wait,quarantined},last_successful_job_at?}`. No raw paths, phone numbers or tokens.
- Response `{server_time,configuration_version,device_status}`. Revoked/disabled device gets `403`; Agent stops sending.

### `POST /api/v1/agent/reports`
- Headers: device Bearer token and required `Idempotency-Key: <64 lowercase hex characters>`.
- Key is derived from the versioned canonical fingerprint: `fingerprint = sha256("v1|" + branch_id + "|" + recipient_phone_e164 + "|" + content_sha256)`. The server derives `branch_id` from the authenticated device, recomputes this fingerprint from normalized inputs, and independently validates the supplied `Idempotency-Key`. Since PDF bytes never reach Django, Django cannot independently prove that the submitted content digest matches the file bytes; the Agent computes that digest locally and this limitation remains explicit. No raw phone number or patient name is in the key.
- Request shape (metadata only; no phone-bearing filenames, no local paths, no media URL and no PDF bytes):

```json
{"recipient_phone_e164":"+919876543210","content_sha256":"64-lowercase-hex-characters","file_size_bytes":183420,"document_type":"diagnostic_report","agent_created_at":"2026-10-12T10:10:00Z"}
```

Data minimization rule: Do NOT transmit the original phone-bearing filename to Django. If an identifier is required for diagnostics, an optional non-identifying label (e.g. `client_tracking_label`) containing neither a phone number nor patient name may be included. Delivered WhatsApp documents use a separate standardized attachment filename (`Diagnostic_Report.pdf`), validated and safe.

The server validates metadata/digest/size, derives organization/branch/device/account server-side, and confirms the branch has an active, verified sender assignment (or active development test verification override) before accepting the job. If not, return `422 account_not_verified` and do not register/upload the file. It creates a durable report record in `queued` state. The Agent then uploads directly to the approved media destination and attaches a validated reference in the next call. This ordering lets the Agent recover safely if upload/registration is interrupted.
- Response `202`: `{report_id,status:"queued",duplicate:false,created_at}`.
- **Idempotency contract:**
  - Same idempotency key + same canonical request returns the existing report without creating a second delivery (`duplicate:true`).
  - Same key used with a different normalized request returns `409 idempotency_conflict`.
  - Same canonical fingerprint submitted with a different key is rejected with `409 idempotency_conflict` (or `409 fingerprint_key_mismatch`), rather than silently treated as a replay.
  - Malformed keys or key/fingerprint mismatches return `400 validation_error` or `409 idempotency_conflict`.
  - Unique database constraints `unique(organization_id, idempotency_key)` and `unique(organization_id, fingerprint)` prevent concurrent duplicate registrations.
- Errors include `400,401,403,409,413,415,422,429`. Security-sensitive fields `phone_number_id`, `whatsapp_account_id`, `organization_id`, `branch_id`, `file_name` and any media URL in this initial creation request must be rejected; strict schema validation is enforced.

### `PUT /api/v1/agent/reports/{report_id}/media-reference`
- Auth: device Bearer token; report must belong to the authenticated device's branch/tenant. `Idempotency-Key` can be the report fingerprint or a documented reference-attachment key.
- Request shape (development example only; explicit ISO 8601 UTC expiration required):

```json
{"media_reference":{"kind":"development_download_url","url":"https://tmpfiles.org/dl/example/fictional-sample.pdf","expires_at":"2026-10-12T11:00:00Z"}}
```

`development_download_url` is accepted only in explicitly enabled development with exact host allow-list (`TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`) and fictional data. The URL must be the direct-download binary URL (`https://tmpfiles.org/dl/...`), never the ordinary HTML landing page (`https://tmpfiles.org/...`). An explicit `expires_at` timestamp is mandatory for temporary media references; a null expiration timestamp (`null`) is rejected for temporary hosts. Note that `expires_at` is a **local operational estimate** based on configured development TTL (`TEMP_UPLOAD_TTL_SECONDS=3600`) and is NOT an upstream provider guarantee; tmpfiles.org may purge files earlier without notice. Production requires the confirmed provider media-reference/direct-upload contract. Django must not fetch arbitrary URLs or accept file bytes. Same reference replay is idempotent; a different reference attached after dispatch has started returns `409 state_conflict` unless a specific safe replace flow is documented.
- **Pre-send expiry, fetch failure, re-upload recovery, and retention:** Before external dispatch starts, the system validates that the media reference is not expired or nearing expiry (within configured buffer threshold `TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`). If expired or nearing expiry before a send attempt begins, the Agent re-uploads from the retained local source PDF and attaches a fresh reference with updated `expires_at` before dispatch proceeds. If the provider rejects the media URL, cannot fetch the document, or reports early expiry (provider-side fetch failure), the system preserves the local source PDF and applies the defined retry policy (re-upload and attach renewed reference). If the local source file is missing or corrupted, the report fails closed with safe error code `source_file_unavailable`. Provider API acceptance alone (`accepted`) does NOT permit deletion of the local source PDF; the Agent retains the source file until confirmed delivery (`delivered`/`read`) plus retention window, or operator resolution. If a previous send attempt timed out or is in `reconciliation_required`, the system reconciles the attempt outcome before attempting any re-upload or resend.
- On success, revalidate that the report’s server-side branch assignment is still active and verified, validate the reference and transition report `queued` → `uploaded`; store the protected reference and create the first `DeliveryAttempt` plus its dispatch-outbox item in the same transaction. If the assignment was revoked after report registration, do not dispatch; return a safe `422 account_not_verified` and leave the report blocked for reconfiguration/operator handling according to the documented implementation policy. The dispatcher must persist request-start evidence before the external send. Return `200` `{report_id,status:"uploaded",duplicate:false}`.
- Errors: `400,401,403,404,409,422,429`.

### `GET /api/v1/agent/reports/{report_id}`
- Device reads only reports available to its own branch/tenant.
- Response `200`: `{report_id,status,created_at,updated_at,last_safe_error_code,delivery_attempt:{attempt_number,status,provider_message_id?,updated_at,last_safe_error_code?},next_action?}`. Omit `delivery_attempt` when none exists. Hide recipient/media URL; inaccessible records return safe `404`.

### `GET /api/v1/agent/reports?status=...&since=...`
- Paginated metadata/status reconciliation list scoped to the Agent's branch/device. Response: `{results:[{report_id,status,created_at,updated_at,last_safe_error_code}],page,page_size,total}`. No media references or raw phone numbers.

## 6. Report and audit endpoints

- `GET /api/v1/reports`: tenant-scoped list; filters `branch_id`, `status`, `created_after`, `created_before`, `document_type`. Implement recipient search only if exact and permission-limited.
- `GET /api/v1/reports/{report_id}`: safe metadata, attempt history and timeline; never bytes or raw public URL.
- `POST /api/v1/reports/{report_id}/resend`: privileged admin. Request `{reason_code,confirmation:true}`. Reject if prior attempt is ambiguous; no recipient/account/template override. Create a new attempt with new server key and audit event.
- `GET /api/v1/delivery-attempts/{attempt_id}`: tenant-scoped safe detail; no raw provider response.
- `GET /api/v1/audit-events`: admin/auditor only, scoped/paginated/redacted.

## 7. Status callback endpoint — blocked pending external contract

Proposed route: `POST /api/v1/webhooks/whatsapp/status`. Do not enable public callback processing until the platform developer supplies payload, authentication/signature header, timestamp/replay rules and retry behavior. Never invent a signature header or trust unsigned callbacks. Then document exact shape, verify authenticity, deduplicate with `WebhookReceipt`, and match only through a provider message ID/account association. Callback never chooses tenant routing.

## 8. Health endpoints

- `GET /health/live`: public liveness only; no secrets or environment dump.
- `GET /health/ready`: internal readiness; restrict via network policy or return a generic safe result. Do not reveal detailed infrastructure publicly.

## 9. Endpoint inventory and canonical safe object shapes

This inventory supplements the endpoint-specific requests above. Any endpoint not fully specified by these examples is a proposed internal contract and must be implemented consistently; it is not an already deployed API. Every list uses the standard paginated envelope unless noted, and every response is tenant-scoped and secret-free.

| Method | Route | Auth | Request | Success response |
|---|---|---|---|---|
| `POST` | `/api/v1/auth/login` | Public, rate-limited | Email/password JSON | `200` user summary + session cookie |
| `POST` | `/api/v1/auth/logout` | Browser session + CSRF | `{}` | `204` |
| `GET` | `/api/v1/auth/me` | Browser session | None | `200` user summary + safe permissions |
| `POST` | `/api/v1/agent/activation/exchange` | One-time code | Activation exchange JSON | `201` safe device + one-time-issued credentials |
| `POST` | `/api/v1/agent/auth/refresh` | Rotating refresh credential | Refresh token JSON | `200` rotated credentials |
| `POST` | `/api/v1/agent/auth/revoke-self` | Device access token | `{}` | `204` |
| `GET/POST` | `/api/v1/organizations` | Session + scoped role | POST: `{name,slug,timezone}` | List envelope / `201` organization summary |
| `GET/PATCH` | `/api/v1/organizations/{organization_id}` | Session + tenant/platform scope | PATCH allow-listed fields | `200` organization summary |
| `GET/POST` | `/api/v1/labs` | Session + scoped role | POST: `{organization_id?,name,code,lab_type,support_phone?}` | List envelope / `201` lab summary |
| `GET/PATCH` | `/api/v1/labs/{lab_id}` | Session + tenant scope | PATCH allow-listed fields | `200` lab summary |
| `GET/POST` | `/api/v1/branches` | Session + scoped role | POST: `{lab_id,name,code,address?,support_phone?,timezone?}` | List envelope / `201` branch summary |
| `GET/PATCH` | `/api/v1/branches/{branch_id}` | Session + tenant scope | PATCH allow-listed fields | `200` branch summary |
| `GET/POST` | `/api/v1/whatsapp-accounts` | Authorized admin | POST safe account metadata; no raw token unless future approved contract changes | List envelope / `201` pending-verification summary |
| `GET` | `/api/v1/whatsapp-accounts/{account_id}` | Authorized tenant admin | None | `200` safe account summary |
| `POST` | `/api/v1/whatsapp-accounts/{account_id}/verify` | Authorized admin | `{}` or provider-approved verification payload only | `200` verified summary in test-mode override, or safe `503` in production while unconfirmed |
| `POST/DELETE` | `/api/v1/branches/{branch_id}/whatsapp-assignment` | Authorized admin | POST `{whatsapp_account_id}`; DELETE no body | `200` assignment summary / `204` |
| `GET/POST` | `/api/v1/devices` | Session + scoped role | POST `{branch_id,name}` | List envelope / `201` device summary |
| `GET/PATCH` | `/api/v1/devices/{device_id}` | Session + tenant scope | PATCH allow-listed metadata | `200` device summary |
| `POST` | `/api/v1/devices/{device_id}/activation-code` | Authorized admin | `{expires_in_seconds?:600}` | `201` one-time code + expiry (never retrievable again) |
| `POST` | `/api/v1/devices/{device_id}/revoke` | Authorized admin | `{reason_code}` | `200` revoked device summary |
| `GET` | `/api/v1/agent/config` | Device token | None | `200` device-specific safe configuration |
| `POST` | `/api/v1/agent/heartbeat` | Device token | Heartbeat JSON | `200` server time/version/status |
| `POST` | `/api/v1/agent/reports` | Device token | Metadata-only report JSON (no phone filename) + Idempotency-Key | `202` queued report |
| `PUT` | `/api/v1/agent/reports/{report_id}/media-reference` | Device token | Validated media-reference JSON with explicit expires_at | `200` uploaded report |
| `GET` | `/api/v1/agent/reports/{report_id}` | Device token, same branch/device scope | None | `200` safe report metadata/status |
| `GET` | `/api/v1/agent/reports` | Device token | Optional status/since/page filters | `200` paginated safe report metadata |
| `GET` | `/api/v1/reports` | Session + tenant scope | Optional documented filters | `200` paginated report summaries |
| `GET` | `/api/v1/reports/{report_id}` | Session + tenant scope | None | `200` report + attempts + timeline, no media URL |
| `POST` | `/api/v1/reports/{report_id}/resend` | Authorized role + CSRF | `{reason_code,confirmation:true}` | `202` new attempt summary or safe conflict |
| `GET` | `/api/v1/delivery-attempts/{attempt_id}` | Session + tenant scope | None | `200` safe attempt summary |
| `GET` | `/api/v1/audit-events` | Admin/auditor + tenant scope | Optional filters | `200` paginated redacted audit summaries |
| `POST` | `/api/v1/webhooks/whatsapp/status` | **Disabled until auth contract confirmed** | Unknown until provider supplies schema | No public processing before contract approval |
| `GET` | `/health/live` | Public, minimal | None | `200` `{status:"ok"}` |
| `GET` | `/health/ready` | Internal/restricted | None | `200` `{status:"ready"}` or safe `503` |

Canonical safe summaries (illustrative required fields; implementations may add reviewed non-sensitive fields):

- **Organization:** `{id,name,slug,status,timezone,created_at}`.
- **Lab:** `{id,organization_id,name,code,lab_type,support_phone,status,created_at}`; omit `organization_id` if not needed by a tenant-scoped client.
- **Branch:** `{id,lab_id,name,code,address,support_phone,timezone,status,created_at}`.
- **Device:** `{id,branch_id,name,status,agent_version,last_seen_at,activated_at,revoked_at}`. Never return credential hashes/tokens or activation codes except the one-time issuance response.
- **WhatsApp account:** `{id,display_name,provider_key,provider_account_reference,phone_number_id,display_phone_number,status,verified_at}`. Never include access token or secret reference.
- **Assignment:** `{id,branch_id,whatsapp_account_id,status,assigned_at,ended_at}`.
- **Report:** `{id,branch_id,device_id,document_type,status,file_size_bytes,created_at,updated_at,accepted_at,delivered_at,read_at,last_safe_error_code}`. Do not include raw media URL, full phone number or local file path in standard lists. A tightly permissioned detail response may expose recipient only when justified, audited and redacted in logs.
- **Delivery attempt:** `{id,report_id,attempt_number,status,provider_message_id,request_started_at,accepted_at,finished_at,safe_error_code}`; provider IDs may need masking based on policy. Never return raw upstream body.
- **Audit event:** `{id,action,target_type,target_id,actor_type,timestamp,request_id,safe_summary}`.

## 10. Idempotency and status semantics

Agent report creation requires a transactional organization-scoped key matching the canonical fingerprint `sha256("v1|" + branch_id + "|" + recipient_phone_e164 + "|" + content_sha256)`. Database constraints `unique(organization_id, idempotency_key)` and `unique(organization_id, fingerprint)` prevent duplicate registrations. Submitting an identical key and canonical payload returns the existing report (`duplicate: true`); submitting the same key with different payload returns `409 idempotency_conflict`; submitting an existing fingerprint with a different key returns `409 idempotency_conflict`. Idempotency deduplicates registrations but does not guarantee exactly-once external delivery to WhatsApp. Each outbound attempt gets a persistent internal attempt ID and provider idempotency key only if provider actually supports one. Callback dedupe uses provider event ID or a documented compound key. API message ID proves acceptance only; ambiguous timeout stays `reconciliation_required` until supported status lookup/callback or audited operator resolution.
