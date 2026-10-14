# Docflow Architecture Decision Log

Decisions should be append-only in spirit. If something changes, add an entry explaining what was superseded and the migration impact. Keep unresolved questions in `OPEN_QUESTIONS.md`.

## D-001 — Product name and V1 audience
- **Status:** Accepted, 2026-10-12.
- **Decision:** Product is Docflow. V1 targets diagnostic labs; core should allow later invoices/receipts/statements, but V1 workflows/templates remain diagnostic-specific.
- **Reason:** Keep future positioning open while limiting launch scope.

## D-002 — Recipient source
- **Status:** Accepted, 2026-10-12.
- **Decision:** V1 recipient is in PDF filename, initially `919876543210.pdf`; validate/normalize to E.164 using configured region.
- **Reason:** Work with current LIS exports without requiring a LIS integration; reject ambiguity rather than guess.

## D-003 — Administrator-managed WhatsApp mapping
- **Status:** Accepted, 2026-10-12.
- **Decision:** Authorized Docflow admin configures/verifies account mapping. Agent cannot choose account.
- **Reason:** Sender identity/credentials are a tenant security boundary.

## D-004 — Backend and dashboard
- **Status:** Accepted, 2026-10-12.
- **Decision:** Django + DRF; Next.js App Router, TypeScript, Tailwind, shadcn/ui. Frontend root is `dashboard/`, not `web/`.
- **Reason:** Match requested `dashboard/CLAUDE.md`; avoid duplicate frontend roots.

## D-005 — Database environments
- **Status:** Accepted, 2026-10-12.
- **Decision:** Django default SQLite for local dev; PostgreSQL in production via environment settings. Each Agent has a separate local SQLite queue.
- **Reason:** Simple local setup and production database capability; PostgreSQL integration tests required before launch.

## D-006 — PDF data plane
- **Status:** Accepted, 2026-10-12.
- **Decision:** Django stores metadata/reference only, never accepts/proxies/stores PDF bytes.
- **Reason:** Minimize sensitive-document exposure and separate control plane from data plane; production media API must support this.

## D-007 — tmpfiles only for development
- **Status:** Accepted, 2026-10-12.
- **Decision:** tmpfiles.org only for fictional PDFs in explicitly enabled development. Forbidden for real patient data and production.
- **Reason:** Public temporary hosting is not suitable for patient reports.

## D-008 — Existing inbox stays
- **Status:** Accepted, 2026-10-12.
- **Decision:** Existing WhatsApp platform handles sends/replies in its inbox; Docflow does not make another inbox.
- **Reason:** Avoid duplicating available functionality.

## D-009 — Server-authoritative routing
- **Status:** Accepted, 2026-10-12.
- **Decision:** Authenticated Agent maps to organization/branch; Django resolves active verified account. Agent can't choose org, branch, account ID or `phone_number_id`.
- **Reason:** IDs identify resources but do not grant authorization; prevent cross-tenant sends.

## D-010 — Durable database-backed dispatch
- **Status:** Accepted, 2026-10-12.
- **Decision:** Persist report/attempt/outbox state before external send. Redis/Celery may support optional tasks/wakeup but isn't sole source of truth or mandatory per-send dependency.
- **Reason:** Redis outages/restarts must not silently lose work.

## D-011 — Reconcile ambiguous sends before resend
- **Status:** Accepted, 2026-10-12.
- **Decision:** If a send may have reached provider but response is lost/timeout, enter `reconciliation_required`. Do not automatically resend until supported evidence or audited operator resolution.
- **Reason:** Avoid duplicate messages.

## D-012 — Append-only progress log
- **Status:** Accepted, 2026-10-12.
- **Decision:** `progress.md` records meaningful tasks, files changed, rationale, exact commands/tests and observed results, blockers and next step. Do not rewrite history silently.
- **Reason:** Keep Claude Code work auditable across sessions.

## D-013 — External media/credential contract not guessed
- **Status:** Open implementation gate, not accepted API contract.
- **Known:** Wrapper endpoint tested with backend-held global developer token and phone ID in path; platform developer states each account has a different phone ID and access token.
- **Unresolved:** Whether Docflow calls wrapper/global token or account-scoped tokens; how secure direct media upload works; status callback authentication and reconciliation support.
- **Rule:** Production adapter is not complete until confirmed, documented in `OPEN_QUESTIONS.md`/`WHATSAPP_ADAPTER.md`, tested and approved.

## D-014 — Development-only test account verification override
- **Status:** Development-only accepted, 2026-10-13 (production verification remains pending external confirmation).
- **Decision:** Introduce a server-side configuration `DEV_ACCOUNT_VERIFICATION_OVERRIDE` (default `false`) that allows an authorized administrator to verify an allowlisted test WhatsApp account (`DEV_TEST_ACCOUNT_ID`, `DEV_TEST_ORGANIZATION_ID`) in development only. Production settings must strictly reject this setting and fail closed at startup if enabled when `DOCFLOW_ENV=production`.
- **Reason:** Report registration requires an active, verified sender assignment. Returning `503` for verification in development blocked all development sending tests. This override provides an explicit, auditable test-mode path without inventing external verification endpoints.
- **Alternatives considered:** Fabricating an unconfirmed external verification endpoint (rejected: invents external contracts); manual database manipulation (rejected: untracked and error-prone); bypassing verification checks for all accounts (rejected: dangerous and risks accidental sends).
- **Security/reliability implications:** Gated strictly to development mode and allowlisted test account/org; fails closed in production; records an audit event (`whatsapp_account_dev_verification_override`); never logs tokens.
- **Related document paths:** `docs/API_CONTRACTS.md`, `docs/WHATSAPP_ADAPTER.md`, `docs/SECURITY.md`, `docs/ENVIRONMENT.md`, `docs/OPEN_QUESTIONS.md`.

## D-015 — Temporary media expiration, conservative TTL, and re-upload recovery
- **Status:** Confirmed, 2026-10-13.
- **Decision:** Acknowledge tmpfiles.org's ~60 minute automatic deletion policy. Require an explicit `expires_at` timestamp in all temporary media reference attachments (`expires_at: null` is forbidden for temporary media). Retain the original local PDF on the Agent PC until the delivery lifecycle reaches an explicitly safe terminal point (`accepted` or later terminal point, or explicit quarantine/archive). Before any send attempt begins, verify that the media reference has not expired or neared expiry (within configured safety threshold `TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`). If expired or nearing expiry, re-upload the retained local PDF to obtain a fresh URL and update the reference before sending. If the source file is missing or corrupted, fail closed with normalized error code `source_file_unavailable`.
- **Reason:** The previous specification used `expires_at: null`, which falsely assumed permanent media references. Files on tmpfiles.org expire in ~60 minutes, causing delivery failures on retries, restarts, or delayed sends.
- **Alternatives considered:** Assuming permanent URLs (rejected: violates upstream reality); deleting local source PDF immediately after initial upload (rejected: prevents re-upload recovery when media expires); blind resending after timeout (rejected: risks duplicate sends).
- **Security/reliability implications:** Local source PDF is safely retained for recovery; pre-send expiration checks eliminate expired link deliveries; fail-closed handling prevents sending corrupted files; tmpfiles remains strictly development-only and fictional-data-only.
- **Related document paths:** `docs/AGENT_SPEC.md`, `docs/API_CONTRACTS.md`, `docs/DATA_MODEL.md`, `docs/DELIVERY_STATE_MACHINE.md`, `docs/WHATSAPP_ADAPTER.md`, `docs/SECURITY.md`, `docs/ENVIRONMENT.md`.

## D-016 — Filename privacy minimization and patient-facing document naming
- **Status:** Confirmed, 2026-10-13.
- **Decision:** Eliminate phone-bearing filenames (e.g. `919876543210.pdf`) from the report registration API schema (`POST /api/v1/agent/reports`) and all API metadata. The Agent parses the recipient phone number locally and transmits only normalized `recipient_phone_e164`, content digest, size, document type, and timestamps. Delivered documents in WhatsApp use a separate, standardized patient-facing filename `Diagnostic_Report.pdf` (or administrator-configured non-identifying name).
- **Reason:** Adheres to data minimization principles. Transmitting phone-bearing filenames duplicated sensitive PII in API payloads, logs, and database models. Sending the patient's phone number as the delivered attachment filename compromised privacy and created a poor user experience.
- **Alternatives considered:** Transmitting original filename in API (rejected: unnecessary PII duplication); using recipient phone number as delivered PDF filename (rejected: poor privacy and UX).
- **Security/reliability implications:** Eliminates unnecessary PII transmission and storage; prevents phone numbers from leaking in file metadata or delivered attachments.
- **Related document paths:** `docs/AGENT_SPEC.md`, `docs/API_CONTRACTS.md`, `docs/DATA_MODEL.md`, `docs/SECURITY.md`, `docs/WHATSAPP_ADAPTER.md`, `docs/RULES.md`.

## D-017 — Deterministic idempotency key derivation and conflict rejection contract
- **Status:** Confirmed, 2026-10-13.
- **Decision:** Define a consistent, deterministic idempotency contract. The Agent computes a canonical versioned fingerprint `sha256("v1|" + branch_id + "|" + recipient_phone_e164 + "|" + content_sha256)` and submits it as `Idempotency-Key`. Django verifies the fingerprint against inputs and validates the supplied key. Submitting the same key and same canonical request returns the existing report (`duplicate: true`). Submitting the same key with a different request returns `409 idempotency_conflict`. Submitting the same fingerprint with a different key returns `409 idempotency_conflict` (or `409 fingerprint_key_mismatch`), rather than silently replaying. Unique database constraints `unique(organization_id, idempotency_key)` and `unique(organization_id, fingerprint)` prevent concurrent duplicate registrations.
- **Reason:** Resolves an explicit contradiction in previous specifications where the server was said to validate the key against the fingerprint, yet also said that submitting the same fingerprint with a different key would return the existing report.
- **Alternatives considered:** Silently returning existing report on key mismatch (rejected: masks agent bugs, key mismatches, or race conditions); allowing arbitrary client-generated UUIDs without fingerprint validation (rejected: fails to deduplicate repeated filesystem watcher events).
- **Security/reliability implications:** Transactional deduplication prevents duplicate reports and outbox jobs; clarifies that registration idempotency is distinct from external provider delivery reconciliation.
- **Related document paths:** `docs/AGENT_SPEC.md`, `docs/API_CONTRACTS.md`, `docs/DATA_MODEL.md`, `docs/RULES.md`, `docs/TESTING.md`.

## D-018 — Standardized token variable naming and credential separation
- **Status:** Confirmed, 2026-10-13.
- **Decision:** Standardize the backend-only global developer token environment variable name on `WA_PLATFORM_DEVELOPER_TOKEN`. Retire legacy variable names completely. Clearly distinguish the global developer token from individual customer account-specific WhatsApp access tokens.
- **Reason:** Prevents naming inconsistency and avoids conflating platform developer credentials with customer account credentials.
- **Alternatives considered:** Retaining legacy variable names (rejected: inconsistent with platform wrapper naming and ambiguous).
- **Security/reliability implications:** Global developer token is strictly backend-only secret storage, never placed on the Agent PC, frontend, installer, or logs. Customer account tokens are managed with individual lifecycles and encryption.
- **Related document paths:** `docs/ENVIRONMENT.md`, `docs/WHATSAPP_ADAPTER.md`, `docs/SECURITY.md`, `.env.example`.

## D-019 — Read-only tooling restriction for review subagents
- **Status:** Confirmed, 2026-10-13.
- **Decision:** Restrict the review subagents (`.claude/agents/security-reviewer.md` and `.claude/agents/tenant-isolation-auditor.md`) to read-only tools via YAML frontmatter `tools: Read, Grep, Glob`. Forbid file editing tools (`Edit`, `Write`), destructive commands, or repository modifications in subagent instructions.
- **Reason:** Subagents are intended solely for reviewing code and reporting findings, not modifying files or introducing unintended code edits.
- **Alternatives considered:** Prompt-only instructions without tool restrictions (rejected: prompt alone does not prevent accidental tool calls); permitting Bash (rejected: permits arbitrary shell commands without read-only enforcement).
- **Security/reliability implications:** Enforces least privilege on auditing subagents, preventing accidental or unauthorized file changes.
- **Related document paths:** `.claude/agents/security-reviewer.md`, `.claude/agents/tenant-isolation-auditor.md`, `docs/ROADMAP.md`.

## D-020 — Metadata-first registration and upload sequencing rationale
- **Status:** Confirmed, 2026-10-13.
- **Decision:** Enforce the strict sequence: (1) Register metadata with Django first (`queued`), (2) Upload document directly to media destination, (3) Attach media reference (`uploaded`). Retain the local source PDF throughout all in-flight states until confirmed delivery (`delivered`/`read`) or final operator resolution plus retention window; provider acceptance alone does not permit deletion.
- **Reason:** Establishing a durable report record in Django first provides an authoritative recovery anchor and backend report ID, validates active sender assignment before expending upload effort, eliminates orphaned media uploads, and preserves Rule 4 (PDF bytes bypass Django).
- **Alternatives considered:** Uploading first then registering metadata with media reference (rejected: creates orphaned uploads if registration fails and prevents early sender assignment validation).
- **Security/reliability implications:** Prevents orphaned media references; ensures fail-closed behavior before network upload; provides clear recovery lifecycle.
- **Related document paths:** `docs/ARCHITECTURE.md`, `docs/AGENT_SPEC.md`, `docs/API_CONTRACTS.md`, `docs/DELIVERY_STATE_MACHINE.md`.

## D-021 — Evaluation of Docflow-owned object storage for direct PDF upload
- **Status:** Pending external confirmation / architectural evaluation, 2026-10-13.
- **Decision:** Evaluate Docflow-owned private object storage (e.g. AWS S3, Cloudflare R2, Google Cloud Storage, MinIO) with short-lived presigned upload URLs as a parallel production option alongside the platform's official media API.
- **Reason:** Preserves Rule 4 (PDF bytes bypass Django) while giving Docflow full control over document lifecycle, retention, and encryption (SSE-KMS) in case the external platform's direct upload endpoint is delayed or insufficient.
- **Alternatives considered:** Relying exclusively on unconfirmed external platform media API (pending: external blocker); proxying PDF bytes through Django (rejected: violates Rule 4 non-negotiable).
- **Security/reliability implications:** Requires confirming whether WhatsApp sending platform / Meta Cloud API can ingest documents via time-bounded presigned GET download URLs. Production implementation remains blocked until confirmed.
- **Related document paths:** `docs/OPEN_QUESTIONS.md`, `docs/ARCHITECTURE.md`, `docs/WHATSAPP_ADAPTER.md`, `docs/ROADMAP.md`.

## D-022 — Source-PDF retention, delivery confirmation prerequisite, operator hold, and finite best-effort cleanup
- **Status:** Confirmed, 2026-10-13.
- **Decision:** Provider API acceptance alone (`accepted`) MUST NOT permit deletion of the local source PDF. The source PDF must be retained on the Agent PC while the report is queued, uploading, retrying, awaiting delivery confirmation (`delivered` or `read`), or undergoing reconciliation (`reconciliation_required`). When a report reaches confirmed delivery (`delivered`/`read`), the Agent initiates a configurable retention window (`AGENT_CLEANUP_RETENTION_HOURS`, default 24h, min 1h) before best-effort file deletion. Permanently failed and quarantined reports are retained for `AGENT_FAILED_RETENTION_DAYS` (default 14d, configurable 1–90d); the retention clock starts at the precise event when the report enters terminal `failed` or `quarantined`. A retry cancels previous cleanup eligibility (`cleanup_eligible_at = NULL`). An operator hold (`operator_hold = 1`) suspends cleanup indefinitely across service restarts. Before deleting any local PDF, the Agent verifies against SQLite: confirmed terminal state, no active worker lease, no active retry, no operator hold, no pending reconciliation, and retention timer elapsed (`now >= cleanup_eligible_at`). State is persisted in SQLite across service restarts. Patient data retention is finite and configurable. Deletion is best-effort file deletion, not guaranteed erasure on modern SSD/flash/journaled media; full-disk encryption (such as BitLocker) should be enabled on Windows Agent host storage. Missing or corrupt source files return `source_file_unavailable`.
- **Reason:** Provider acceptance only proves gateway receipt; message delivery to WhatsApp client may still fail or require reconciliation. Premature deletion upon acceptance leaves reports unrecoverable if delivery fails or media expires. Indefinite retention violates medical data minimization. Overwriting cannot reliably guarantee erasure on SSDs, journaled filesystems (NTFS), CoW systems, snapshots, or backups.
- **Alternatives considered:** Deleting upon provider acceptance (rejected: leaves reports unrecoverable on delivery failure); indefinite retention (rejected: violates privacy regulations and fills disk); claiming guaranteed secure erasure via file overwrite alone (rejected: technically inaccurate on modern SSD and journaled filesystems).
- **Security/reliability implications:** Eliminates data loss during delivery anomalies; ensures patient health records are retained only for bounded, configurable windows; provides best-effort file deletion with full-disk encryption without making false erasure claims on modern SSD/journaled media.
- **Related document paths:** `docs/AGENT_SPEC.md`, `docs/DELIVERY_STATE_MACHINE.md`, `docs/SECURITY.md`, `docs/DATA_MODEL.md`, `docs/RULES.md`, `docs/ENVIRONMENT.md`.

## D-023 — tmpfiles.org upload contract, direct-download URL resolution, and operational expiry estimates
- **Status:** Confirmed (development-only), 2026-10-13.
- **Decision:** Use `POST https://tmpfiles.org/api/v1/upload` (multipart/form-data with field `file`) exclusively in development with fictional data. The default retention is approximately 60 minutes, but upstream retention is not SLA-guaranteed and files may be deleted earlier by the host without notice. The Agent extracts the returned `data.url` (an HTML landing page) and transforms it into the direct-download URL by inserting `/dl/` (`https://tmpfiles.org/dl/...`). The direct-download URL is strictly validated for HTTPS and expected host (`TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`). The HTML landing-page URL is never passed to WhatsApp. The client computes an explicit `expires_at` (default 3600s with safety buffer) which is strictly a local operational estimate, not an upstream provider guarantee. Before send, expired or near-expiry references are renewed from the retained local source. If the provider rejects the media URL or fails to fetch it (provider-side fetch failure), the Agent preserves the source PDF and retries/re-uploads under backoff policy. If a send timed out (`reconciliation_required`), the Agent reconciles the attempt before resending, even if the media reference has expired.
- **Reason:** Passing the HTML landing-page URL causes WhatsApp to download HTML instead of PDF bytes, causing delivery failure. Relying on unverified custom expiry parameters risks premature upstream file deletion. Treating `expires_at` as a local estimate prevents relying on unconfirmed provider availability guarantees.
- **Alternatives considered:** Passing landing-page URL to WhatsApp (rejected: WhatsApp cannot ingest HTML viewer pages); assuming custom expiry parameter works without verification (rejected: upstream service documents fixed 60-minute lifetime); assuming 5-minute buffer guarantees availability (rejected: upstream service provides no SLA).
- **Security/reliability implications:** Prevents delivery failure on WhatsApp; prevents SSRF/arbitrary redirect risks; guarantees safe renewal without duplicate sends or loss of source PDFs on fetch failure.
- **Related document paths:** `docs/WHATSAPP_ADAPTER.md`, `docs/AGENT_SPEC.md`, `docs/SECURITY.md`, `docs/API_CONTRACTS.md`, `docs/TESTING.md`.

