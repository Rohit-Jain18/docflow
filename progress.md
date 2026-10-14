# Docflow Progress Log

> **Append-only log.** Log every implementation task or cohesive change batch, including why it was done. Do not rewrite history; add a dated correction if needed. Do not log every keystroke, but never omit a substantive change, failed check, reverted approach or blocker. Record only commands actually executed and observed results. Never include secrets, patient-identifying data, raw tokens, activation codes or public report URLs.

## Entry format

- **Timestamp (local time + timezone):** ISO 8601
- **Phase / task:** Phase number and short identifier
- **Goal:** Intended outcome
- **Inspection:** Relevant files/state reviewed
- **Changes:** Files created/modified/deleted
- **Why:** Rationale tied to a requirement or decision
- **Commands run:** Exact commands actually executed
- **Tests/checks:** Exact commands and observed outcomes; say `not run` with reason when appropriate
- **Security/reliability checks:** Relevant tenant, secret, data-flow, idempotency or retry implications
- **Decisions:** Accepted decisions only, otherwise `none`
- **Open issues/blockers:** Known unknowns and owner/next action
- **Next step:** One concrete next step

---

## 2026-10-12T16:26:27+05:30 — Planning pack prepared (initial entry; validation added below)

- **Phase / task:** Pre-Phase 0 / documentation bootstrap
- **Goal:** Prepare source-of-truth specifications before application development begins.
- **Inspection:** Used the confirmed decisions in the planning conversation. No existing Docflow application repository was supplied or inspected.
- **Changes:** Created the product/engineering specifications, root and folder Claude instructions, security and tenant-isolation auditor subagents, reusable slash commands, placeholder environment file and ignore rules. No product application code was written.
- **Why:** Establish consistent requirements and label unresolved WhatsApp contracts before delegating implementation.
- **Commands run:** The planning documents were written using file-generation commands in the working container. A complete command-by-command implementation log does not exist for each generation operation; do not infer one. The explicit validation command and outcomes are recorded in the following validation entry and `docs/PACK_VALIDATION.md`. Claude Code must record its own exact commands when it starts Phase 0.
- **Tests/checks:** Application tests are not applicable because no application exists yet. Do not represent this pack validation as application or security testing.
- **Security/reliability checks:** Prohibit real patient data on tmpfiles.org, global/account token exposure to customer PCs, PDF bytes through Django, client-selected sender routing and blind resend after ambiguous timeout.
- **Decisions:** Docflow; V1 diagnostic labs; filename recipient; admin-managed WhatsApp assignment; SQLite development; PostgreSQL production; frontend root `dashboard/`.
- **Open issues/blockers:** Media-upload contract, account credential provisioning, wrapper-vs-account-token sending behavior, status callbacks and webhook verification remain unresolved in `docs/OPEN_QUESTIONS.md`.
- **Next step:** Open the extracted project root in Claude Code and run Phase 0 only.


## 2026-10-12T16:26:27+05:30 — Documentation consistency validation and correction

- **Phase / task:** Pre-Phase 0 / pack validation
- **Goal:** Catch missing files, malformed Markdown structure, contradictory delivery-flow instructions and accidental secret material before handing the pack to Claude Code.
- **Inspection:** Read the architecture, API contracts, data model, Agent specification, delivery state machine, security rules, dashboard spec and open questions; compared the two-step metadata/upload/reference flow across documents.
- **Changes:** Clarified the Mermaid architecture and Agent instructions so metadata registration happens first, fictional development upload happens second, and media-reference attachment happens third. Aligned `queued`/`uploaded` semantics with initial attempt/outbox creation. Added a route inventory and canonical safe response shapes to the proposed internal API contract. Explicitly recorded that Django cannot independently verify an Agent-supplied content hash against bytes it never receives. Added `infrastructure/README.md`; no application code was generated.
- **Why:** Keep API flow, persistence and recovery semantics aligned; prevent the Agent and backend from making incompatible sequencing assumptions or inventing an external credential/media contract.
- **Commands run:** `python /tmp/validate_docflow_pack.py` (first attempt exposed a validation-script path bug; it was fixed and rerun). The successful rerun reported **46 checks passed, 0 issues** before the final edits recorded in this entry; rerun again after this entry is authored and update this log if results differ.
- **Tests/checks:** Initial static pack validation passed required-file presence, 27 Markdown readability/fence checks, seven-rule count, roadmap phases 0–5, important architecture/security terms, status/outbox consistency, environment placeholder checks, and absence of app scaffolding. This did not test application behavior. Final post-edit validation is pending at the time of writing.
- **Security/reliability checks:** The production media/credential/callback contracts remain open. No raw tokens were added. tmpfiles remains fictional-data-only and development-only. PDF bytes still bypass Django. Ambiguous-send timeout still blocks blind resend.
- **Decisions:** No product decisions changed. Documented API contract details are proposals for implementation, not claims about deployed endpoints.
- **Open issues/blockers:** See `docs/OPEN_QUESTIONS.md` (OQ-001 through OQ-010).
- **Next step:** Run the final pack validator, inspect its report, create and integrity-test the ZIP, and then start Phase 0 only after the user opens it in Claude Code.


## 2026-10-12T16:30:00+05:30 — Audit note on initial entry

- **Phase / task:** Pre-Phase 0 / progress-log correction
- **Goal:** Keep the activity log factually accurate while preserving the initial entry.
- **Inspection:** Compared the initial progress entry with the final file list and command sequence.
- **Changes:** Clarified that `docs/PACK_VALIDATION.md` and `infrastructure/README.md` were added after the initial entry. The initial entry's wording implied the validation report existed at the moment of the initial entry; that implication was inaccurate. The report now identifies the final validation result and this correction preserves the original entry for auditability.
- **Why:** The progress log must be trustworthy rather than silently rewriting earlier history.
- **Commands run:** File inspection and edit via the working-container shell/Python; the exact reproducible pack-validation command is `python scripts/validate_pack.py` from the pack root.
- **Tests/checks:** Final pack validation is run after all document edits and recorded in the next entry. No application tests exist at this stage.
- **Security/reliability checks:** No secrets or patient data added.
- **Decisions:** None.
- **Open issues/blockers:** WhatsApp contract questions remain in `docs/OPEN_QUESTIONS.md`.
- **Next step:** Finish post-edit validation, archive integrity check, and save the planning pack.


## 2026-10-12T16:30:41+05:30 — Final consistency checks corrected and passed

- **Phase / task:** Pre-Phase 0 / validator refinement and final document pass
- **Goal:** Verify the final planning pack after clarifying report queue semantics and the metadata → upload → media-reference order.
- **Inspection:** Reviewed the validator predicates against `ARCHITECTURE.md`, `API_CONTRACTS.md`, `DATA_MODEL.md`, `AGENT_SPEC.md` and `DELIVERY_STATE_MACHINE.md`.
- **Changes:** Updated the repeatable `scripts/validate_pack.py` so its expected `queued`-state text matched the refined status definition; expanded the validator to check API inventory consistency, Agent sequencing, absence of stale reversed sequencing, and the metadata-hash limitation. Added results/caveats to `docs/PACK_VALIDATION.md`. No product application code was generated.
- **Why:** The validator should check stable semantics, not brittle exact prose that becomes stale after a deliberate wording improvement.
- **Commands run:** `python /mnt/data/docflow-planning-pack/scripts/validate_pack.py`. The successful run printed `Checks passed: 51` and `Issues: 0` and exited successfully. An immediately preceding run printed one failed queued/uploaded/outbox assertion because the validator expected older wording; that assertion was corrected before the successful rerun.
- **Tests/checks:** 51 planning-pack checks passed, zero issues; 28 Markdown files read and checked for non-empty UTF-8 content, balanced fenced-code markers and local Markdown links. This is documentation validation only. No application tests were run because the pack intentionally contains no application code.
- **Security/reliability checks:** No detected literal developer token or live secret assignment in `.env.example`; all seven testable rules remain present; tmpfiles is dev-only for fictional files; PDF bytes bypass Django; ambiguous send timeouts remain `reconciliation_required` and are not blindly retried.
- **Decisions:** No product decisions changed. API routes remain proposals; external WhatsApp media/credential/status contracts remain unconfirmed.
- **Open issues/blockers:** `docs/OPEN_QUESTIONS.md`, OQ-001 through OQ-010.
- **Next step:** Verify the archived pack contents and ZIP integrity, then save the archive for the user.

## 2026-10-12T16:31:30+05:30 — Planning pack archived and integrity-checked

- **Phase / task:** Pre-Phase 0 / deliverable packaging
- **Goal:** Produce a portable ZIP with the entire Docflow source-of-truth pack at a `docflow/` project root.
- **Inspection:** Inspected the archive's top-level paths and checked the validator summary before saving.
- **Changes:** Packaged the planning documents, root/folder Claude instructions, security and tenant-isolation review agents, slash commands, environment placeholders, progress log, and repeatable validator as `Docflow_Planning_Pack.zip`. No application code or real credentials were added.
- **Why:** Give Claude Code a single repository-shaped folder to inspect before implementation starts.
- **Commands run:** `python scripts/validate_pack.py` (from `/mnt/data/docflow`): passed with 51 checks and zero issues; `zip -qr /mnt/data/Docflow_Planning_Pack.zip docflow`; `unzip -t /mnt/data/Docflow_Planning_Pack.zip` reported no errors; `sha256sum /mnt/data/Docflow_Planning_Pack.zip` produced a hash for this archived version.
- **Tests/checks:** ZIP integrity passed. Archive content listing confirmed the expected root and core documents. These are pack checks, not application tests.
- **Security/reliability checks:** Confirmed no detected literal developer token or live secret assignment in `.env.example`; external WhatsApp unknowns remain documented rather than guessed.
- **Decisions:** None changed.
- **Open issues/blockers:** WhatsApp media upload, credential provisioning/routing, account verification, status callbacks and reconciliation remain production blockers in `docs/OPEN_QUESTIONS.md`.
- **Next step:** Extract/open `docflow/` in Claude Code and allow Phase 0 repository inspection only. Review its findings before approving Phase 1.

## 2026-10-13T00:37:00+05:30 — Planning pack audit and consistency corrections

- **Phase / task:** Pre-Phase 0 / documentation audit and consistency correction
- **Goal:** Audit and correct Docflow planning pack across 8 identified architectural, security, and lifecycle contradictions before Claude Code Phase 0 development begins.
- **Inspection:** All project Markdown files (`docs/*.md`, root and per-folder `CLAUDE.md`, `.claude/agents/*.md`, `.claude/commands/*.md`), `.env.example`, `scripts/validate_pack.py`.
- **Changes:**
  - `.claude/agents/security-reviewer.md` & `.claude/agents/tenant-isolation-auditor.md`: Restricted frontmatter to `tools: Read, Grep, Glob`; added explicit instructions prohibiting code edits, writes, destructive commands, or repository modifications.
  - `docs/AGENT_SPEC.md`: Standardized local filename stem extraction without transmitting phone-bearing filenames; set patient-facing document name to `Diagnostic_Report.pdf`; replaced obsolete legacy report ID prefix with `docflow_report_id`; documented deterministic idempotency key derivation and key-mismatch conflict behavior (`409 idempotency_conflict`); added tmpfiles.org ~60 min auto-deletion handling, explicit non-null `expires_at`, pre-send expiry buffer check, local source file retention until terminal state, re-upload renewal flow, and `source_file_unavailable` error handling.
  - `docs/API_CONTRACTS.md`: Documented development account verification override (`DEV_ACCOUNT_VERIFICATION_OVERRIDE=true`, fail-closed in production, allowlisted org/account only); removed `file_name` from `POST /api/v1/agent/reports`; clarified idempotency replay vs conflict (`409 idempotency_conflict`); updated `PUT /.../media-reference` example with concrete ISO 8601 `expires_at` timestamp and pre-send renewal semantics.
  - `docs/DATA_MODEL.md`: Documented dev verification override mode on `WhatsAppAccount`; removed `source_filename` from `Report` model and added optional opaque `source_file_label` and `Diagnostic_Report.pdf` patient-facing name; added unique constraints `unique(organization_id, idempotency_key)` and `unique(organization_id, fingerprint)`; documented `expires_at` on `MediaReference`; added `whatsapp_account_dev_verification_override` audit event.
  - `docs/DELIVERY_STATE_MACHINE.md`: Documented validated `expires_at` on `uploaded` state, pre-send expiry validation, re-upload renewal from retained source, and `source_file_unavailable` failure code; preserved ambiguous send outcome reconciliation.
  - `docs/WHATSAPP_ADAPTER.md`: Standardized global developer token on `WA_PLATFORM_DEVELOPER_TOKEN` (retiring legacy token variable names); set delivered document name to `Diagnostic_Report.pdf`; documented tmpfiles ~60 min auto-deletion, non-null `expires_at`, and pre-send re-upload; added evaluation of Docflow-owned object storage; documented dev verification override.
  - `docs/SECURITY.md`: Documented `WA_PLATFORM_DEVELOPER_TOKEN` backend secret isolation; fail-closed constraints for dev verification override; filename privacy (no phone numbers in transmitted/logged filenames); patient-facing document naming; tmpfiles ~60 min TTL renewal; audit events and security test requirements.
  - `docs/RULES.md`: Updated Rule 3 (`WA_PLATFORM_DEVELOPER_TOKEN`), Rule 5 (deterministic idempotency and key-mismatch conflict rejection), Rule 7 (tmpfiles ~60 min expiry renewal, filename privacy).
  - `docs/OPEN_QUESTIONS.md`: Added comprehensive 4-way comparative evaluation in OQ-001/OQ-002 (Platform media upload vs tmpfiles dev upload vs Docflow-owned object storage with presigned URLs vs delegated credentials), documenting unresolved questions, security, retention, and provider access for each; updated OQ-004 to record dev verification override resolution while production remains open.
  - `docs/DECISIONS.md`: Added architectural decisions D-014 through D-021 covering dev verification override, temporary media expiration/recovery, filename privacy, idempotency contract, standardized token naming, read-only subagents, metadata-first order, and object storage evaluation.
  - `docs/ENVIRONMENT.md` & `.env.example`: Added `DEV_ACCOUNT_VERIFICATION_OVERRIDE`, `DEV_TEST_ORGANIZATION_ID`, `DEV_TEST_ACCOUNT_ID`, `TEMP_UPLOAD_TTL_SECONDS`, `TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`, `WHATSAPP_PATIENT_FACING_FILENAME`; standardized on `WA_PLATFORM_DEVELOPER_TOKEN`.
  - `docs/TESTING.md`: Expanded Section 3 with mandatory tests covering all 8 required correction areas.
  - `docs/ROADMAP.md`: Updated Phases 0–5 deliverables and acceptance criteria to incorporate all corrected requirements.
  - `docs/DASHBOARD_SPEC.md`, `backend/CLAUDE.md`, `agent/CLAUDE.md`, `docs/ARCHITECTURE.md`: Synchronized token names, dev verification override, metadata-first flow rationale, and media expiry handling.
  - `scripts/validate_pack.py`: Fixed Windows UTF-8 decoding; added stdout UTF-8 reconfigure; added mechanical checks for subagent read-only tools, token standardization, obsolete identifiers, non-null expiration timestamps, and decision log completeness.
  - `docs/PACK_VALIDATION.md`: Updated validation report for 2026-10-13 run with 60 passed checks.
- **Why:** Resolve contradictions between specifications, unblock development sending without weakening production security, prevent sensitive patient data exposure in filenames, ensure robust recovery from temporary file expiration, eliminate idempotency ambiguities, and restrict code review subagents to read-only operation.
- **Commands run:** `python scripts/validate_pack.py` (invoked in workspace root `c:\Rohit's-Workspace\Docflow`).
- **Tests/checks:** Mechanical pack validator executed with exit code 0; 60 checks passed, 0 issues across all 28 Markdown files. Application runtime tests (Django, Next.js, Windows Agent) were NOT run because application code does not exist yet (pre-development planning phase).
- **Security/reliability checks:** Development verification override fails closed if activated in production; override works only for designated allowlisted test organization/account; no phone-bearing filenames transmitted or logged; patient-facing filename standardized on `Diagnostic_Report.pdf`; temporary media references have explicit non-null `expires_at` and are refreshed before sending; same fingerprint with different idempotency key rejected with `409 idempotency_conflict`; global developer token strictly backend-controlled; review subagents restricted to read-only tools (`tools: Read, Grep, Glob`).
- **Decisions:** Accepted architectural decisions D-014 (Dev-only test verification override), D-015 (Temporary media expiration & recovery), D-016 (Filename privacy & patient-facing document naming), D-017 (Deterministic idempotency & conflict rejection), D-018 (Standardized token naming), D-019 (Read-only review subagents), D-020 (Metadata-first sequencing rationale), D-021 (Evaluating Docflow-owned object storage).
- **Open issues/blockers:** External WhatsApp platform contracts remain unconfirmed in `docs/OPEN_QUESTIONS.md` (official media upload, customer credential provisioning, webhook delivery callbacks, provider status reconciliation). Production account verification remains blocked until provider contract is confirmed.
- **Next step:** Documentation audit complete and validated. Hand off repository to Claude Code to begin Phase 0 inspection.

## 2026-10-13T00:54:00+05:30 — Source-PDF retention lifecycle and tmpfiles.org upload contract alignment

- **Phase / task:** Pre-Phase 0 / final documentation correction
- **Goal:** Correct local source-PDF retention rules, cleanup eligibility, and tmpfiles.org upload contract to resolve remaining lifecycle ambiguities before Claude Code Phase 0.
- **Inspection:** Inspected `docs/AGENT_SPEC.md`, `docs/DELIVERY_STATE_MACHINE.md`, `docs/API_CONTRACTS.md`, `docs/DATA_MODEL.md`, `docs/SECURITY.md`, `docs/WHATSAPP_ADAPTER.md`, `docs/TESTING.md`, `docs/DECISIONS.md`, `docs/ENVIRONMENT.md`, `.env.example`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/OPEN_QUESTIONS.md`, `docs/RULES.md`, `agent/CLAUDE.md`, `backend/CLAUDE.md`, `scripts/validate_pack.py`, `docs/PACK_VALIDATION.md`, and `progress.md`.
- **Changes:**
  - `docs/AGENT_SPEC.md`: Enforced that provider API acceptance alone (`accepted`) MUST NOT permit deletion of the local source PDF; source must be retained across all in-flight states (`queued`, `uploading`, `retrying`, awaiting delivery confirmation `delivered`/`read`, and `reconciliation_required`). Added SQLite `jobs` table cleanup fields (`terminal_confirmed_at`, `cleanup_eligible_at`, `cleanup_status`, `deletion_verified_at`). Defined finite configurable retention windows: `AGENT_CLEANUP_RETENTION_HOURS` (default 24h) for delivered/read reports, and `AGENT_FAILED_RETENTION_DAYS` (default 14d) for failed/quarantined reports. Specified pre-deletion verification checklist (terminal state, no active lease, no pending reconciliation, elapsed timer) with SQLite persistence surviving service restarts. Documented `source_file_unavailable` error handling. Detailed tmpfiles upload contract: `POST https://tmpfiles.org/api/v1/upload` (multipart field `file`), default 60 min lifetime, direct-download binary URL (`/dl/`) extraction/validation, ordinary HTML landing-page URL rejection in WhatsApp payloads, HTTPS and host validation (`TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`), conservative expiry, pre-send renewal, and reconcile-before-resend even when temporary media expired.
  - `docs/DELIVERY_STATE_MACHINE.md`: Updated Section 1 and Section 4 to explicitly state that provider acceptance alone (`accepted`) does not permit source PDF deletion; source is retained until delivery confirmation (`delivered`/`read`) plus retention window or operator resolution; ambiguous send timeouts trigger `reconciliation_required` and must be reconciled before resending, even if temporary media expired; documented `source_file_unavailable`.
  - `docs/API_CONTRACTS.md`: Clarified `PUT /.../media-reference` requires direct-download binary URL (`https://tmpfiles.org/dl/...`), rejects HTML landing-page URLs, validates host `TEMP_UPLOAD_EXPECTED_HOST`, and notes local source retention through in-flight states until delivery confirmation.
  - `docs/DATA_MODEL.md`: Updated `MediaReference` to require direct-download binary URL and expected host allowlist; added local SQLite retention tracking fields and pre-deletion verification checklist to Section 7.
  - `docs/SECURITY.md`: Expanded Section 5 to document source-PDF retention rules, pre-deletion verification checklist, finite configurable retention (`AGENT_CLEANUP_RETENTION_HOURS`, `AGENT_FAILED_RETENTION_DAYS`), tmpfiles multipart endpoint and direct-download binary URL enforcement, rejection of landing-page URLs in WhatsApp payloads, and `source_file_unavailable` handling.
  - `docs/WHATSAPP_ADAPTER.md`: Expanded Section 7 with exact tmpfiles upload endpoint (`POST https://tmpfiles.org/api/v1/upload`), multipart field `file`, default 60 min lifetime, `/dl/` direct-download URL resolution, HTML landing-page URL rejection in WhatsApp payloads, host allowlist, conservative expiry, pre-send renewal, and reconcile-before-resend.
  - `docs/RULES.md`: Updated Rule 6 (acceptance alone does not permit source deletion) and Rule 7 (tmpfiles multipart endpoint, direct-download binary URL enforcement, landing-page URL rejection, finite configurable retention, `source_file_unavailable`).
  - `docs/ENVIRONMENT.md` & `.env.example`: Added `TEMP_UPLOAD_EXPECTED_HOST` (default `tmpfiles.org`), `AGENT_CLEANUP_RETENTION_HOURS` (default `24`), and `AGENT_FAILED_RETENTION_DAYS` (default `14`).
  - `docs/DECISIONS.md`: Updated D-020; added D-022 (Source-PDF retention, delivery confirmation prerequisite, and finite secure cleanup) and D-023 (tmpfiles.org upload contract, direct-download URL resolution, and conservative expiry).
  - `docs/TESTING.md`: Added test requirements for local source retention during in-flight/reconciliation states, prevention of deletion on provider acceptance alone, cleanup retention timers, pre-deletion verification checklist, tmpfiles response parsing, `/dl/` direct-download URL validation, landing-page URL rejection in WhatsApp payloads, host allowlist, malformed response handling, and reconcile-before-resend.
  - `docs/ROADMAP.md`: Updated Phase 2 and Phase 3 deliverables and done criteria with source retention, cleanup eligibility, and tmpfiles upload contract details.
  - `docs/ARCHITECTURE.md`: Synchronized PDF data plane narrative with source retention until confirmed delivery + retention window, tmpfiles direct-download URL resolution, and reconcile-before-resend.
  - `docs/OPEN_QUESTIONS.md`: Updated Option 2 with tmpfiles endpoint, direct-download URL resolution, and local source retention during delayed reconciliation.
  - `agent/CLAUDE.md` & `backend/CLAUDE.md`: Synchronized rules on source retention until delivery confirmation, tmpfiles direct-download URL requirements, and reconcile-before-resend.
  - `scripts/validate_pack.py`: Added checks for D-023, `AGENT_CLEANUP_RETENTION_HOURS`, `TEMP_UPLOAD_EXPECTED_HOST`, `source_file_unavailable`, `/dl/` path, provider acceptance non-deletion rule in `AGENT_SPEC.md`, and direct-download vs landing-page URL distinction in `WHATSAPP_ADAPTER.md`.
  - `docs/PACK_VALIDATION.md`: Updated validation report for 67 passed checks.
- **Why:** Provider acceptance alone does not guarantee message arrival on recipient client; deleting source PDFs upon acceptance prevents recovery or resending. Passing HTML landing-page URLs to WhatsApp causes delivery failures because WhatsApp expects PDF bytes. Enforcing direct-download URLs, finite configurable retention, and pre-deletion verification ensures data resilience, privacy, and regulatory compliance.
- **Commands run:** `python scripts/validate_pack.py` (executed from workspace root `c:\Rohit's-Workspace\Docflow`).
- **Tests/checks:** Mechanical pack validator executed with exit code 0; 67 checks passed, 0 issues across all 28 Markdown files. Runtime tests were not run because application code does not exist yet (pre-Phase 0).
- **Security/reliability checks:** Local source PDF retained across all in-flight states; provider acceptance alone cannot delete source; pre-deletion checklist prevents race conditions; patient report retention is finite and configurable; direct-download binary URL enforced; ordinary HTML landing page prohibited in WhatsApp payloads; unexpected hosts rejected; ambiguous timeouts require reconciliation before resend even if media expired; missing source files fail closed with `source_file_unavailable`.
- **Decisions:** Confirmed D-022 (Source-PDF retention, delivery confirmation prerequisite, and finite secure cleanup) and D-023 (tmpfiles.org upload contract, direct-download URL resolution, and conservative expiry).
- **Open issues/blockers:** External WhatsApp platform contracts remain unconfirmed in `docs/OPEN_QUESTIONS.md` (official media upload, customer credential provisioning, webhook delivery callbacks, provider status reconciliation). Production account verification remains blocked until provider contract is confirmed.
- **Next step:** Documentation pack is complete, consistent, and validated. Ready for Claude Code Phase 0 inspection.

## 2026-10-13T01:13:00+05:30 — Corrections to deletion guarantees, failed retention lifecycle, and uncertain upload expiry

- **Phase / task:** Pre-Phase 0 / final documentation correction
- **Goal:** Correct the secure-deletion guarantee (frame as best-effort file deletion with full-disk encryption, explaining wear-leveling/SSD/journaling limits), explicitly define the failed/quarantined source-PDF retention lifecycle and operator hold, and treat temporary upload expiry as an uncertain local operational estimate.
- **Inspection:** Inspected `docs/AGENT_SPEC.md`, `docs/SECURITY.md`, `docs/DELIVERY_STATE_MACHINE.md`, `docs/DATA_MODEL.md`, `docs/API_CONTRACTS.md`, `docs/WHATSAPP_ADAPTER.md`, `docs/TESTING.md`, `docs/DECISIONS.md`, `docs/ENVIRONMENT.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/OPEN_QUESTIONS.md`, `docs/RULES.md`, `agent/CLAUDE.md`, `scripts/validate_pack.py`, and `docs/PACK_VALIDATION.md`.
- **Changes:**
  - `docs/AGENT_SPEC.md`: Replaced unconditional secure-erasure claims with best-effort file deletion; documented wear-leveling, SSD remapping, NTFS journaling, CoW filesystems, snapshots, and backups; specified full-disk encryption (BitLocker) for Windows Agent host storage; defined failed/quarantined retention clock start at transition to `failed`/`quarantined` (`terminal_confirmed_at`); specified that retries cancel cleanup eligibility (`cleanup_eligible_at = NULL`); documented operator hold (`operator_hold = 1`, `cleanup_status = 'operator_hold'`) suspending cleanup across service restarts with recalculation upon release; updated pre-deletion checklist; documented `expires_at` as a local operational estimate with no upstream provider guarantee; documented handling of provider fetch failure without losing source PDF; prohibited reconstructing source PDF from temporary URLs.
  - `docs/SECURITY.md`: Replaced secure-deletion claims with best-effort file deletion; mandated BitLocker volume encryption and ACLs on Windows Agent storage; documented failed/quarantine retention lifecycle and operator hold; framed temporary upload expiry as local operational estimate; documented provider fetch failure handling and retry.
  - `docs/DELIVERY_STATE_MACHINE.md`: Updated Section 4 to document operational expiry estimate, provider-side fetch failure handling, failed/quarantined retention lifecycle, retry eligibility cancellation, operator hold suspension, and best-effort deletion with BitLocker.
  - `docs/DATA_MODEL.md`: Updated `MediaReference` to define `expires_at` as a local operational estimate; documented provider fetch failure handling; updated Section 7 with failed/quarantined retention clock, retry cancellation, operator hold, and best-effort deletion.
  - `docs/API_CONTRACTS.md`: Clarified that `expires_at` in `PUT /.../media-reference` is a local operational estimate without upstream provider guarantee; documented provider-side fetch failure recovery.
  - `docs/WHATSAPP_ADAPTER.md`: Documented that tmpfiles.org lifetime is an unconfirmed operational estimate (~60m default TTL); detailed pre-send expiry validation, rejection within safety buffer, and provider fetch failure retry handling.
  - `docs/RULES.md`: Updated Rule 7 to specify best-effort file deletion and local operational estimate for temporary upload lifetime.
  - `docs/TESTING.md`: Added test requirements for failed-retention deadline calculation, retry cancelling cleanup eligibility, operator hold suspending cleanup across restarts, pre-deletion checklist blocking conditions, best-effort deletion, operational expiry estimate, provider fetch failure, and prohibition of reconstructing source PDFs from temporary URLs.
  - `docs/DECISIONS.md`: Updated D-022 to record best-effort file deletion, BitLocker disk encryption, and operator hold; updated D-023 to specify operational upload expiry estimates and provider fetch failure handling.
  - `docs/ENVIRONMENT.md`: Documented `TEMP_UPLOAD_TTL_SECONDS` and `TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS` operational parameters, and BitLocker requirement for Agent storage.
  - `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/OPEN_QUESTIONS.md`, `agent/CLAUDE.md`: Synchronized best-effort deletion, operator hold, and operational expiry estimates across narratives and guidelines.
  - `scripts/validate_pack.py`: Added mechanical checks for best-effort file deletion, BitLocker, operator hold, operational expiry estimate, failed-retention deadline calculation, and provider fetch failure tests.
  - `docs/PACK_VALIDATION.md`: Updated report for 73 passed checks (0 issues).
- **Why:** Overwriting a file before unlinking cannot guarantee erasure on modern SSDs with wear-leveling, journaled filesystems (NTFS), or copy-on-write storage; disk encryption (BitLocker) must be used instead of making technically false secure-erasure claims. Failed and quarantined reports require unambiguous retention lifecycles where retries reset cleanup and operator holds halt deletion. Temporary uploader expiry must be treated as an uncertain operational estimate without upstream SLAs, ensuring resilience if files expire prematurely.
- **Commands run:** `python scripts/validate_pack.py` (executed from workspace root `c:\Rohit's-Workspace\Docflow`).
- **Tests/checks:** Mechanical pack validator executed with exit code 0; 73 checks passed, 0 issues across all 28 Markdown files. Runtime tests were not run because application code does not exist yet (pre-development planning phase).
- **Security/reliability checks:** Deletion framed as best-effort file deletion; BitLocker disk encryption required on Windows Agent host; operator hold reliably suspends cleanup across restarts; retries cancel stale cleanup deadlines; active leases and unresolved reconciliation block deletion; temporary upload expiry treated as local estimate; provider fetch failure preserves local source PDF and triggers safe retry; missing source PDF fails closed with `source_file_unavailable`.
- **Decisions:** Updated D-022 (Source-PDF retention, delivery confirmation prerequisite, operator hold, and finite best-effort cleanup) and D-023 (tmpfiles.org upload contract, direct-download URL resolution, and operational expiry estimates).
- **Open issues/blockers:** External WhatsApp platform contracts remain unconfirmed in `docs/OPEN_QUESTIONS.md` (official media upload, customer credential provisioning, webhook delivery callbacks, provider status reconciliation). Production account verification remains blocked until provider contract is confirmed.
- **Next step:** Planning pack corrections complete and validated (73/73 checks passing). Ready for Claude Code Phase 0 inspection.

## 2026-10-14T00:00:00+05:30 — Phase 1 Task 1: Django backend foundation

- **Phase / task:** Phase 1 / Task 1 — Django backend skeleton, custom User model, three-settings layout, startup validator, migrations, tests.
- **Goal:** Establish the minimum working Django + DRF backend with a UUID/email-based User model set as AUTH_USER_MODEL before any migration, development (SQLite) and production (PostgreSQL fail-closed) settings, and a startup configuration validator that rejects unsafe production configuration.
- **Inspection:** Confirmed `backend/` contained only `CLAUDE.md`. No application code existed. No Git repository; `.gitignore` already excludes `.venv/` and `backend/db.sqlite3`. Python 3.13.7 and pip 26.1.1 available on host.
- **Changes:**
  - `backend/requirements.txt` — pinned dependency ranges: django>=5.1,<5.2, djangorestframework>=3.15, dj-database-url>=2.3, psycopg2-binary>=2.9, python-decouple>=3.8.
  - `backend/.venv/` — Python 3.13.7 virtual environment (excluded by `.gitignore`).
  - `backend/manage.py` — standard Django entry point; default settings `config.settings.development`.
  - `backend/config/__init__.py`, `backend/config/wsgi.py`, `backend/config/asgi.py`, `backend/config/urls.py`
  - `backend/config/settings/__init__.py`
  - `backend/config/settings/base.py` — shared settings: INSTALLED_APPS (with `apps.users`), MIDDLEWARE, DRF config, AUTH_USER_MODEL = "users.User", USE_TZ = True.
  - `backend/config/settings/development.py` — SQLite (Django default), DEBUG=True, localhost ALLOWED_HOSTS, DEV_ACCOUNT_VERIFICATION_OVERRIDE from env (default false).
  - `backend/config/settings/production.py` — startup validator: _require_env() for DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, DATABASE_URL; fails closed if DEBUG!=false, DATABASE_URL missing/SQLite/non-PostgreSQL, DEV_ACCOUNT_VERIFICATION_OVERRIDE=true, TEMP_UPLOAD_MODE!=disabled. No secret values in error messages.
  - `backend/apps/__init__.py`, `backend/apps/users/__init__.py`, `backend/apps/users/apps.py`
  - `backend/apps/users/models.py` — custom User: UUID PK, email-based login (USERNAME_FIELD="email"), display_name, is_platform_admin, created_at, updated_at, UserManager with create_user/create_superuser.
  - `backend/apps/users/admin.py` — UserAdmin registered.
  - `backend/apps/users/migrations/__init__.py`, `backend/apps/users/migrations/0001_initial.py` (auto-generated).
  - `backend/tests/__init__.py`
  - `backend/tests/test_user_model.py` — 14 tests: UUID PK, email uniqueness, normalisation, password hashing, create_user defaults, create_superuser flags and error, display name helpers, timestamps.
  - `backend/tests/test_config_validation.py` — 15 tests: production fail-closed for missing/empty SECRET_KEY, DEBUG=true/1, missing/empty/SQLite DATABASE_URL, DEV_ACCOUNT_VERIFICATION_OVERRIDE=true/1, TEMP_UPLOAD_MODE=tmpfiles; happy paths for each; error messages do not leak values.
- **Why:** AUTH_USER_MODEL must be set before first migration (irreversible Django constraint). Fail-closed production validator enforces Rules 1, 3, 7, ENVIRONMENT.md §3, SECURITY.md §6 and the DEV_ACCOUNT_VERIFICATION_OVERRIDE production rejection required by D-014.
- **Commands run (exact):**
  - `python -m venv "C:\Rohit's-Workspace\Docflow\backend\.venv"` — exit 0
  - `& "...\backend\.venv\Scripts\pip.exe" install "django>=5.1,<5.2" djangorestframework "dj-database-url>=2.3" psycopg2-binary python-decouple` — exit 0; installed django-5.1.15, djangorestframework-3.17.2, dj-database-url-3.1.2, psycopg2-binary-2.9.13, python-decouple-3.8
  - `& "...\backend\.venv\Scripts\python.exe" manage.py check --settings=config.settings.development 2>&1` — "System check identified no issues (0 silenced)"
  - `& "...\backend\.venv\Scripts\python.exe" manage.py makemigrations --settings=config.settings.development 2>&1` — created `apps/users/migrations/0001_initial.py`
  - `& "...\backend\.venv\Scripts\python.exe" manage.py migrate --settings=config.settings.development 2>&1` — all migrations applied OK (contenttypes, auth, users, admin, sessions)
  - `& "...\backend\.venv\Scripts\python.exe" manage.py test tests --settings=config.settings.development --verbosity=2 2>&1` — **Ran 29 tests in 9.901s — OK**
- **Tests/checks:** 29 tests run and passed. 0 failures. System check 0 issues.
- **Security/reliability checks:** No secrets in error messages (tested); production settings never fall back to SQLite; DEV_ACCOUNT_VERIFICATION_OVERRIDE=true rejected at import time in production; TEMP_UPLOAD_MODE!=disabled rejected in production; DEBUG must be exactly false; AUTH_USER_MODEL set before first migration.
- **Decisions:** None changed. All decisions (D-004, D-005, D-014) followed as specified.
- **Open issues/blockers:** None for Phase 1 Task 1. Remaining WhatsApp/media/credential open questions (OQ-001 through OQ-010) are deferred to Phase 3+.
- **Next step:** Phase 1 Task 1 complete. Awaiting approval to proceed to Phase 1 Task 2 (remaining models: Organization, Lab, Branch, Device, WhatsApp account, Report, Outbox, etc.).

## 2026-10-14T21:05:00+05:30 — Phase 1 Task 2A: Core Tenancy Models

- **Phase / task:** Phase 1 / Task 2A — Core Tenancy Models (Organization, OrganizationMembership, Lab, Branch), migrations, admin registration, tenant safety validation, unit tests.
- **Goal:** Implement minimal core tenancy abstractions with UUID PKs, uniqueness constraints, role/status choices, and robust cross-tenant consistency validation (branch's lab must belong to branch's organization on save) without unnecessary database queries.
- **Inspection:** Inspected Git status, CLAUDE.md, backend/config/settings/base.py, apps/users/models.py, docs/DATA_MODEL.md, docs/RULES.md, docs/SECURITY.md.
- **Changes:**
  - `backend/config/settings/base.py`: Registered `apps.tenants` in `INSTALLED_APPS`.
  - `backend/apps/tenants/__init__.py`: Package init.
  - `backend/apps/tenants/apps.py`: TenantsConfig AppConfig.
  - `backend/apps/tenants/models.py`: Created `Organization` (UUID PK, name, unique slug, status choices, timezone, created_by FK, timestamps), `OrganizationMembership` (UUID PK, organization FK, user FK, role choices, status choices, timestamps, unique constraint on org + user), `Lab` (UUID PK, organization FK, name, code unique per organization, default diagnostic lab_type, support phone, status choices, timestamps), and `Branch` (UUID PK, organization FK, lab FK, name, code unique per lab, address, support phone, timezone, status choices, timestamps, cross-tenant consistency validation in `clean()` and `save()`).
  - `backend/apps/tenants/admin.py`: Registered `OrganizationAdmin`, `OrganizationMembershipAdmin`, `LabAdmin`, and `BranchAdmin` with search, filter, and readonly timestamp fields.
  - `backend/apps/tenants/migrations/0001_initial.py`: Migration generated and applied cleanly against development SQLite database.
  - `backend/tests/test_tenant_models.py`: 29 unit tests covering model creation, UUID PKs, slug uniqueness, membership uniqueness, role/status choices, lab code scoping, branch code scoping, cascade deletion behaviors, and tenant safety invariants.
- **Why:** Establish tenant boundary models per DATA_MODEL.md §1 and enforce Rule 1 (tenant isolation). Prevent cross-tenant branch misconfigurations even on direct ORM `save()` or `create()` calls without degrading partial updates.
- **Commands run:**
  - `& "...\backend\.venv\Scripts\python.exe" manage.py check --settings=config.settings.development` — System check identified no issues (0 silenced).
  - `& "...\backend\.venv\Scripts\python.exe" manage.py makemigrations tenants --settings=config.settings.development` — Created `apps/tenants/migrations/0001_initial.py`.
  - `& "...\backend\.venv\Scripts\python.exe" manage.py migrate --settings=config.settings.development` — Applied `tenants.0001_initial` OK.
  - `& "...\backend\.venv\Scripts\python.exe" manage.py test tests --settings=config.settings.development --verbosity=2` — Ran 68 tests in 23.615s — OK.
- **Tests/checks:** 68 tests run (39 existing + 29 new tenant tests), 0 failures. System check 0 issues.
- **Security/reliability checks:** Cross-organization branch creation (`branch.lab.organization != branch.organization`) is rejected with `ValidationError` on `save()`, `create()`, and `full_clean()`; `save(update_fields=['status'])` does not trigger redundant queries; unique constraints prevent duplicate slugs, duplicate memberships, duplicate lab codes per org, and duplicate branch codes per lab.
- **Decisions:** Branch code uniqueness is scoped to its lab (`unique_lab_branch_code`); `created_by` on `Organization` uses `SET_NULL`; `clean()` and `save()` enforce tenant consistency across normal model persistence.
- **Open issues/blockers:** None for Task 2A. External WhatsApp contracts (OQ-001–OQ-010) remain deferred to Phase 3+.
- **Next step:** Phase 1 Task 2A complete. Awaiting approval for Phase 1 Task 2B (Device & activation models, or next planned model batch).

## 2026-10-14T21:25:00+05:30 — Phase 1 Task 2B: Device and Credential Models

- **Phase / task:** Phase 1 / Task 2B — Device, DeviceActivationCode, and DeviceRefreshCredential models, migrations, admin registration, tenant consistency validation, credential hashing protections, and unit tests.
- **Goal:** Implement minimal device domain abstractions per DATA_MODEL.md §2 and SECURITY.md §3, enforcing cross-table tenant consistency (device branch must belong to device organization; activation code org, branch, and device must agree; replacement refresh credential must belong to same device) and strictly protecting secrets by storing only hashes.
- **Inspection:** Inspected Git status, CLAUDE.md, backend/config/settings/base.py, apps/tenants/models.py, docs/DATA_MODEL.md §2, docs/SECURITY.md §3.
- **Changes:**
  - `backend/config/settings/base.py`: Registered `apps.devices` in `INSTALLED_APPS`.
  - `backend/apps/devices/__init__.py`: Package init.
  - `backend/apps/devices/apps.py`: DevicesConfig AppConfig.
  - `backend/apps/devices/models.py`: Created `Device` (UUID PK, organization FK, branch FK, name, status choices, agent_version, windows platform default, last_seen_at, last_ip, activated_at, revoked_at, timestamps, tenant consistency validation, and organization immutability), `DeviceActivationCode` (UUID PK, organization FK, branch FK, device FK, created_by FK, unique code_hash, default 10-minute expiry, consumed_at, attempt_count, revoked_at, timestamps, mutual consistency validation, helper properties `is_valid`/`is_consumed`/`is_revoked`/`is_expired`), and `DeviceRefreshCredential` (UUID PK, device FK, unique credential_hash, issued_at, expires_at, rotated_at, revoked_at, replaced_by OneToOne self-reference, same-device rotation validation, helper properties `is_active`/`is_rotated`/`is_revoked`/`is_expired`).
  - `backend/apps/devices/admin.py`: Registered `DeviceAdmin`, `DeviceActivationCodeAdmin`, and `DeviceRefreshCredentialAdmin`, strictly excluding `code_hash` and `credential_hash` from `list_display` and making `organization` read-only on existing Device instances.
  - `backend/apps/devices/migrations/0001_initial.py`: Migration generated and applied cleanly against development SQLite database.
  - `backend/tests/test_device_models.py`: 25 unit tests covering model creation, UUID PKs, choices, hash uniqueness, expiry calculations, mutual tenant consistency on save/clean, credential hash protections, rotation chaining, and admin security.
- **Why:** Establish client PC identity and authentication credential storage per DATA_MODEL.md §2 and SECURITY.md §3 without storing raw secrets or allowing cross-tenant device bindings.
- **Commands run:**
  - `& "...\backend\.venv\Scripts\python.exe" manage.py check --settings=config.settings.development` — System check identified no issues (0 silenced).
  - `& "...\backend\.venv\Scripts\python.exe" manage.py makemigrations devices --settings=config.settings.development` — Created `apps/devices/migrations/0001_initial.py`.
  - `& "...\backend\.venv\Scripts\python.exe" manage.py migrate --settings=config.settings.development` — Applied `devices.0001_initial` OK.
  - `& "...\backend\.venv\Scripts\python.exe" manage.py test tests --settings=config.settings.development --verbosity=2` — Ran 99 tests in 32.976s — OK.
- **Tests/checks:** 99 tests run (14 user + 25 config + 35 tenant + 25 device), 0 failures. System check 0 issues.
- **Security/reliability checks:** Raw activation codes and refresh secrets are never stored (hashes only); hashes excluded from admin list displays; cross-organization branches on devices and activation codes are rejected with `ValidationError`; replacement refresh credentials must belong to the same device; device organization cannot be mutated after persistence.
- **Decisions:** Activation code initial expiry defaults to 10 minutes (`get_default_activation_code_expiry`); `replaced_by` uses `OneToOneField` self-reference for linear rotation chains; `code_hash` and `credential_hash` are unique CharFields.
- **Open issues/blockers:** None for Task 2B. External WhatsApp contracts (OQ-001–OQ-010) remain deferred to Phase 3+.
- **Next step:** Phase 1 Task 2B complete. Awaiting approval for Phase 1 Task 2C (WhatsApp account & assignment models, or next planned model batch).

## 2026-10-14T21:35:00+05:30 — Phase 1 Task 2C: WhatsApp Account and Branch Assignment Models

- **Phase / task:** Phase 1 / Task 2C — WhatsAppAccount and BranchWhatsAppAssignment models, migrations, admin registration, tenant consistency validation, single-active-assignment constraint, and unit tests.
- **Goal:** Implement WhatsApp account and branch assignment abstractions per DATA_MODEL.md §3, SECURITY.md §4, and OPEN_QUESTIONS.md OQ-003/OQ-004, ensuring mutual tenant consistency, preserving assignment history, enforcing at most one active sender per branch via a database constraint, and protecting opaque credential secret references.
- **Inspection:** Inspected Git status, CLAUDE.md, backend/config/settings/base.py, apps/tenants/models.py, docs/DATA_MODEL.md §3, docs/SECURITY.md §4, and docs/OPEN_QUESTIONS.md.
- **Changes:**
  - `backend/config/settings/base.py`: Registered `apps.whatsapp` in `INSTALLED_APPS`.
  - `backend/apps/whatsapp/__init__.py`: Package init.
  - `backend/apps/whatsapp/apps.py`: WhatsappConfig AppConfig (`name = "apps.whatsapp"`, `label = "whatsapp"`).
  - `backend/apps/whatsapp/models.py`: Created `WhatsAppAccount` (UUID PK, organization FK, provider_key, optional provider_account_reference, phone_number_id, restricted display fields display_phone_number and display_name, credential_mode choices, opaque credential_secret_ref, status choices, verification timestamps, created_by FK, standard timestamps, organization immutability on edit, non-unique composite lookup index on `[provider_key, phone_number_id]`), and `BranchWhatsAppAssignment` (UUID PK, organization FK, branch FK, whatsapp_account FK, status choices [active, inactive], assigned_by FK, assigned_at, ended_at, partial database unique constraint enforcing at most one active sender per branch across SQLite and PostgreSQL, cross-tenant consistency validation ensuring branch and account belong to assignment organization).
  - `backend/apps/whatsapp/admin.py`: Registered `WhatsAppAccountAdmin` and `BranchWhatsAppAssignmentAdmin`, strictly excluding `credential_secret_ref` from `list_display`, protecting credentials from ordinary listings, and setting `organization` read-only on edit.
  - `backend/apps/whatsapp/migrations/0001_initial.py`: Migration generated and applied cleanly against development SQLite database.
  - `backend/tests/test_whatsapp_models.py`: 18 unit tests covering model creation, UUID PKs, choices, secret ref protection, organization immutability, non-unique phone ID indexing across accounts, cross-tenant assignment validation rejection, single-active-assignment database constraint enforcement, multiple inactive assignments preservation, and admin security.
- **Why:** Establish WhatsApp sender identity and routing assignments per DATA_MODEL.md §3 without storing raw access tokens or allowing cross-tenant sender assignments.
- **Commands run:**
  - `& "...\backend\.venv\Scripts\python.exe" manage.py check --settings=config.settings.development` — System check identified no issues (0 silenced).
  - `& "...\backend\.venv\Scripts\python.exe" manage.py makemigrations whatsapp --settings=config.settings.development` — Created `apps/whatsapp/migrations/0001_initial.py`.
  - `& "...\backend\.venv\Scripts\python.exe" manage.py migrate --settings=config.settings.development` — Applied `whatsapp.0001_initial` OK.
  - `& "...\backend\.venv\Scripts\python.exe" manage.py makemigrations --check --settings=config.settings.development` — No changes detected.
  - `& "...\backend\.venv\Scripts\python.exe" manage.py test tests --settings=config.settings.development --verbosity=2` — Ran 117 tests in 49.846s — OK.
- **Tests/checks:** 117 tests run (14 user + 25 config + 35 tenant + 25 device + 18 whatsapp), 0 failures, 0 errors. System check 0 issues. `makemigrations --check` clean.
- **Security/reliability checks:** `credential_secret_ref` is treated as an opaque reference; raw access tokens are never stored; `credential_secret_ref` excluded from admin list displays; cross-organization assignments (`branch.organization != account.organization != assignment.organization`) rejected with `ValidationError`; single active assignment per branch enforced at database level with `UniqueConstraint(fields=["branch"], condition=Q(status="active"))`; historical assignments preserved; account organization immutable after initial save.
- **Decisions:** Upstream provider uniqueness for `phone_number_id` remains unresolved per OQ-003/OQ-004, so a non-unique composite index `(provider_key, phone_number_id)` is used rather than speculative unique constraints; `credential_mode` supports `platform_managed`, `backend_secret`, and `pending_contract`; `status` supports `pending_verification`, `verified`, `disabled`, and `error`.
- **Open issues/blockers:** None for Task 2C. Upstream WhatsApp provider contracts (OQ-001 through OQ-010) remain deferred to Phase 3+.
- **Next step:** Phase 1 Task 2C complete. Awaiting approval for Phase 1 Task 2D (Report / Outbox models).

## 2026-10-14T21:55:00+05:30 — Phase 1 Task 2D: Report and Delivery Models

- **Phase / task:** Phase 1 / Task 2D — Report, MediaReference, DeliveryAttempt, DeliveryEvent, and DispatchOutbox models, migrations, admin registration, tenant consistency validation, canonical fingerprint formula, idempotency constraints, media expiration requirements, and unit tests.
- **Goal:** Implement report metadata and delivery tracking models in `apps.reports` per DATA_MODEL.md §§ 4 and 6, DELIVERY_STATE_MACHINE.md, and API_CONTRACTS.md, strictly preventing PDF bytes storage in Django, validating tenant consistency across all foreign keys, enforcing idempotency and versioned canonical fingerprint uniqueness, protecting encrypted media references, preserving attempt history across resends, avoiding raw webhook payloads, and supporting durable outbox dispatch.
- **Inspection:** Inspected Git status, CLAUDE.md, backend/config/settings/base.py, apps/tenants/models.py, apps/devices/models.py, apps/whatsapp/models.py, docs/DATA_MODEL.md §§ 4 and 6, docs/DELIVERY_STATE_MACHINE.md, and docs/API_CONTRACTS.md.
- **Changes:**
  - `backend/config/settings/base.py`: Registered `apps.reports` in `INSTALLED_APPS`.
  - `backend/apps/reports/__init__.py`: Package init.
  - `backend/apps/reports/apps.py`: ReportsConfig AppConfig (`name = "apps.reports"`, `label = "reports"`).
  - `backend/apps/reports/models.py`: Created `Report` (UUID PK, organization/lab/branch/device/branch_assignment FKs, recipient_phone_e164, opaque source_file_label with PII minimization, diagnostic_report document_type, content_sha256, file_size_bytes, 64-hex idempotency_key, versioned canonical fingerprint `sha256("v1|" + branch_id + "|" + recipient_phone_e164 + "|" + content_sha256)`, status choices from delivery state machine, unique constraints on `(organization, idempotency_key)` and `(organization, fingerprint)`, timestamps, immutable identity fields), `MediaReference` (UUID PK, report FK, kind choices [development_download_url, provider_media_id, provider_upload_reference], protected/encrypted reference storage, download_url for direct binary tmpfiles links, mandatory explicit expires_at for temporary media, rejection of PDF bytes and plaintext temporary URLs in encrypted_reference), `DeliveryAttempt` (UUID PK, organization and report FKs, attempt_number starting at 1, status choices, provider_key, provider_message_id and request_id, timestamps, normalized error_code and error_category [transient, permanent, ambiguous, configuration], unique constraint on `(report, attempt_number)`), `DeliveryEvent` (UUID PK, organization, report, and optional delivery_attempt FKs, event_type, source choices [agent, docflow, platform, meta, admin], provider_event_id, provider and received timestamps, safe_payload_summary strictly rejecting raw payloads and secrets, normalized error_code), and `DispatchOutbox` (UUID PK, organization, report, and delivery_attempt FKs, event_type, state choices [pending, claimed, completed, retry_wait, dead_letter], available_at, claimed_at, claim_expires_at, attempt_count, last_error_code, timestamps, durable dispatch indexes).
  - `backend/apps/reports/admin.py`: Registered `ReportAdmin`, `MediaReferenceAdmin` (excluding sensitive reference fields from list_display), `DeliveryAttemptAdmin`, `DeliveryEventAdmin`, and `DispatchOutboxAdmin` with appropriate search, filter, and read-only protections.
  - `backend/apps/reports/migrations/0001_initial.py`: Migration generated and applied cleanly against development SQLite database.
  - `backend/tests/test_report_models.py`: 38 unit tests covering model creation, UUID PKs, status and kind choices, 64-hex and E.164 validations, source_file_label PII protection, canonical fingerprint calculation, database unique constraints, cross-tenant relationship rejections, immutability of persisted identity fields, media expiry and binary direct URL restrictions, attempt history preservation, safe payload restrictions, and outbox claiming lifecycle.
- **Why:** Establish report lifecycle, idempotency boundaries, media locator tracking, and durable outbox state per DATA_MODEL.md §§ 4 and 6 without storing PDF bytes or raw secrets.
- **Commands run:**
  - `& "...\backend\.venv\Scripts\python.exe" manage.py check --settings=config.settings.development` — System check identified no issues (0 silenced).
  - `& "...\backend\.venv\Scripts\python.exe" manage.py makemigrations reports --settings=config.settings.development` — Created `apps/reports/migrations/0001_initial.py`.
  - `& "...\backend\.venv\Scripts\python.exe" manage.py migrate --settings=config.settings.development` — Applied `reports.0001_initial` OK.
  - `& "...\backend\.venv\Scripts\python.exe" manage.py makemigrations --check --settings=config.settings.development` — No changes detected.
  - `& "...\backend\.venv\Scripts\python.exe" manage.py test tests --settings=config.settings.development` — Ran 161 tests in 55.888s — OK.
- **Tests/checks:** 161 tests run (14 user + 25 config + 35 tenant + 25 device + 24 whatsapp + 38 reports), 0 failures, 0 errors. System check 0 issues. `makemigrations --check` clean.
- **Security/reliability checks:** PDF bytes are never stored (validated); plaintext temporary URLs cannot be stored in `encrypted_reference`; temporary media references require explicit `expires_at` and binary `/dl/` prefix; raw webhook payloads and credentials cannot be persisted in `safe_payload_summary`; cross-tenant relationships across report, attempt, event, and outbox are rejected; report identity and attempt numbers are immutable; database unique constraints prevent concurrent duplicate submissions.
- **Decisions:** Canonical fingerprint follows `sha256("v1|" + branch_id + "|" + recipient_phone_e164 + "|" + content_sha256)`; `MediaReference` separates `encrypted_reference` ciphertext from `download_url` direct binary development URL; `DeliveryEvent.safe_payload_summary` enforces absence of raw payload/token keys; `DispatchOutbox` provides durable state machine outbox for dispatch workers.
- **Open issues/blockers:** None for Task 2D. Production media encryption/direct upload and status webhooks (OQ-001 through OQ-010) remain deferred to future phases.
- **Next step:** Phase 1 Task 2D complete. Awaiting approval to proceed to Phase 1 Task 3 (or next planned task).

## 2026-10-14T22:25:00+05:30 — Phase 1 Task 2E: AuditEvent and WebhookReceipt

- **Phase / task:** Phase 1 / Task 2E — AuditEvent and WebhookReceipt models, migrations, admin registration, and unit tests.
- **Goal:** Implement append-only `AuditEvent` with strict metadata allowlist, bounded scalar values, actor-device tenant consistency, and platform-level gating; implement `WebhookReceipt` with provider-scoped duplicate suppression and immutable event identity per DATA_MODEL.md §5 and SECURITY.md §§ 2, 7, 8.
- **Inspection:** Inspected Git status, revision alignment, CLAUDE.md, backend/config/settings/base.py, existing domain models, docs/DATA_MODEL.md §5, docs/SECURITY.md §§ 2, 7, 8, and docs/OPEN_QUESTIONS.md.
- **Changes:**
  - `backend/config/settings/base.py`: Registered `apps.audit` in `INSTALLED_APPS`.
  - `backend/apps/audit/__init__.py`: Package init.
  - `backend/apps/audit/apps.py`: AuditConfig AppConfig (`name = "apps.audit"`, `label = "audit"`).
  - `backend/apps/audit/models.py`: Created `AuditEvent` (UUID PK, nullable organization FK only for platform actions, optional actor_user and actor_device FKs, action choices covering device/account/role/delivery/security/platform actions, target_type, target_id, request_id, timestamp, safe_metadata JSON field with strict allowlisted keys, bounded scalar values, defense-in-depth content inspection rejecting URLs, PDF headers, tokens, raw payloads, and phone numbers, actor-device tenant consistency validation, append-only model and QuerySet immutability) and `WebhookReceipt` (UUID PK, provider_key, external_event_key, received_at, optional processed_at, processing_state choices, safe_error_code, unique constraint on `(provider_key, external_event_key)`, indexes on processing_state/received_at, event identity immutability on update, and legitimate processing-state lifecycle updates).
  - `backend/apps/audit/admin.py`: Registered `AuditEventAdmin` (append-only: no add, no edit, no delete, all fields read-only) and `WebhookReceiptAdmin` (no delete, identity fields read-only on edit).
  - `backend/apps/audit/migrations/0001_initial.py`: Migration generated and applied cleanly against development SQLite database.
  - `backend/tests/test_audit_models.py`: 33 unit tests covering model creation, UUID PKs, platform-level organization gating, actor-device cross-tenant mismatch rejection, metadata allowlist enforcement, snake_case key validation, scalar type bounding, value content security checks (PDF, URL, token, JSON payload, phone number), append-only model/QuerySet immutability, webhook receipt uniqueness and identity immutability, processing-state transitions, and admin permissions.
- **Why:** Establish tamper-resistant audit trail foundation and provider callback duplicate suppression records without storing sensitive payloads, tokens, or PII.
- **Commands run:**
  - `python manage.py check --settings=config.settings.development` — System check identified no issues (0 silenced).
  - `python manage.py makemigrations audit --settings=config.settings.development` — Created `apps/audit/migrations/0001_initial.py`.
  - `python manage.py migrate audit --settings=config.settings.development` — Applied `audit.0001_initial` OK.
  - `.\.venv\Scripts\python.exe manage.py makemigrations --check --settings=config.settings.development` — No changes detected.
  - `.\.venv\Scripts\python.exe manage.py test tests --settings=config.settings.development` — Ran 201 tests in 68.645s — OK.
- **Tests/checks:** 201 tests run (14 user + 25 config + 35 tenant + 25 device + 24 whatsapp + 45 reports + 33 audit), 0 failures, 0 errors. System check 0 issues. `makemigrations --check` clean.
- **Security/reliability checks:** Audit records are strictly append-only (edits and deletions blocked in model and QuerySet); metadata rejects unknown keys, nested objects, non-scalar values, oversized strings, and inspected sensitive values (URLs, PDFs, tokens, raw payloads, patient phone numbers); organization is required for tenant actions and permitted to be null only for explicit platform actions; actor-device tenant consistency is enforced; webhook receipts enforce provider-scoped uniqueness with immutable event identity.
- **Decisions:** Created `apps.audit` for DATA_MODEL.md §5 models (`AuditEvent`, `WebhookReceipt`); audit records use custom Manager/QuerySet to block bulk update/delete operations; safe metadata enforces both allowlisted key names and content inspection of string values.
- **Open issues/blockers:** None for Task 2E. Provider callback signatures, webhook endpoints, and external event schemas remain unconfirmed per OQ-005.
- **Next step:** Phase 1 Task 2E complete. Awaiting approval to proceed to next task.

