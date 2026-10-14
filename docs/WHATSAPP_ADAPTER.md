# WhatsApp Adapter Specification

## 1. Goal

Use a narrow server-side adapter for account verification, media preparation, template sending and reconciliation. Keep provider-specific behavior out of report processing and the Windows Agent. The existing platform inbox remains the reply surface; Docflow does not build an inbox.

## 2. Known development facts

- Existing base URL: `https://wa.kizieemedia.com/api/developer`.
- Tested/documented route: `POST /api/developer/v25.0/{PHONE_NUMBER_ID}/messages`.
- The development test used `Authorization: Bearer <global developer token>` from an environment variable. Keep it backend-only; never ship it to a customer PC or frontend.
- Platform developer confirmed every account has a different `phone_number_id` and access token.
- `lab_report_ready` is reported approved and manually tested; Utility category, English, document header, two body variables.
- User reports successful document delivery during development; the Python client also returned a message ID resembling a WhatsApp `wamid`. Retain detailed recipient/response only in private test records, not source fixtures. A `wamid`/accepted API response proves acceptance, not delivery status by itself.
- The first tmpfiles page URL returned HTML; successful test used a direct download URL with `/dl/...` and a PDF filename.

## 3. External contracts NOT confirmed

Do not invent or assume:
1. Production media upload URL, method, content type, multipart fields, headers, response/media ID, expiry, limits or errors.
2. Whether Docflow calls the wrapper using global developer token for each permitted customer ID, or must use per-account access tokens directly.
3. How account tokens are provisioned, rotated, expired and revoked, or whether they remain entirely within the existing platform.
4. Whether wrapper verifies that phone-number ID and token/customer match, and how cross-account requests are rejected.
5. How account ownership/connection is verified.
6. Whether wrapper forwards `sent`/`delivered`/`read`/`failed` callbacks, payload fields, IDs/timestamps, signature/header, replay rules and retry behavior.
7. Whether a provider message-status lookup exists to reconcile ambiguous timeouts.
8. Whether returned `wamid` is a direct Meta message ID or wrapper-specific ID.

Track answers in `OPEN_QUESTIONS.md`; production capabilities remain disabled until confirmed.

## 4. Proposed adapter interface

Conceptual interface; exact names can be chosen in Phase 3:
- `verify_account(account_assignment) -> VerificationResult`
- `prepare_media(report, local_pdf_path_or_direct_upload_grant) -> MediaReference`
- `send_template(account_assignment, recipient_e164, template_name, language_code, document_reference, filename, body_parameters, attempt_id) -> SendResult`
- `reconcile_send(account_assignment, attempt) -> ReconciliationResult` (only if a documented provider lookup exists)
- `parse_status_event(authenticated_event) -> NormalizedStatusEvent`

Inputs derive from server-side records. Agent never provides account ID, `phone_number_id` or access token as routing authority. Credentials are injected server-side or remain managed by the provider after contract confirmation. Logs are redacted.

## 5. Development wrapper request

A development/sandbox adapter may call:

`POST https://wa.kizieemedia.com/api/developer/v25.0/{PHONE_NUMBER_ID}/messages`

Headers:

```http
Authorization: Bearer ${WA_PLATFORM_DEVELOPER_TOKEN}
Content-Type: application/json
```

**Developer token vs account tokens:**
- Standardize the backend-only global developer token environment variable on `WA_PLATFORM_DEVELOPER_TOKEN`. Legacy variable names are retired and must not be used.
- The global developer token (`WA_PLATFORM_DEVELOPER_TOKEN`) exists solely in backend-controlled secret storage and is never exposed to the frontend, Windows Agent config, code, installer, or logs.
- Customer account-specific WhatsApp access tokens are separate secrets managed per account. If account custody is confirmed, they are encrypted and protected as individual secrets, separate from the global developer token.
- The phone-number ID comes from a server-side verified branch assignment, never the Agent body. Do not assume the global token supports every customer ID until tested/confirmed by the platform developer. If account-scoped tokens or a different flow is required, update this document before implementation.

## 6. Approved V1 template

- Name: `lab_report_ready`
- Category: Utility
- Tested language code: `en`
- Header: Document
- Body:

  `Your diagnostic report from {{1}} is ready.`

  `Please find your report attached.`

  `If you have questions about the report, please contact the laboratory at {{2}} for assistance.`

`{{1}}` is the verified lab/display name; `{{2}}` the verified support phone. Both come from backend configuration, not Agent input. Do not put patient results in the message body. Future invoice clients require a separate approved template and scope decision.

**Patient-facing document filename:**
The document attached to the WhatsApp template header must use a standardized, validated patient-facing filename: `Diagnostic_Report.pdf` (or an administrator-configured safe non-identifying name). The local LIS filename containing the patient's phone number must NEVER be sent as the attachment filename in the WhatsApp payload.

Illustrative payload shape, fictional values only:

```json
{
  "messaging_product": "whatsapp",
  "to": "+919876543210",
  "type": "template",
  "template": {
    "name": "lab_report_ready",
    "language": {"code": "en"},
    "components": [
      {"type":"header","parameters":[{"type":"document","document":{"link":"https://tmpfiles.org/dl/example/fictional-sample.pdf","filename":"Diagnostic_Report.pdf"}}]},
      {"type":"body","parameters":[{"type":"text","text":"Example Diagnostics"},{"type":"text","text":"+91 9000000000"}]}
    ]
  }
}
```

Never commit a real sample file URL, real recipient or token.

## 7. Development media adapter

- Agent first registers metadata with Django (`queued`), then uploads a fictional PDF directly to tmpfiles.org and attaches the direct URL and explicit `expires_at` to the report. Django receives only metadata/reference, never bytes.
- **tmpfiles.org upload contract:**
  - Endpoint: `POST https://tmpfiles.org/api/v1/upload` using multipart form data with field name `file`.
  - Default lifetime and operational estimate: tmpfiles.org documents a default retention lifetime of 60 minutes (~3600 seconds). However, tmpfiles.org provides NO SLA or guarantee; files may be deleted earlier by the host without notice.
  - Expiration parameter: Pass the configured `expire` parameter only if supported by the current uploader contract; do not claim custom expiry is guaranteed merely because the client requested it. Upstream retention must be treated as unconfirmed and uncertain.
  - Response parsing & URL resolution: Parse JSON response (`status == "success"` and extract `data.url`). The raw `data.url` is an HTML landing page (`https://tmpfiles.org/{id}/{filename}`). The Agent must transform this into the direct-download URL by inserting `/dl/` (`https://tmpfiles.org/dl/{id}/{filename}`).
  - URL & host validation: The direct-download URL must use HTTPS and match the expected host (`TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`). Reject arbitrary uploader-returned URLs, non-HTTPS schemes, private/loopback targets, or unexpected domains.
  - **No HTML landing-page URLs:** Never pass the ordinary HTML landing-page URL (`https://tmpfiles.org/{id}/{filename}`) to WhatsApp. The WhatsApp platform requires direct access to PDF bytes; passing an HTML viewer URL will cause media fetch failure.
  - Expiration estimate: Calculate and persist an explicit `expires_at` timestamp based on upload time and configured TTL (`TEMP_UPLOAD_TTL_SECONDS=3600`). This timestamp is strictly a **local operational estimate**, NOT an upstream provider guarantee. The five-minute safety buffer (`TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS=300`) reduces the risk of in-flight expiry but cannot guarantee availability.
- **Pre-send expiry check, fetch failure, and re-upload recovery:**
  - Before initiating any external send attempt, the dispatcher/Agent checks if the media reference has expired or is nearing expiry (within `TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`, default 300 seconds). Reject expired or near-expiry references.
  - If expired or nearing expiry before send begins, the Agent re-uploads from the retained local source PDF, derives a fresh direct-download URL, and attaches the fresh reference with renewed `expires_at` before dispatch proceeds.
  - If the provider rejects the media URL, cannot fetch the document, or reports that it has expired (provider-side early expiry or fetch failure): handle the failure explicitly. Preserve the source PDF and apply the defined retry policy (re-upload and attach renewed reference) or mark for operator review if retry budget is exhausted. Never discard the source PDF on media-fetch failure.
  - If the retained local source PDF is missing or corrupted, fail closed with normalized error code `source_file_unavailable`. Never attempt to reconstruct the original report from a temporary URL.
- **Reconcile before resend:** If an external send timed out or the attempt outcome is ambiguous (`reconciliation_required`), DO NOT blindly resend, even if the temporary media reference has expired. Reconcile the status of the previous attempt first to avoid duplicate messages.
- Require explicit development environment and fictional-data safety opt-in; production config must refuse this mode. Never upload real patient reports to tmpfiles.org.
- Backend must not fetch arbitrary URLs; do not log full URLs. Treat URL as a bearer-like file secret.
- Keep behind an interface; temporary host behavior/retention is not a production contract.

## 8. Production media/security gate

Production should send PDF bytes directly from Agent to approved media destination. The platform must provide a documented mechanism that ensures: PDF bypasses Django; global token never reaches Agent; long-lived account tokens are not shipped/plaintext on PCs; upload is authorized for the correct account and narrowly scoped where possible; response returns usable media ID/reference; limits/expiry/errors/retries are documented.

Options under evaluation (see `OPEN_QUESTIONS.md`):
1. Official platform media-upload endpoint with scoped upload tokens.
2. Docflow-owned private object storage with scoped presigned upload URLs (Agent uploads direct to S3/GCS without passing bytes through Django).
3. Delegated upload credentials or platform-side upload initiation.

If no approved direct-upload mechanism exists, stop and seek explicit architecture decision; do not proxy bytes through Django.

## 9. Result/error normalization and verification

Normalize provider results to `{accepted, provider_message_id?, provider_request_id?, safe_error_code?, retry_classification}`. Don't persist raw upstream bodies. Accepted response -> `accepted`, never `delivered`. Ambiguous timeout -> `reconciliation_required`.

**Account verification policy:**
- In production: mark account `verified` only after a provider-supported verification or documented trustworthy admin workflow proves phone-number ownership. Entering an ID alone is not proof. If verification contract is unknown, account remains `pending_verification` and production sending is blocked.
- In development ONLY: to unblock development sending flows while production platform contracts remain unconfirmed, an explicit development override (`DEV_ACCOUNT_VERIFICATION_OVERRIDE=true`, default `false`) permits an authorized administrator to verify an allowlisted test account (`DEV_TEST_ACCOUNT_ID`, `DEV_TEST_ORGANIZATION_ID`). This override must fail closed in production, cannot verify arbitrary accounts, logs an audit event (`whatsapp_account_dev_verification_override`), and is an audited test-mode authorization mechanism, not proof of real account ownership.
