# Docflow Open Questions and External Dependencies

Do not replace unknowns with assumptions to unblock coding. A question is resolved only when explicit developer confirmation or documentation/test evidence is recorded here and in the relevant contract.

## OQ-001 — Production media-upload contract

- **Question:** Exact URL, method, headers, upload format/fields, response/media ID, expiry, size/type limits, retention and errors/retries?
- **Known:** Developer said a production media endpoint will be added; tmpfiles is for development testing only with fictional data.
- **Owner:** WhatsApp platform developer.
- **Blocks:** Production media adapter and Phase 5.

## OQ-002 — Direct upload architecture options (preserving Rule 4: PDF bytes bypass Django)

- **Question:** How does the Agent upload documents directly to an approved media destination without receiving long-lived WhatsApp account tokens or the global platform developer token on the customer PC, and how does the sending platform access the resulting document?
- **Comparative evaluation of architectural options (do not assume any option is confirmed until verified with evidence):**
  1. **Option 1: Official media-upload endpoint on the existing WhatsApp platform.**
     - *Mechanism:* Platform provides a dedicated endpoint for media upload returning a provider `media_id`.
     - *Unresolved questions:* Does the platform provide an endpoint that the Agent can call directly? What credentials or scoped upload tokens are required? Does the platform return a Meta `media_id` or an internal ID?
     - *Security considerations:* The Agent PC must not hold global platform credentials (`WA_PLATFORM_DEVELOPER_TOKEN`) or long-lived account credentials. An upload mechanism must use short-lived, single-use scoped grants issued per report.
     - *Retention/deletion requirements:* What is the provider's retention period? Is there an API to delete media after delivery?
     - *Provider access:* WhatsApp Cloud API sends the document by `media_id` directly in the message payload.
  2. **Option 2: Existing platform's temporary development upload mechanism (tmpfiles.org).**
     - *Mechanism:* Agent uploads fictional PDF directly to tmpfiles.org via `POST https://tmpfiles.org/api/v1/upload` (multipart field `file`); transforms returned HTML landing-page URL (`https://tmpfiles.org/{id}/{name}`) into direct-download binary URL (`https://tmpfiles.org/dl/{id}/{name}`) and passes `/dl/...` URL in template header.
     - *Unresolved questions:* Files expire automatically after approximately 60 minutes (this is a local operational estimate, not an upstream guarantee); upstream retention is not configurable and custom `expire` parameters cannot be assumed guaranteed; upload failure rate, early purging, and availability are not SLA-backed.
     - *Security considerations:* Development-only, fictional data only. Strictly forbidden for real patient data. Public link is bearer-accessible. Direct-download binary URL is required; ordinary HTML landing page must never be passed to WhatsApp.
     - *Retention/deletion requirements:* Purged by host after ~60 minutes. Local source PDF is retained on Agent PC across all in-flight states until confirmed delivery (`delivered`/`read`) plus retention window (`AGENT_CLEANUP_RETENTION_HOURS`); provider acceptance alone does not permit deletion. Retained files undergo best-effort file deletion; host storage should use full-disk encryption (BitLocker). If temporary media expires before send begins or provider reports fetch failure, local source is re-uploaded. If a send times out, the attempt is reconciled before resending, even if the temporary media reference has expired.
     - *Provider access:* Sent as a direct-download binary link (`https://tmpfiles.org/dl/...`) in template document component; Meta fetches link at send time.
  3. **Option 3: Docflow-owned private object storage with scoped, short-lived upload URLs.**
     - *Mechanism:* Django control plane generates a short-lived presigned PUT URL (e.g. AWS S3, Cloudflare R2, Google Cloud Storage, or MinIO) scoped to the specific report UUID. The Agent uploads PDF bytes directly to private object storage using this presigned URL. PDF bytes completely bypass Django, satisfying Rule 4.
     - *Unresolved questions:* How does the WhatsApp sending platform access the document? If the platform sends via Meta Cloud API link parameter, Django can issue a short-lived presigned GET URL (e.g. valid for 15–30 minutes) for Meta to fetch during delivery. Does the WhatsApp platform accept presigned S3/GCS download URLs? Does Meta's media fetcher require specific headers, public accessibility, or IP allowlisting? Can the signed URL be revoked immediately after provider acceptance?
     - *Security considerations:* High tenant control. Documents are stored in Docflow-controlled encrypted private buckets (SSE-KMS) with access logging and strict bucket policies. No credentials reside on the Agent PC beyond the single-use, short-lived PUT URL.
     - *Retention/deletion requirements:* Docflow owns the lifecycle policy: automatic bucket expiration rules (e.g. 24 hours, 7 days, or deletion immediately upon verified delivery), supporting regulatory and privacy compliance.
     - *Provider access:* WhatsApp template message header receives a time-bounded presigned GET download URL, or the platform fetches from the private bucket via server-to-server integration.
  4. **Option 4: Delegated upload credentials or platform-side upload initiation.**
     - *Mechanism:* Existing platform generates single-use upload tokens delegated to the Agent for direct submission.
     - *Unresolved questions:* Platform developer has not confirmed whether delegated token creation is supported.
- **Status:** Unconfirmed architecture gate. Production remains blocked until an approved direct-upload path is confirmed and tested.

## OQ-003 — Token/account-routing behavior
- **Question:** Developer confirmed per-account phone-number ID and access token. Does Docflow call the wrapper using global developer token + ID in route while platform uses its customer token internally, or should Docflow use account-specific tokens? Can global wrapper token send for all authorized customer IDs?
- **Known:** A development send worked through wrapper using a global developer token. That alone does not confirm all-account routing/security semantics.
- **Owner:** Platform developer; request supported server-to-server contract, ownership enforcement and credential rotation/revocation behavior.
- **Blocks:** Production credential model and adapter completion.

## OQ-004 — Account verification
- **Question:** What provider-supported operation or trustworthy admin workflow verifies that a phone ID belongs to intended customer and is active/authorized?
- **Development resolution:** To safely unblock development sending without inventing external platform endpoints, an audited development verification override (`DEV_ACCOUNT_VERIFICATION_OVERRIDE=true`) permits allowlisted test accounts (`DEV_TEST_ACCOUNT_ID`, `DEV_TEST_ORGANIZATION_ID`) to be marked verified in development only.
- **Production gate:** Real production account verification remains unconfirmed and strictly blocked until provider-supported verification and credential-provisioning contracts are confirmed. Production settings fail closed if the development override is enabled.

## OQ-005 — Delivery status callbacks
- **Question:** Does platform forward `sent`, `delivered`, `read`, `failed` statuses? Exact payload fields/event IDs/timestamps, signature/auth header, replay rules, duplicate/order behavior and retry semantics?
- **Needed:** Redacted sample payload and webhook docs, followed by sandbox tests.
- **Blocks:** Accurate status UI and public callback endpoint.

## OQ-006 — Reconciliation/status lookup after ambiguous timeout
- **Question:** Is there a status lookup by `wamid`/request ID or reliable callback to resolve whether timed-out send was accepted?
- **Needed:** Endpoint/auth/consistency/retention and not-found semantics.
- **Blocks:** Automated resolution of `reconciliation_required`. Until answered, don't blind-resend.

## OQ-007 — Message response/error contract
- **Question:** Guaranteed success/error response fields? Is `wamid` direct Meta ID? Which codes are permanent/transient, rate limits and `Retry-After` semantics?
- **Known:** Test client returned a message ID resembling `wamid`; not all error classes tested.
- **Blocks:** Final retry/error mapping.

## OQ-008 — Template consistency
- **Question:** Is `lab_report_ready` approved/available for each customer account, and is `en` accepted consistently by the wrapper for intended production accounts?
- **Known:** User reported it approved and tested with language code `en`.
- **Needed:** Verify per account during onboarding.

## OQ-009 — Production constraints/privacy
- **Question:** File size/MIME/rate limits, media retention, document hosting constraints, local retention, legal/privacy obligations?
- **Owner:** Platform developer + business/product decision.
- **Blocks:** Final limits, retention and SLA claims.

## OQ-010 — Hosting/operations
- **Question:** Deployment target, secret manager, monitoring, backup/restore objectives, support hours and retention period?
- **Owner:** Product owner, before Phase 5.
- **Blocks:** Final deployment/runbooks, not local Phase 1.

## Resolution record format

Append date/source, question ID, confirmed behavior and API version/date, sanitized test evidence, affected docs (`WHATSAPP_ADAPTER.md`, `API_CONTRACTS.md`, `SECURITY.md`, `DECISIONS.md`), and whether the production gate is cleared. Never paste actual tokens, patient data, public report URLs or unredacted webhook payloads here.
