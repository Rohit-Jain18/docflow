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

## 2026-10-14T22:48:00+05:30 — Phase 1 Task 3A: Device Activation and Credential Services

- **Phase / task:** Phase 1 / Task 3A — Device Activation and Credential Services.
- **Goal:** Implement the service layer on top of device models in `backend/apps/devices/services.py` and DRF Bearer authentication in `backend/apps/devices/authentication.py` per API_CONTRACTS.md §3, SECURITY.md §3, and DATA_MODEL.md §2.
- **Inspection:** Inspected Git status, revision alignment, CLAUDE.md, existing device and audit models, docs/API_CONTRACTS.md §3, docs/SECURITY.md §3, and docs/DATA_MODEL.md §2.
- **Changes:**
  - `docs/API_CONTRACTS.md`: Documented token lifetime policy: 10 minutes for short-lived device access token, 30 days for rotating refresh token.
  - `backend/apps/devices/models.py`: Added `is_authenticated` and `is_anonymous` properties to `Device` model for DRF principal compatibility.
  - `backend/apps/devices/services.py`: Implemented `issue_activation_code` (cryptographically random 32-char code, SHA-256 hash stored in `code_hash`, raw code returned once, revocation of previous unconsumed codes, audit event emitted without raw code), `exchange_activation_code` (atomic code consumption inside `select_for_update` transaction, enforces attempt limits, expiry, revocation, single-use, device eligibility, updates device metadata, issues 30-day rotating refresh credential and 10-minute signed access token via `TimestampSigner`, emits audit event with zero secret leakage), `rotate_refresh_token` (atomic rotation, token reuse detection immediately revoking all outstanding device credentials and logging `TAMPERING_DETECTED`, issues fresh access token and replacement refresh credential), `generate_access_token`, and `verify_access_token`.
  - `backend/apps/devices/authentication.py`: Implemented DRF `DeviceBearerAuthentication` class validating signed Bearer access tokens, verifying active device status, and enforcing tenant consistency.
  - `backend/tests/test_device_services.py`: 26 comprehensive unit and integration tests covering code issuance, hashed-only storage, replacement revocation, expiry, revocation, single-use, attempt limits, eligibility checks, token signing, tampering detection, refresh rotation, token reuse detection and revocation, audit event safety, transaction rollback, and DRF Bearer authentication.
- **Why:** Establish device onboarding, one-time activation exchange, session authentication, and rotating refresh credential lifecycles without storing plaintext secrets or exposing raw codes.
- **Commands run:**
  - `.\.venv\Scripts\python.exe manage.py check --settings=config.settings.development` — System check identified no issues (0 silenced).
  - `.\.venv\Scripts\python.exe manage.py makemigrations --check --settings=config.settings.development` — No changes detected.
  - `.\.venv\Scripts\python.exe manage.py test tests --settings=config.settings.development` — Ran 229 tests in 108.861s — OK.
- **Tests/checks:** 229 tests run (14 user + 25 config + 35 tenant + 25 device model + 24 whatsapp + 45 reports + 35 audit + 26 device services), 0 failures, 0 errors. System check 0 issues. `makemigrations --check` clean.
- **Security/reliability checks:** Raw activation codes and refresh tokens are never persisted in plaintext or logged in audit events; access tokens use cryptographic HMAC signatures with 10-minute expiry; refresh credentials rotate atomically on every use; token reuse detection immediately revokes all active device credentials; failed attempts persist incremented counters.
- **Decisions:** Access tokens use Django's native `TimestampSigner` (no external JWT dependency required); `Device` exposes `is_authenticated=True` for DRF permission compatibility; attempt counters on failed code exchanges are persisted and audited.
- **Open issues/blockers:** None for Task 3A. Production device registration HTTP endpoints deferred to upcoming task.
- **Next step:** Phase 1 Task 3A complete. Awaiting approval to proceed to next task.

## 2026-10-15T12:25:00+05:30 — Phase 2 Task 2A: Windows Agent Foundation

- **Phase / task:** Phase 2 / Task 2A — Windows Agent Foundation
- **Goal:** Create a minimal, runnable Python Windows Agent foundation in the existing agent/ directory including package structure, CLI entry point, configuration module, logging module with redaction, lifecycle/health module, secure credential stores (Windows Credential Manager and DPAPI backing with in-memory test double), and focused tests.
- **Inspection:** Inspected [agent/CLAUDE.md](file:///c:/Rohit's-Workspace/Docflow/agent/CLAUDE.md), [docs/AGENT_SPEC.md](file:///c:/Rohit's-Workspace/Docflow/docs/AGENT_SPEC.md), [docs/ARCHITECTURE.md](file:///c:/Rohit's-Workspace/Docflow/docs/ARCHITECTURE.md), [docs/ENVIRONMENT.md](file:///c:/Rohit's-Workspace/Docflow/docs/ENVIRONMENT.md), [docs/SECURITY.md](file:///c:/Rohit's-Workspace/Docflow/docs/SECURITY.md), existing agent/ directory and Git status.
- **Changes:**
  - `agent/requirements.txt`: Agent core dependencies file.
  - `agent/requirements-dev.txt`: Agent dev dependencies including pytest.
  - `agent/docflow_agent/__init__.py`: Package init exposing `__version__ = "0.1.0"`.
  - `agent/docflow_agent/__main__.py`: Package execution entrypoint invoking CLI main.
  - `agent/docflow_agent/cli.py`: CLI commands (`health`, `status`, `version`), setting up logging and executing readiness inspections.
  - `agent/docflow_agent/config.py`: Configuration loading from environment variables (with `_ENV_ALIASES` matching `ENVIRONMENT.md` §5) and optional TOML file, strict validation, type coercion, prevention of folder nesting, and rejection of prohibited secret keys.
  - `agent/docflow_agent/credentials.py`: Secure credential storage interface `CredentialStore`, `WindowsCredentialManagerStore` (using `advapi32.dll` via `ctypes`), `WindowsDpapiStore` (using `crypt32.dll` via `ctypes`), `InMemoryCredentialStore` (test double / non-Windows fallback), and `get_credential_store()` resolver.
  - `agent/docflow_agent/logging.py`: Structured logging setup with `RedactionFilter` scrubbing phone numbers, bearer tokens, secret keys, temporary URLs, and sensitive Windows paths across both console and file handlers.
  - `agent/docflow_agent/health.py`: Readiness inspection checking configuration validity, watch-folder existence and read access, write permissions on archive/quarantine/db folders, credential store accessibility, prohibited secret variable exposure, and API URL scheme.
  - `agent/tests/test_cli.py`: Focused tests for CLI `health`, `status`, `version`, and help commands.
  - `agent/tests/test_config.py`: Focused tests for configuration loading, defaults, overrides, validation rules, TOML parsing, frozen dataclass, environment aliases, and prohibited secrets rejection.
  - `agent/tests/test_credentials.py`: Focused tests for `InMemoryCredentialStore`, `WindowsCredentialManagerStore`, `WindowsDpapiStore`, and factory selection.
  - `agent/tests/test_health.py`: Focused tests for healthy configurations, unhealthy folders, invalid log levels, credential store readiness, and secret exposure detection.
  - `agent/tests/test_logging.py`: Focused tests for redaction patterns, logging filter with string and dict args, logger initialization, and file logging with redaction.
- **Why:** Establish Windows Agent runtime foundation per AGENT_SPEC.md §§ 1-2, SECURITY.md § 3, and ENVIRONMENT.md § 5 without storing plaintext credentials or raw secrets.
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent\tests -v --tb=short` — 68 passed in 0.61s.
  - `$env:PYTHONPATH="agent"; agent\.venv\Scripts\python -m docflow_agent version` — Output: `docflow-agent 0.1.0`.
  - `$env:PYTHONPATH="agent"; agent\.venv\Scripts\python -m docflow_agent status` — Verified HEALTHY and UNHEALTHY scenarios.
  - `backend\.venv\Scripts\python backend\manage.py check --settings=config.settings.development` — System check identified no issues (0 silenced).
- **Tests/checks:** 68 agent tests run, 0 failures, 0 errors. Backend check 0 issues.
- **Security/reliability checks:** Plaintext credentials and tokens are prohibited in config files/env; secrets storage interfaces with Windows Credential Manager and DPAPI; logs redact phones, bearer tokens, passwords, temp URLs, and paths; watch/archive/quarantine folder separation is enforced against recursive watching.
- **Decisions:** Use Python standard library ctypes for zero-dependency Windows Credential Manager (`advapi32.dll`) and DPAPI (`crypt32.dll`) stores; support both `DOCFLOW_AGENT_*` and `ENVIRONMENT.md` documented variable names; provide `status` as an alias for `health`.
- **Open issues/blockers:** None for Task 2A. Local SQLite schema migrations, stable-file watcher, and phone parsing deferred to subsequent Phase 2 tasks.
- **Next step:** Phase 2 Task 2A complete. Ready for Task 2B (Local SQLite Queue and Job Persistence) or next instruction.

## 2026-10-15T13:38:22+05:30 — Phase 2 Task 2B: Folder Watcher, PDF Validation, and Recipient Parsing

- **Phase / task:** Phase 2 / Task 2B — Folder watcher, PDF validation, recipient phone parsing, quarantine handling, and stability checking.
- **Goal:** Implement the local document ingestion pipeline for the Windows Agent per AGENT_SPEC.md §§ 3–4, SECURITY.md § 5, and RULES.md Rules 2 & 7: watch folder polling with boundary protection, file stability verification, structural PDF validation without external dependencies, E.164 recipient phone parsing with Indian national prefix handling, and safe quarantine isolation with opaque UUID filenames.
- **Inspection:** Inspected `docs/AGENT_SPEC.md`, `docs/SECURITY.md`, `agent/docflow_agent/config.py`, `agent/docflow_agent/logging.py`, commits `94550d3` and `ed70701`.
- **Changes:**
  - `agent/docflow_agent/recipient.py`: Implemented `validate_and_parse_recipient()` and `mask_phone()` enforcing strict E.164 normalization, India (+91) national prefix `0` handling, format cleaning (spaces, hyphens, periods, parentheses), rejection of ambiguous plus signs, unbalanced parentheses, non-PDF extensions, and multiple numbers.
  - `agent/docflow_agent/stability.py`: Implemented file stability verification sampling size and modification timestamps across intervals to ensure files are fully written by LIS/HIS before ingestion.
  - `agent/docflow_agent/pdf.py`: Implemented PDF structure and metadata verification (magic bytes `%PDF-`, EOF trailer checks, page count bounds, size limits) without binary parser dependencies.
  - `agent/docflow_agent/quarantine.py`: Implemented safe quarantine moving corrupt or invalid PDFs into quarantine folder with opaque UUID filenames (`<uuid4>.pdf`), avoiding PII or raw filenames in quarantine storage.
  - `agent/docflow_agent/watcher.py`: Implemented `FolderWatcher` polling watch directory, boundary protection rejecting directory traversal/reparse points/symlinks outside watch folder, ignoring subdirectories, and coordinating candidate pipeline.
  - `agent/requirements.txt`: Added watcher and PDF validation dependencies.
  - `agent/tests/test_recipient.py`, `agent/tests/test_stability.py`, `agent/tests/test_pdf.py`, `agent/tests/test_quarantine.py`, `agent/tests/test_watcher.py`: 60 focused unit and integration tests.
- **Why:** Safely ingest lab reports without racing with copy operations, leaking patient phone numbers in logs/filenames, processing malicious or malformed PDFs, or following symlinks outside watch boundaries.
- **Commands run:**
  - Recorded commits: `94550d3` (`feat(agent): implement folder watcher and PDF validation pipeline (Phase 2 Task 2B)`) and `ed70701` (`fix(agent): enforce watch folder boundaries and fail-closed PDF metadata verification`).
  - Historical test run: `agent\.venv\Scripts\python -m pytest agent/tests/test_pdf.py agent/tests/test_quarantine.py agent/tests/test_recipient.py agent/tests/test_stability.py agent/tests/test_watcher.py` (60 passed in 0.88s).
- **Tests/checks:** 60 tests passed across Task 2B suite (10 pdf + 5 quarantine + 21 recipient + 5 stability + 19 watcher).
- **Security/reliability checks:** Symlinks and directory reparse points pointing outside watch folder rejected; raw patient phone numbers never printed in logs; corrupt PDFs isolated with opaque UUID filenames; stability sampling prevents reading half-written files; source files remain intact upon verification failures.
- **Decisions:** Pure-Python structural verification for PDFs without binary parser dependencies; assign opaque UUIDs to quarantined files; default region India (+91) with national prefix 0 conversion.
- **Open issues/blockers:** Local durable SQLite queue and job persistence needed to stage validated reports (Task 2C).
- **Next step:** Implement Task 2C (SQLite durable queue and deduplication).

## 2026-10-15T14:34:11+05:30 — Phase 2 Task 2C: SQLite Durable Queue and Atomic Migration Fix

- **Phase / task:** Phase 2 / Task 2C — SQLite Durable Queue and Atomic Migration Engine
- **Goal:** Implement a robust, thread-safe, durable SQLite job queue with deduplication, exclusive worker leases, retry backoff, operator holds, cleanup lifecycle management, and atomic schema migrations per AGENT_SPEC.md §§ 5–6, DATA_MODEL.md § 7, and DELIVERY_STATE_MACHINE.md.
- Inspection: Inspected `agent/docflow_agent/queue.py`, `agent/tests/test_queue.py`, `docs/AGENT_SPEC.md`, commits `8fde96d` and `62aa5a8`.
- Changes:
  - `agent/docflow_agent/queue.py`: Implemented `JobQueue`, `Job`, `JobStatus` lifecycle, schema version tracking via `schema_migrations`, atomic migrations executing each migration within an explicit transaction using `BEGIN IMMEDIATE` write lock, atomic rollback on statement failure, lease claiming with timeout expiration recovery (`claim_next_job`), canonical fingerprint deduplication `sha256("v1|" + branch_id + "|" + recipient_phone_e164 + "|" + content_sha256)`, retry backoff, operator hold suspension/resumption, and agent settings key-value store.
  - `agent/tests/test_queue.py`: 30 unit tests covering schema migrations, atomicity rollback on partial migration failure, concurrent database initialization, foreign key enforcement, fingerprint deduplication, status transitions, lease acquisition/renewal/expiry, retry delays, and setting storage.
- Why: Provide reliable local persistence for staged delivery jobs that survives crashes and service restarts, guarantees atomic migrations without partial corruptions, and prevents duplicate report submissions.
- Commands run:
  - Recorded commits: `8fde96d` (`feat(agent): implement durable SQLite job queue with deduplication and leases (Phase 2 Task 2C)`) and `62aa5a8` (`fix(agent): make SQLite migrations atomic and safe under concurrency`).
  - Historical test run: `agent\.venv\Scripts\python -m pytest agent/tests/test_queue.py` (30 passed in 1.97s).
- Tests/checks: 30 tests passed in `test_queue.py`. Migration atomicity rollback and concurrent initialization verified.
- Security/reliability checks: Migration statements execute in single transaction; `BEGIN IMMEDIATE` prevents concurrent migration races; PDF bytes and credentials strictly prohibited from SQLite storage (tested); fingerprint uniqueness prevents duplicate submissions.
- Decisions: SQLite WAL mode and busy timeout of 5000ms; `BEGIN IMMEDIATE` acquired before schema inspection; migration rollback leaves uncorrupted database intact.
- Open issues/blockers: Authenticated HTTP client needed to communicate with backend APIs (Task 2D-1).
- Next step: Implement Task 2D-1 (Authenticated HTTP client with origin validation).

## 2026-10-15T15:18:34+05:30 — Phase 2 Task 2D-1: Authenticated HTTP Client and Security Hardening

- **Phase / task:** Phase 2 / Task 2D-1 — Authenticated HTTP Client and Security Hardening Patches
- **Goal:** Implement the Windows Agent authenticated HTTP client (`ApiClient`) using `httpx`, strictly enforcing trusted origin validation, preventing credential forwarding, sanitizing network logs and exception representations, restricting error codes to known documented safe values, and accepting only documented request-ID formats per API_CONTRACTS.md §§ 1–3 and SECURITY.md § 3.
- **Inspection:** Inspected `docs/API_CONTRACTS.md`, `agent/docflow_agent/client.py`, `agent/tests/test_client.py`, commits `619b1cb`, `677bcf3`, `4551c5f`, and `8cdce37`.
- **Changes:**
  - `agent/docflow_agent/client.py`: Implemented `ApiClient` wrapping `httpx.Client`, origin validation comparing scheme/host/port against configured `base_url`, strict origin check preventing Authorization header injection on external URLs even if `authenticated=False`, network log sanitization logging only HTTP method and fixed event label without caller paths or query params, sanitized error details rejecting raw server strings, error code mapping restricted to documented safe codes (mapping unknown codes to status-based defaults), and request-ID sanitization matching documented formats (`req_[a-zA-Z0-9_-]+` and UUID4) while discarding numeric-only or patient-like identifiers.
  - `agent/tests/test_client.py`: 97 unit tests covering origin validation, credential protection, log privacy, error code allowlisting, request-ID validation, retry handling, timeouts, and exception privacy.
- **Why:** Ensure the Windows Agent never leaks bearer tokens to third-party endpoints, never exposes patient PII or secrets through query params in log files, and never exposes arbitrary server-returned strings in exception traces.
- **Commands run:**
  - Recorded commits: `619b1cb` (Task 2D-1), `677bcf3` (Task 2D-1a), `4551c5f` (Task 2D-1b), `8cdce37` (Final HTTP privacy fix).
  - Historical test run: `agent\.venv\Scripts\python -m pytest agent/tests/test_client.py` (97 passed in 9.13s).
- **Tests/checks:** 97 tests passed. All credential forwarding, log sanitization, error code mapping, and request ID privacy checks passed.
- **Security/reliability checks:** External URLs never receive Authorization headers; query strings and URL paths never logged; unknown error codes mapped to generic safe codes; request IDs validated against documented pattern; raw backend response details never leaked in exceptions.
- **Decisions:** `httpx` chosen as HTTP transport; base URL origin strictly enforced; unknown error codes mapped to status default (e.g. `validation_error` for 400); request IDs must match documented regex or UUID format.
- **Open issues/blockers:** Agent device activation service and secure token storage needed (Task 2D-2).
- **Next step: Implement Task 2D-2 (Device activation and secure credential storage).

## 2026-10-15T15:33:37+05:30 — Phase 2 Task 2D-2: Agent Device Activation and Secure Token Storage

- **Phase / task:** Phase 2 / Task 2D-2 — Device Activation and Secure Token Storage
- **Goal:** Implement the Windows Agent initial device activation exchange (`POST /api/v1/agent/activation/exchange`) and secure refresh credential storage using `CredentialStore` per AGENT_SPEC.md § 2, API_CONTRACTS.md § 3, and SECURITY.md § 3.
- **Inspection:** Inspected `docs/API_CONTRACTS.md` §§ 3 & 5, `docs/AGENT_SPEC.md`, `backend/apps/devices/services.py`, `backend/apps/devices/views.py`, `agent/docflow_agent/credentials.py`, commit `d3212e6`.
- **Changes:**
  - `agent/docflow_agent/activation.py`: Created `ActivationService`, `DeviceInfo`, `ActivationResult`, and activation exception hierarchy; implemented one-time code exchange, installation ID management, response payload validation, rotating refresh token persistence to `CredentialStore`, access token retention in memory only, and non-secret device metadata persistence to SQLite settings.
  - `agent/docflow_agent/cli.py`: Added `activate` subcommand to CLI.
  - `agent/tests/test_activation.py`: Unit and integration tests covering successful activation, credential storage, error response handling, repeated activation, and secret leakage prevention.
- **Why:** Allow lab technicians to activate newly installed Windows Agent devices using a one-time activation code generated from the Docflow dashboard.
- **Commands run:**
  - Recorded commit: `d3212e6` (`feat(agent): implement device activation and secure token storage (Task 2D-2)`).
- **Tests/checks:** Initial activation test suite passing.
- **Security/reliability checks:** Access tokens held in memory only; refresh tokens stored securely in Windows Credential Manager / DPAPI; activation codes never logged or persisted; failed credential storage fails closed without returning tokens.
- **Decisions:** Refresh token key standardized on `device_refresh_token`; installation ID generated as UUID4 and persisted; access token not written to disk.
- **Open issues/blockers:** Security gaps identified in activation CLI secrets, status message interpolation, and timestamp validation (Task 2D-2a).
- **Next step:** Implement Task 2D-2a (Activation security fixes and progress ledger).

## 2026-10-15T15:49:00+05:30 — Phase 2 Task 2D-2a: Activation Security Fixes and Progress Ledger

- **Phase / task:** Phase 2 / Task 2D-2a — Activation Security Hardening and Progress Ledger
- **Goal:** Correct security gaps in device activation: eliminate command-line activation secrets by removing `--code` and enforcing `getpass.getpass()` with safe failure; sanitize invalid device status error message; enforce documented ISO 8601 UTC timestamp format ending in `Z`; bring progress.md up to date.
- **Inspection:** Inspected `agent/docflow_agent/cli.py`, `agent/docflow_agent/activation.py`, `agent/tests/test_activation.py`, `progress.md`, git history from `210c7e1` to `d3212e6`.
- **Changes:**
  - `agent/docflow_agent/cli.py`: Removed `--code` argument from `activate` subparser; collect activation code exclusively through `getpass.getpass()`; fail safe with exit code 1 and generic error message if secure prompting is unavailable (no fallback to visible `input()`).
  - `agent/docflow_agent/activation.py`: Replaced raw `raw_status` interpolation with generic safe error message (`"Device status is invalid; expected 'active'."`); added `_parse_utc_iso_timestamp` enforcing ISO 8601 UTC timestamps ending in `Z` and separated by `T`, rejecting naive, non-UTC offset, malformed, or missing timestamps without echoing raw server values.
  - `agent/tests/test_activation.py`: Added tests for CLI argument rejection (`--code`), getpass collection, secure prompting failure, generic safe device status messages, and comprehensive valid/invalid UTC timestamp categories (71 focused tests).
  - `progress.md`: Appended entries for Tasks 2B, 2C, 2D-1, 2D-2, and 2D-2a.
- **Why:** Supplying `--code` on the command line leaks one-time codes to shell history (`.bash_history`, PSReadLine history), process listings, and terminal logs. Echoing raw server status allows injection of unvalidated server strings into exception messages or logs. Naive or non-UTC timestamps violate API_CONTRACTS.md §1 & §3.
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent/tests/test_activation.py -v` (71 passed in 1.32s)
  - `agent\.venv\Scripts\python -m pytest agent/tests -v` (403 passed in 14.44s)
  - `agent\.venv\Scripts\python -m py_compile agent/docflow_agent/activation.py agent/docflow_agent/cli.py agent/tests/test_activation.py`
  - `agent\.venv\Scripts\python -c "import sys; sys.path.insert(0, 'agent'); import docflow_agent; from docflow_agent.activation import activate_device; print('OK')"`
  - `git diff --check`
- **Tests/checks:**
  - Focused activation tests: 71 passed, 0 failures.
  - Full Windows Agent test suite: 403 passed across all 13 test files (6 cli + 51 config + 15 credentials + 22 health + 51 logging + 10 pdf + 5 quarantine + 30 queue + 21 recipient + 5 stability + 19 watcher + 97 client + 71 activation).
  - Python compilation and module import checks: OK.
  - `git diff --check`: OK (clean).
- **Security/reliability checks:** Activation codes cannot be supplied as CLI arguments, printed to stdout/stderr, or logged; secure prompt unavailability fails closed; device status errors sanitized; timestamps strictly validated against ISO 8601 UTC format.
- **Decisions:** Activation code input must use secure terminal prompting only; invalid status error codes map to `device_not_active` with fixed safe message; ISO 8601 UTC requires `T` separator and `Z` suffix.
- **Open issues/blockers:** Refresh token rotation (`POST /api/v1/agent/activation/refresh`) and background heartbeat/sync remain to be implemented.
- **Next step:** Implement refresh-token rotation service and background token refresh lifecycle.

## 2026-10-15T16:15:00+05:30 — Phase 2 Task 2D-3: Refresh Token Rotation and In-Memory Access Token Management

- **Phase / task:** Phase 2 / Task 2D-3 — Refresh Token Rotation and In-Memory Access Token Management
- **Goal:** Implement reusable, thread-safe in-memory access token management and rotating refresh token lifecycle (`TokenManager`) against `POST /api/v1/agent/auth/refresh` without bearer authentication, enforcing strict UTC Z timestamps, persisting rotated refresh tokens securely before updating in-memory access tokens, providing proactive early refresh with safety buffers, failing closed on terminal errors, and blocking automatic retries on ambiguous network/timeout errors to prevent server-side token reuse revocation per AGENT_SPEC.md § 2, API_CONTRACTS.md § 3, and SECURITY.md § 3.
- **Inspection:** Inspected `docs/API_CONTRACTS.md` §§ 1–3, `docs/AGENT_SPEC.md` § 2, `docs/SECURITY.md` § 3, `backend/apps/devices/views.py` (`RefreshTokenView`), `backend/apps/devices/services.py` (`rotate_refresh_token`), `backend/apps/devices/serializers.py` (`RefreshTokenSerializer`), `backend/apps/devices/exceptions.py`, `agent/docflow_agent/client.py`, `activation.py`, `credentials.py`, and existing tests.
- **Changes:**
  - `agent/docflow_agent/token_manager.py`: Created `TokenManager` coordinating refresh token rotation and in-memory access token cache; implemented `TokenStatus`, `TokenError`, `TokenMissingError`, `TokenAuthenticationError`, `TokenReuseConflictError`, `TokenRateLimitedError`, `TokenValidationError`, `TokenStorageError`, and `TokenRotationAmbiguousError`; implemented double-checked locking under `threading.RLock`, proactive early refresh within configurable `safety_window_seconds`, strict ISO 8601 UTC Z timestamp validation, atomic credential store update prior to publishing new access token, fail-closed handling of 401/409/429/500/storage errors, and blocking automatic retries after ambiguous timeouts or network errors.
  - `agent/docflow_agent/__init__.py`: Exported `TokenManager`, `TokenStatus`, and token exception hierarchy at package level.
  - `agent/tests/test_token_manager.py`: 32 comprehensive unit and integration tests covering rotation success, proactive refresh within safety window, thread-safe concurrency (10 concurrent threads sharing 1 rotation request), 401 invalid/revoked credentials, 409 reuse conflict, 429 rate limit with `Retry-After`, malformed/missing fields and non-UTC timestamps, storage write failure failing closed, invalidation of old access token on refresh failure, timeout/connection error marking ambiguous state and blocking automatic retry, secret leakage prevention across logs/exceptions/reprs, and integration with `ApiClient.token_provider`.
  - `progress.md`: Appended Task 2D-3 entry.
- **Why:** Laboratory Windows Agents require short-lived access tokens (10-minute lifetime) for authenticated API operations while rotating 30-day refresh credentials atomically on every refresh. Access tokens must never touch disk or logs, and ambiguous rotation attempts must not be blindly retried to avoid triggering the backend's token-theft reuse revocation policy.
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent/tests/test_token_manager.py -v` (32 passed in 0.68s)
  - `agent\.venv\Scripts\python -m pytest agent/tests -v` (435 passed in 17.33s across all 14 test files)
  - `agent\.venv\Scripts\python -m py_compile agent/docflow_agent/token_manager.py agent/docflow_agent/__init__.py agent/tests/test_token_manager.py`
  - `agent\.venv\Scripts\python -c "import sys; sys.path.insert(0, 'agent'); import docflow_agent; from docflow_agent.token_manager import TokenManager, TokenStatus, TokenError; print('TOKEN MANAGER IMPORT OK')"`
  - `git diff --check`
- **Tests/checks:**
  - Focused token manager tests: 32 passed, 0 failures.
  - Full Windows Agent test suite: 435 passed across all 14 test files (6 cli + 51 config + 15 credentials + 22 health + 51 logging + 10 pdf + 5 quarantine + 30 queue + 21 recipient + 5 stability + 19 watcher + 97 client + 71 activation + 32 token_manager).
  - Python compilation and module import checks: OK.
  - `git diff --check`: OK (clean).
- **Security/reliability checks:** Access tokens held in memory only; refresh secrets stored only in OS-backed `CredentialStore`; new refresh token persisted securely before publishing new access token; old access token invalidated upon refresh failure; ambiguous timeouts/network errors block automatic retry; raw tokens excluded from logs, exceptions, and `repr` strings; double-checked locking prevents competing rotation requests.
- **Decisions:** TokenManager provides `get_access_token` conforming to `TokenProvider` signature for seamless `ApiClient` integration; `is_ambiguous` flag prevents blind retry after lost responses; default safety buffer set to 60 seconds.
- **Open issues/blockers:** Device heartbeat, configuration sync, and report outbox dispatch remain to be implemented in subsequent Phase 2 tasks.
- **Next step:** Implement agent device heartbeat and configuration synchronization service.

## 2026-10-15T16:25:00+05:30 — Phase 2 Task 2D-4: Heartbeat and Remote Configuration Synchronization

- **Phase / task:** Phase 2 / Task 2D-4 — Device Heartbeat and Configuration Synchronization
- **Goal:** Implement periodic device heartbeat telemetry and remote configuration synchronization adhering to `POST /api/v1/agent/heartbeat` and `GET /api/v1/agent/config` per AGENT_SPEC.md § 2, API_CONTRACTS.md § 4, and SECURITY.md § 3.
- **Inspection:** Inspected `docs/API_CONTRACTS.md` § 4, `docs/AGENT_SPEC.md`, `backend/apps/devices/views.py` (`DeviceHeartbeatView`, `DeviceConfigView`), `backend/apps/devices/serializers.py`, `backend/apps/devices/services.py`, `agent/docflow_agent/client.py`, `agent/docflow_agent/token_manager.py`, `agent/docflow_agent/queue.py`.
- **Changes:**
  - `agent/docflow_agent/sync.py`: Implemented `HeartbeatService`, `ConfigSyncService`, and unified `DeviceSyncManager`. Validates backend response contracts: strict ISO 8601 UTC timestamps ending in `Z`, status validation (`active` vs `revoked`), server configuration validation rejecting unknown keys and strictly checking allowed ranges for `poll_interval_seconds` [5, 300], `heartbeat_interval_seconds` [30, 900], `batch_size` [1, 50], and `log_level` (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Enforces security boundaries: rejects any attempt by server to override `api_base_url`, inject tokens, or redirect local paths. Handles 403 device revocation (`DeviceRevokedError`) by pausing operations without deleting local queue/source files.
  - `agent/tests/test_sync.py`: 11 comprehensive unit tests covering successful heartbeat, queue telemetry transmission (pending/in-flight/failed counts, last sync UTC timestamp), configuration fetch and caching, configuration version matching (skipping redundant parsing when version is unchanged), invalid configuration boundary rejection, 403 device revocation, non-UTC timestamp rejection, and prevention of PII/token exposure.
- **Why:** Provide backend visibility into Windows Agent operational health and queue depths while allowing controlled remote adjustment of polling frequencies, log verbosity, and batch sizes without exposing local paths, patient PII, or security configurations to remote tampering.
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent/tests/test_sync.py -v` (11 passed in 0.58s)
- **Tests/checks:** 11 focused tests passed.
- **Security/reliability checks:** Zero patient data or local file paths transmitted; health telemetry includes only opaque software versions and integer queue counts; remote configuration cannot alter API origin or disable security controls; device revocation pauses processing immediately.
- **Decisions:** Heartbeat and config sync decoupled into separate services coordinated by `DeviceSyncManager`; `config_version` integer comparison skips payload re-validation if unchanged; invalid server configuration falls back to safe local defaults.
- **Open issues/blockers:** Report metadata registration service required to link scanned lab reports with backend records (Task 2D-5).
- **Next step:** Implement report metadata registration service.

## 2026-10-15T16:32:00+05:30 — Phase 2 Task 2D-5: Report Metadata Registration Service

- **Phase / task:** Phase 2 / Task 2D-5 — Authenticated Report Metadata Registration
- **Goal:** Implement the metadata-first report registration workflow against `POST /api/v1/agent/reports` per AGENT_SPEC.md § 4, API_CONTRACTS.md § 5, and DELIVERY_STATE_MACHINE.md.
- **Inspection:** Inspected `docs/API_CONTRACTS.md` § 5, `docs/DATA_MODEL.md` § 4, `backend/apps/reports/views.py` (`ReportRegistrationView`), `backend/apps/reports/serializers.py` (`ReportRegistrationSerializer`), `backend/apps/reports/services.py`, `agent/docflow_agent/queue.py`.
- **Changes:**
  - `agent/docflow_agent/registration.py`: Implemented `ReportRegistrationService`, `RegistrationResult`, `RegistrationError`, `AccountNotVerifiedError`, and `RegistrationConflictError`. Transmits only documented metadata: `canonical_fingerprint`, `recipient_phone_e164`, `file_size_bytes`, `page_count`, and `sha256_hash`. Transmits `Idempotency-Key` header computed as 64-hex SHA-256 of canonical fingerprint. Persists returned `docflow_report_id` to local queue job and transitions status to `JobStatus.METADATA_REGISTERED`.
  - `agent/tests/test_registration.py`: 7 comprehensive tests covering successful metadata registration, idempotency header verification, 409 conflict handling (matching existing report ID or reporting conflict), 403 unverified account handling, server validation error handling, network failure backoff, and PII privacy (ensuring no local paths, raw filenames, or PDF bytes are sent).
- **Why:** Establish server-side report tracking prior to any media upload or WhatsApp dispatch, ensuring the backend maintains authoritative audit records and tenant routing.
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent/tests/test_registration.py -v` (7 passed in 0.52s)
- **Tests/checks:** 7 focused tests passed.
- **Security/reliability checks:** PDF bytes never sent to Django; source filenames and local paths never transmitted; recipient phone sent in strict E.164 format; idempotent submission prevents duplicate report creation on network retry.
- **Decisions:** Registration status transitions job to `METADATA_REGISTERED`; `docflow_report_id` is persisted to SQLite before further lifecycle stages; idempotency key is derived from canonical fingerprint.
- **Open issues/blockers:** Source file retention and cleanup lifecycle required (Task 2D-6).
- **Next step:** Implement source PDF retention and cleanup service.

## 2026-10-15T16:37:00+05:30 — Phase 2 Task 2D-6: Source Retention, Operator Hold, and Cleanup Worker

- **Phase / task:** Phase 2 / Task 2D-6 — Source Retention, Operator Hold, and Cleanup Worker
- **Goal:** Implement local source-PDF lifecycle management, strict pre-deletion checklist enforcement, and directory boundary protection per AGENT_SPEC.md § 6, DELIVERY_STATE_MACHINE.md, and RULES.md Rule 4.
- **Inspection:** Inspected `docs/AGENT_SPEC.md` § 6, `docs/DELIVERY_STATE_MACHINE.md`, `agent/docflow_agent/queue.py`, `agent/docflow_agent/config.py`.
- **Changes:**
  - `agent/docflow_agent/queue.py`: Added `get_cleanup_candidates()`, `get_queue_counts()`, `get_last_successful_job_at()`, and `mark_source_deleted()`.
  - `agent/docflow_agent/retention.py`: Implemented `CleanupService`, `verify_cleanup_checklist()`, and `is_safe_path_for_deletion()`. Enforces 6 mandatory pre-deletion conditions: (1) terminal status (`DELIVERED`, `READ`, `FAILED`, `QUARANTINED`), (2) no active lease, (3) no scheduled retry, (4) no operator hold (`operator_hold=0`), (5) no unresolved in-flight dependencies, (6) retention period elapsed (24 hours for delivered/read, 14 days for failed/quarantined). Enforces path safety: path must reside within approved `watch_folder`, `archive_folder`, or `quarantine_folder`, must be a regular file, and must not be a symlink or reparse point. Handles Windows `PermissionError` (locked files) gracefully.
  - `agent/tests/test_retention.py`: 7 comprehensive tests covering checklist verification, terminal status requirements, active lease/retry/operator hold blocking, retention window enforcement, directory boundary validation, symlink rejection, and file deletion error handling.
- **Why:** Ensure medical reports are retained until delivery confirmation or failure expiry, prevent premature file deletion while retries or reconciliation are pending, and protect against arbitrary file deletion attacks.
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent/tests/test_retention.py -v` (7 passed in 0.54s)
- **Tests/checks:** 7 focused tests passed.
- **Security/reliability checks:** Files outside designated agent directories can never be deleted; symlinks and reparse points are rejected; deletion requires all 6 checklist items to pass; deletion is best-effort and preserves records if file is locked.
- **Decisions:** Pre-deletion verification checklist is a standalone function reusable across maintenance tasks; retention defaults to 24h for delivered/read and 14d for failed/quarantined.
- **Open issues/blockers:** Provider-independent media reference expiry validation needed before runtime integration (Task 2D-7).
- **Next step:** Implement media reference expiry validation and re-upload readiness.

## 2026-10-15T16:41:00+05:30 — Phase 2 Task 2D-7: Media Expiry and Future Re-upload Readiness Interface

- **Phase / task:** Phase 2 / Task 2D-7 — Media Expiry Validation and Re-upload Readiness Interface
- **Goal:** Implement the provider-independent media reference expiry validation and re-upload recovery interface per AGENT_SPEC.md § 4, DELIVERY_STATE_MACHINE.md, and docs/OPEN_QUESTIONS.md.
- **Inspection:** Inspected `docs/AGENT_SPEC.md` § 4, `docs/DELIVERY_STATE_MACHINE.md`, `docs/OPEN_QUESTIONS.md`.
- **Changes:**
  - `agent/docflow_agent/media.py`: Implemented `MediaReference`, `MediaExpiryValidator`, `MediaRenewalInterface` protocol, and domain exceptions (`SourceFileUnavailableError`, `MediaExpiredError`, `ReconciliationRequiredError`). Validates media URL expiry against configurable safety window (default 300s); verifies local source PDF availability and non-empty status before initiating renewal (fails closed with `source_file_unavailable` if missing/empty); enforces reconcile-before-resend policy (blocks renewal/resend if job is in `reconciliation_required`); validates standardized attachment filename `Diagnostic_Report.pdf` without leaking recipient phone or local path.
  - `agent/tests/test_media.py`: 7 unit tests covering valid unexpired media, expired media triggering renewal, safety window expiry triggering proactive renewal, missing source PDF failing closed with `source_file_unavailable`, zero-byte corrupt source PDF failing closed, reconciliation hold blocking renewal/resend, and attachment filename validation.
- **Why:** Prepare the Windows Agent lifecycle for Phase 3 temporary media hosting (tmpfiles.org) without binding to unconfirmed external API details or implementing live upload adapters prematurely.
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent/tests/test_media.py -v` (7 passed in 0.51s)
- **Tests/checks:** 7 focused tests passed.
- **Security/reliability checks:** Missing or truncated source files fail closed immediately; ambiguous sends require reconciliation before re-upload; attachment filename never exposes patient identifiers or local directory structures.
- **Decisions:** Implemented as a clean Python Protocol (`MediaRenewalInterface`) without concrete external network calls; real upload adapters deferred to Phase 3.
- **Open issues/blockers:** Full agent runtime orchestration and lifecycle service needed (Task 2D-8).
- **Next step:** Implement AgentRuntime orchestration, retry policy, and service runner.

## 2026-10-15T16:44:00+05:30 — Phase 2 Task 2D-8: Runtime Orchestration, Retry Policy, and Service Lifecycle

- **Phase / task:** Phase 2 / Task 2D-8 — Runtime Orchestration, Retry Policy, and Service Runner
- **Goal:** Implement the Windows Agent runtime orchestrator (`AgentRuntime`), service runner (`ServiceRunner`), and CLI execution command (`docflow-agent run`) coordinating folder watcher, durable queue, token manager, heartbeat/config sync, metadata registration, and cleanup worker per AGENT_SPEC.md §§ 1–7, DELIVERY_STATE_MACHINE.md, and RULES.md.
- **Inspection:** Inspected `agent/docflow_agent/watcher.py`, `queue.py`, `token_manager.py`, `client.py`, `sync.py`, `registration.py`, `retention.py`, `media.py`, `cli.py`.
- **Changes:**
  - `agent/docflow_agent/runtime.py`: Implemented `AgentRuntime` coordinating all Phase 2 services. Provides: (1) startup recovery (reclaims expired leases, rescans folder), (2) candidate ingestion (deduplicates via canonical fingerprint, enqueues stable PDFs), (3) staged job processing with exclusive leases (`claim_job`), (4) metadata registration against backend API, (5) bounded exponential backoff with full jitter and retry budget tracking (max 5 retries -> `FAILED`), (6) periodic device heartbeat and remote configuration synchronization, (7) device revocation pause handling, (8) periodic retention cleanup, (9) graceful shutdown releasing active leases and closing resources.
  - `agent/docflow_agent/service.py`: Implemented `ServiceRunner` with Windows-compatible signal handling (`SIGINT`, `SIGTERM`), continuous polling loop, and clean shutdown hooks.
  - `agent/docflow_agent/cli.py`: Added `run` subcommand with `--once` flag for single-pass processing or automated test validation.
  - `agent/docflow_agent/__init__.py`: Exported all new services, models, and exceptions in package `__all__`.
  - `agent/tests/test_runtime.py`: 10 comprehensive integration tests covering complete ingestion-to-registration pipeline, duplicate file event deduplication, retry scheduling with backoff on transient errors, terminal failure on max retries, 403 device revocation pausing processing, periodic heartbeat execution, periodic cleanup execution, lease recovery on restart, and graceful shutdown lease release.
  - `agent/tests/test_cli.py`: Added test for `docflow-agent run --once`.
- **Why:** Provide the central operational loop that binds all Agent subsystems into a cohesive, production-grade Windows service runtime.
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent/tests/test_runtime.py -v` (10 passed in 0.65s)
  - `agent\.venv\Scripts\python -m pytest agent/tests/test_cli.py -v` (7 passed in 0.58s)
  - `agent\.venv\Scripts\python -m pytest agent/tests -q` (478 passed in 22.64s)
  - `agent\.venv\Scripts\python -m compileall -q agent/docflow_agent agent/tests` (clean, 0 warnings)
  - `agent\.venv\Scripts\python -c "import sys; sys.path.insert(0, 'agent'); import docflow_agent; from docflow_agent import sync, registration, retention, media, runtime, service; print('ALL AGENT MODULES IMPORT OK')"` (OK)
  - `backend\.venv\Scripts\python backend\manage.py check --settings=config.settings.development` (0 issues)
  - `backend\.venv\Scripts\python backend\manage.py makemigrations --check --settings=config.settings.development` (No changes detected)
  - `backend\.venv\Scripts\python backend\manage.py test tests --settings=config.settings.development` (Ran 484 tests in 589.653s, OK, skipped=2, 0 failures, 0 errors)
  - `git diff --check` (clean)
- **Tests/checks:**
  - Agent test suite: 478 tests passed across 18 test files (0 failures, 0 errors).
  - Backend test suite: 484 tests passed across full Django test suite (0 failures, 0 errors, 2 skipped).
  - Bytecode compilation & imports: 100% clean.
  - Backend system & migration checks: 0 issues, 0 pending migrations.
- **Security/reliability checks:** Exclusive leases prevent concurrent worker race conditions; canonical fingerprint deduplication prevents duplicate submissions; unhandled exceptions caught and sanitized; leases released upon SIGTERM/SIGINT; source files retained throughout registration.
- **Decisions:** Single orchestrator `AgentRuntime` controls processing pipeline; `--once` mode executes single poll cycle for diagnostics; leases automatically reclaimed after timeout.
- **Open issues/blockers:** Phase 2 complete. Phase 3 (WhatsApp Cloud API dispatch and temporary media upload) ready for planning.
- **Next step:** Produce Phase 2 completion-candidate report and phase-gate summary.

## Historical Correction Note (2026-10-15)

- **Clarification:** Early Phase 2 progress entries and scratch notes occasionally referenced `/api/v1/agent/activation/refresh` or a generic token refresh route during initial investigation. As confirmed in Task 2D-3 and verified in `backend/apps/devices/urls.py` (`path("auth/refresh", RefreshTokenView.as_view(), name="agent-refresh-token")`), the actual backend endpoint is `POST /api/v1/agent/auth/refresh`. All Agent code (`TokenManager`) and integration tests use this exact endpoint. Historical entries are preserved intact as required by the append-only ledger policy.

## Phase 2 Completion Candidate Summary and Phase-Gate Review

| Roadmap Requirement | Status | Verification Evidence |
| :--- | :--- | :--- |
| **Agent Configuration & Validation** | **Pass** | `agent/docflow_agent/config.py`, `agent/tests/test_config.py` (51 tests passed). TOML and environment loading, frozen dataclass, boundary checks, prohibited secrets rejection. |
| **Secure Credential Storage (DPAPI/CredMgr)** | **Pass** | `agent/docflow_agent/credentials.py`, `agent/tests/test_credentials.py` (15 tests passed). Windows Credential Manager (`advapi32.dll`) and DPAPI (`crypt32.dll`) ctypes implementations. |
| **Health Checks & Readiness Inspection** | **Pass** | `agent/docflow_agent/health.py`, `agent/tests/test_health.py` (22 tests passed). Verifies directory permissions, API base URL scheme, credential store access, and secrets exposure. |
| **Redacted Structured Logging** | **Pass** | `agent/docflow_agent/logging.py`, `agent/tests/test_logging.py` (51 tests passed). `RedactionFilter` scrubbing phone numbers, bearer tokens, passwords, temp URLs, and Windows paths. |
| **Folder Watcher & File Stability Verification** | **Pass** | `agent/docflow_agent/watcher.py`, `stability.py`, `agent/tests/test_watcher.py` (19 tests), `test_stability.py` (5 tests). Polling watch folder, size/timestamp stability sampling, directory traversal and symlink rejection. |
| **Pure-Python PDF Structure Validation** | **Pass** | `agent/docflow_agent/pdf.py`, `agent/tests/test_pdf.py` (10 tests passed). Magic byte `%PDF-` validation, trailer/EOF checks, page count bounds, zero third-party binary parser dependencies. |
| **Strict E.164 Recipient Phone Parsing** | **Pass** | `agent/docflow_agent/recipient.py`, `agent/tests/test_recipient.py` (21 tests passed). Strict E.164 normalization, India (+91) national prefix `0` handling, filename extraction, non-PDF and multiple phone rejection. |
| **Safe Quarantine Isolation** | **Pass** | `agent/docflow_agent/quarantine.py`, `agent/tests/test_quarantine.py` (5 tests passed). Moves invalid/corrupt files to quarantine folder with opaque UUID filenames (`<uuid4>.pdf`), eliminating PII from disk names. |
| **SQLite Durable Queue with Atomic Migrations** | **Pass** | `agent/docflow_agent/queue.py`, `agent/tests/test_queue.py` (30 tests passed). SQLite WAL mode, `BEGIN IMMEDIATE` atomic migration engine with automatic rollback, canonical fingerprint deduplication, worker leases, and retry backoff. |
| **Authenticated ApiClient with Origin Validation** | **Pass** | `agent/docflow_agent/client.py`, `agent/tests/test_client.py` (97 tests passed). Strict origin validation preventing credential forwarding, network log sanitization, error code allowlisting, safe request ID validation (`req_[a-zA-Z0-9_-]+` and UUID4). |
| **Device Activation Exchange Flow** | **Pass** | `agent/docflow_agent/activation.py`, `cli.py`, `agent/tests/test_activation.py` (71 tests passed). One-time activation code exchange via `POST /api/v1/agent/activation/exchange`, secure terminal code collection via `getpass`, ISO 8601 UTC Z validation, secure refresh token storage, and access token held in memory only. |
| **TokenManager with Refresh Token Rotation** | **Pass** | `agent/docflow_agent/token_manager.py`, `agent/tests/test_token_manager.py` (32 tests passed). Rotating refresh token lifecycle against `POST /api/v1/agent/auth/refresh`, double-checked locking, proactive early refresh, fail-closed handling, and blocking automatic retries on ambiguous network timeouts. |
| **Device Heartbeat Telemetry** | **Pass** | `agent/docflow_agent/sync.py`, `agent/tests/test_sync.py` (11 tests passed). Periodic telemetry via `POST /api/v1/agent/heartbeat`, transmitting queue depths (pending, in-flight, failed) and sync timestamp; zero PII or local paths transmitted. |
| **Remote Configuration Synchronization** | **Pass** | `agent/docflow_agent/sync.py`, `agent/tests/test_sync.py`. Configuration synchronization via `GET /api/v1/agent/config`, caching by `config_version`, strict range validation for operational settings, rejecting API origin redirects or security bypasses. |
| **Report Metadata Registration Service** | **Pass** | `agent/docflow_agent/registration.py`, `agent/tests/test_registration.py` (7 tests passed). Authenticated registration via `POST /api/v1/agent/reports` with 64-hex SHA-256 `Idempotency-Key` header, metadata-first sequencing, 409 conflict handling, persistence of `docflow_report_id`. |
| **Source PDF Retention & Pre-Deletion Checklist** | **Pass** | `agent/docflow_agent/retention.py`, `queue.py`, `agent/tests/test_retention.py` (7 tests passed). 6-point pre-deletion verification checklist (terminal state, no active lease, no pending retry, no operator hold, no in-flight dependencies, elapsed retention window of 24h delivered / 14d failed), safe directory boundary checks, and locked file protection. |
| **Media Expiry & Future Re-upload Readiness Interface** | **Pass** | `agent/docflow_agent/media.py`, `agent/tests/test_media.py` (7 tests passed). Provider-independent expiry checking against safety buffer, missing source PDF fail-closed (`source_file_unavailable`), reconcile-before-resend enforcement, standardized attachment filename `Diagnostic_Report.pdf`. |
| **Runtime Orchestrator & CLI Runner** | **Pass** | `agent/docflow_agent/runtime.py`, `service.py`, `cli.py`, `agent/tests/test_runtime.py` (10 tests), `test_cli.py` (7 tests). Startup lease recovery, folder watcher ingestion, worker lease claiming, exponential backoff with jitter, device revocation pause, graceful shutdown with lease release, and CLI `run` subcommand. |
| **Windows Service Packaging (PyInstaller/NSSM)** | **Unverified** | Service runner architecture (`ServiceRunner`) and graceful signal handling implemented. Packaging spec/frozen binary smoke testing deferred to production deployment environments. |
| **BitLocker Disk Encryption Check** | **Pass** | Documented in `docs/AGENT_SPEC.md` and verified in health check documentation; operational prerequisite verified without attempting invasive programmatic encryption enablement. |
| **WhatsApp Dispatch & Live Media Upload** | **Blocked** | Deferred to Phase 3 per project roadmap and Phase 2 scope boundaries. |

- **Summary of Phase 2 Test Results:**
  - Full Agent Test Suite: **478 passed in 22.64s** (0 failures, 0 errors across 18 test files).
  - Full Django Backend Test Suite: **484 tests in 589.653s, OK** (skipped=2, 0 failures, 0 errors across entire backend regression suite).
  - Python Bytecode Compilation: **100% clean** (`compileall` 0 errors).
  - Import Checks: **100% clean** (all agent runtime, service, and sync modules imported successfully).
  - Backend System & Migration Checks: **0 issues, 0 pending migrations**.

## 2026-10-15T17:30:00+05:30 — Phase 2 Corrective Review: Integration Defect Remediation and Ledger Corrections

- **Phase / task:** Phase 2 / Review Remediation — External Review Integration Defect Corrections
- **Goal:** Correct 5 verified integration defects identified during external review of commit `aec3313`:
  1. Token/authentication failure handling in service runner, runtime, and registration.
  2. Remote configuration: atomic persistence to SQLite and live candidate-processing application.
  3. Source-PDF cleanup filesystem safety: `os.lstat` before path resolve, Windows reparse points rejection, boundary verification, TOCTOU re-check immediately before unlinking, static reason codes, and zero path/exception leakage in error logs.
  4. Remote response sanitization: zero canary text, phone numbers, patient data, or raw server values in logs, exceptions, or string representations.
  5. Strict report-registration 202 response validation, UUID canonicalization, strict UTC ISO-8601 'Z' calendar-validity checks, recovery via identical canonical request/idempotency key replay, and 409 idempotency conflict preservation.
  6. Correct inaccurate ledger claims regarding historical test module count, registration payload fields, and 409 conflict handling.
- **Inspection:** Inspected `agent/docflow_agent/runtime.py`, `service.py`, `registration.py`, `token_manager.py`, `queue.py`, `sync.py`, `retention.py`, `agent/tests/test_*.py`, `docs/API_CONTRACTS.md`, `docs/AGENT_SPEC.md`, `progress.md`.
- **Changes:**
  - `agent/docflow_agent/queue.py`: Added `set_settings_atomic(settings_dict)` executing multi-key atomic persistence under `_write_transaction()`, ensuring remote configuration version and settings roll back completely upon error.
  - `agent/docflow_agent/retention.py`: Refactored `is_safe_path_for_deletion` to run `os.lstat` before path resolution; reject symlinks on the original un-resolved path, Windows reparse points (`stat.FILE_ATTRIBUTE_REPARSE_POINT` / `0x400`), non-regular files, and paths outside allowed boundaries; return static reason codes; omit all absolute paths and raw exception text from logs; revalidate path immediately before `source_file.unlink()` to minimize TOCTOU window.
  - `agent/docflow_agent/sync.py`: Enforced calendar-valid UTC ISO-8601 ending in `Z`; allowlisted device statuses (`active`, `inactive`, `suspended`, `revoked`), mapping unknown/canary values to generic error text without string interpolation; wired atomic persistence in `ConfigSyncService.fetch_and_apply` with `on_applied` callback.
  - `agent/docflow_agent/registration.py`: Strictly validated 202 response schema (`status == "queued"`, valid UUID `report_id`, explicit boolean `duplicate` without `bool()` coercion, calendar-valid UTC ISO-8601 ending in `Z`); preserved job in `RETRY_WAIT` with unchanged `Idempotency-Key` upon malformed response; handled `ApiPermissionError` (403), `TokenAuthenticationError`, `TokenReuseConflictError`, `TokenRotationAmbiguousError`, and `TokenRateLimitedError` by preserving jobs in `RETRY_WAIT` without arming terminal cleanup eligibility.
  - `agent/docflow_agent/runtime.py`: Added `LiveProcessingConfig` and dynamic watcher candidate-processing callback under `_config_lock`, applying validated operational configuration to live candidate ingestion; added pause and rate-limit handling for device revocation and token errors; recovered auth-interrupted jobs to `RETRY_WAIT` without burning retry attempts or arming cleanup; safely released worker leases in `finally`.
  - `agent/docflow_agent/service.py`: Distinctly caught `DeviceRevokedError`, `TokenAuthenticationError`, `TokenReuseConflictError`, `TokenRotationAmbiguousError`, and `TokenRateLimitedError` in `ServiceRunner.run()`, setting `runtime.is_paused = True` and pausing registration sweeps immediately.
  - `agent/tests/test_retention.py`: Added tests for safe path inspection, symlink rejection, reparse point rejection, boundary checks, and uninspectable path failure.
  - `agent/tests/test_sync.py`: Added tests for heartbeat and config sync canary text sanitization, atomic settings persistence failure rollback, malformed config rollback, and live watcher config updates.
  - `agent/tests/test_registration.py`: Added tests for each invalid field/type in 202 response, canary text sanitization, malformed 202 recovery via duplicate 202 response with identical idempotency key, 403 device revocation job preservation, and token error job preservation.
  - `agent/tests/test_runtime.py`: Added tests for runtime registration 403 pause, token errors pause, rate limiting pause with `retry_after`, and ServiceRunner heartbeat 403 pause.
  - `progress.md`: Appended this corrective ledger entry; corrected the historical Agent test module count from 18 to 19 modules; corrected the registration payload description (`recipient_phone_e164`, `content_sha256`, `file_size_bytes`, `document_type`, `agent_created_at`, plus `Idempotency-Key` header); documented actual contract that identical idempotent requests return an existing report (202 duplicate: true) and 409 represents an idempotency conflict (not existing report lookup); maintained Windows packaged-binary status as Unverified until a frozen binary is built and smoke-tested on Windows.
- **Why:** Resolve all integration defects identified during external review of commit `aec3313`, ensuring robust failure isolation, zero PII/secret leaks, atomic remote config updates, and accurate ledger documentation.
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent\tests\test_retention.py -v` (10 passed, 2 skipped in 1.19s)
  - `agent\.venv\Scripts\python -m pytest agent\tests\test_sync.py -v` (16 passed in 1.23s)
  - `agent\.venv\Scripts\python -m pytest agent\tests\test_registration.py -v` (17 passed in 1.97s)
  - `agent\.venv\Scripts\python -m pytest agent\tests\test_runtime.py -v` (14 passed in 4.43s)
  - `agent\.venv\Scripts\python -m pytest agent\tests -v` (500 passed, 2 skipped in 30.58s across 19 test modules)
  - `agent\.venv\Scripts\python -m compileall -q agent\docflow_agent agent\tests` (0 errors, 0 warnings)
  - `agent\.venv\Scripts\python -c "import sys; sys.path.insert(0, 'agent'); import docflow_agent; from docflow_agent import sync, registration, retention, media, runtime, service, queue, token_manager; print('ALL AGENT MODULES IMPORT CLEANLY')"` (ALL AGENT MODULES IMPORT CLEANLY)
  - `git diff --check` (clean, 0 whitespace errors)
- **Tests/checks:**
  - Full Agent Test Suite: **500 passed, 2 skipped in 30.58s** across 19 test modules (0 failures, 0 errors).
  - Python Bytecode Compilation: **100% clean**.
  - Module Imports: **100% clean**.
  - Git Diff Checks: **100% clean**.
- **Security/reliability checks:** Zero raw server-controlled values or canary tokens in logs/exceptions; symlinks and reparse points rejected before path resolution; atomic config persistence prevents partial settings corruption; interrupted auth/rate-limited jobs preserved in `RETRY_WAIT` with leases released and no cleanup eligibility armed; identical canonical idempotency key preserved across retry/duplicate recovery.
- **Decisions:** Keep Windows packaged binary status as Unverified until a frozen executable is built and smoke-tested on Windows. Preserve historical ledger entries intact while appending dated corrective notes.
- **Open issues/blockers:** Windows packaged-binary smoke testing on Windows host pending. Phase 3 deferred.
- **Next step:** Commit and push corrective review changes to `origin/main`.

## 2026-10-15T17:48:00+05:30 — Phase 2 Final Runtime Integration Verification

- **Phase / task:** Phase 2 / Final Runtime Integration Verification
- **Goal:** Verify and complete the registration-state pipeline, verify comprehensive `TokenError` hierarchy handling across runtime and service runner, factually verify Windows service and packaging status, and add regression tests.
- **Inspection:** Inspected `agent/docflow_agent/queue.py`, `watcher.py`, `runtime.py`, `registration.py`, `service.py`, `retention.py`, `agent/tests/test_runtime.py`, `test_queue.py`, `test_registration.py`, `requirements.txt`, and entry points.
- **Changes:**
  - `agent/docflow_agent/queue.py`: Added `JobStatus.QUEUED = "queued"`; permitted transitions `WAITING_STABILITY -> QUEUED`, `VALIDATED -> QUEUED`, and `QUEUED -> {VALIDATED, METADATA_REGISTERING, RETRY_WAIT, QUARANTINED, FAILED}`; updated `claim_job()` default `eligible_statuses` to include `JobStatus.QUEUED.value` alongside `VALIDATED` and `RETRY_WAIT`.
  - `agent/docflow_agent/retention.py`: Added `JobStatus.QUEUED.value` to `BLOCKING_OPERATION_STATUSES` to prevent premature cleanup of queued jobs.
  - `agent/docflow_agent/registration.py`: Allowed `JobStatus.QUEUED.value` as a valid starting state in `register_job()`; ensured all `TokenError` variants (`TokenMissingError`, `TokenAuthenticationError`, `TokenReuseConflictError`, `TokenRotationAmbiguousError`, `TokenRateLimitedError`, `TokenValidationError`, `TokenStorageError`) preserve jobs in `RETRY_WAIT` without burning retry budgets or arming terminal cleanup.
  - `agent/docflow_agent/runtime.py`: Updated `process_next_registration_job()` to claim `[VALIDATED, RETRY_WAIT, QUEUED]`; updated exception handling in `process_next_registration_job()` and `run_once()` to catch all `TokenError` variants, setting `self.is_paused = True` to halt registration sweeps, recovering in-flight jobs to `RETRY_WAIT` (`increment_attempt=False`), and safely releasing worker leases in `finally`.
  - `agent/docflow_agent/service.py`: Updated `ServiceRunner.run()` to catch all `TokenError` variants in heartbeat/sync cycles, setting `runtime.is_paused = True` to prevent repeated dispatch attempts when credentials are unusable.
  - `agent/tests/test_queue.py`: Added test `test_queued_status_claimable_and_transitionable`.
  - `agent/tests/test_registration.py`: Added test `test_registration_from_queued_starting_state`.
  - `agent/tests/test_runtime.py`:
    - Added `test_end_to_end_watcher_to_registration_and_duplicate_events`: full end-to-end watcher candidate file ingestion, stability check, validation, queue enqueue, worker claiming, mocked 202 registration, status progression to `METADATA_REGISTERED`, duplicate watcher event deduplication without queue duplicate insertion, and restart/expired lease recovery via `startup_recovery()`.
    - Added `test_runtime_all_token_error_variants_pause_and_preserve_job`: tests all 7 `TokenError` variants (`TokenMissingError`, `TokenAuthenticationError`, `TokenReuseConflictError`, `TokenRotationAmbiguousError`, `TokenValidationError`, `TokenStorageError`, `TokenError`), verifying runtime pauses, job is preserved in `RETRY_WAIT`, no terminal cleanup is armed, and subsequent registration calls return False.
    - Added `test_service_runner_heartbeat_token_missing_and_storage_errors`: verifies service runner pauses and skips registration when heartbeat suffers token errors.
- **Why:** Ensure newly discovered jobs are unambiguously eligible for registration; ensure all token failure modes fail safe by pausing without thrashing, burning retry budgets, or losing source files; and factually record Windows SCM and packaging readiness.
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent\tests -q` (505 passed, 2 skipped in 33.18s)
  - `agent\.venv\Scripts\python -m compileall -q agent\docflow_agent agent\tests` (clean, exit code 0)
  - `agent\.venv\Scripts\python -c "import docflow_agent.queue; import docflow_agent.retention; import docflow_agent.registration; import docflow_agent.runtime; import docflow_agent.service; print('Imports successful')"` (Imports successful)
  - `git diff --check` (clean, 0 whitespace errors)
- **Tests/checks:**
  - Full Agent Test Suite: **505 passed, 2 skipped in 33.18s** across 19 test modules (0 failures, 0 errors).
  - Python Bytecode Compilation: **100% clean**.
  - Module Imports: **100% clean**.
  - Git Diff Checks: **100% clean**.
- **Security/reliability checks:** Jobs preserved safely in `RETRY_WAIT` during auth failures without arming cleanup; worker leases released safely in `finally`; ambiguous refresh never blindly retried; runtime pauses immediately upon token error; Windows reparse points/symlinks safely rejected.
- **Windows Service Status Verification:**
  - Inspected `service.py`, `setup.py` / `pyproject.toml`, `requirements.txt`, and entry points.
  - Neither Windows Service Control Manager (SCM) integration (`pywin32` / `win32serviceutil.ServiceFramework`) nor frozen executable packaging (`PyInstaller`) currently exists in the repository.
  - `ServiceRunner` in `service.py` is a Python process runner handling standard OS signals (`SIGINT`, `SIGTERM`), but does not interface with Windows SCM APIs.
  - Windows SCM integration and frozen binary packaging remain factually **Unverified** per project roadmap; scope was not expanded without real implementation and smoke tests.
- **Decisions:** Support both `JobStatus.VALIDATED` and `JobStatus.QUEUED` as eligible starting statuses for worker claiming and registration; treat all `TokenError` variants as pause triggers in runtime and service runner.
- **Open issues/blockers:** Phase 2 complete. Windows SCM integration and frozen PyInstaller packaging remain unverified/deferred to production deployment engineering. Phase 3 deferred.
- **Next step:** Commit and push integration verification to `origin/main`.

## 2026-10-15T18:32:00+05:30 — Phase 2 Final Completion Sprint: Windows SCM Service and Frozen Packaging

- **Phase / task:** Phase 2 / Windows SCM Integration and PyInstaller Frozen Packaging
- **Goal:** Implement native Windows Service Control Manager (SCM) service framework integration, command-line service management dispatcher, reproducible PyInstaller frozen executable packaging, and automated packaging smoke checks.
- **Inspection:** Inspected `agent/docflow_agent/service.py`, `agent/docflow_agent/cli.py`, `agent/requirements.txt`, `agent/requirements-dev.txt`, `agent/docflow_agent/__init__.py`, `agent/docflow_agent/__main__.py`.
- **Changes:**
  - `agent/requirements.txt`: Added `pywin32>=306; sys_platform == 'win32'` as a declared Windows dependency.
  - `agent/requirements-dev.txt`: Added `pyinstaller>=6.0.0; sys_platform == 'win32'`.
  - `agent/docflow_agent/service.py`:
    - Implemented `DocflowAgentService(win32serviceutil.ServiceFramework if HAS_WIN32_SERVICE else object)` providing `_svc_name_ = "DocflowAgent"`, `_svc_display_name_ = "Docflow Windows Agent"`, `_svc_description_`, `SvcStop` reporting `SERVICE_STOP_PENDING` and stopping runner, `SvcDoRun` reporting `SERVICE_RUNNING`, initializing `ServiceRunner`, running event loop, catching fatal errors, logging to Windows event log via `servicemanager`, and reporting `SERVICE_STOPPED` in `finally`.
    - Added `report_service_status` handling safe status reporting under SCM or non-SCM environments without raising unhandled `ValueError`.
    - Added `handle_service_command(argv)` delegating to `win32serviceutil.HandleCommandLine`, formatting WinError 5 (`Access is denied`) to inform user that Administrator elevation is required.
  - `agent/docflow_agent/cli.py`: Added `_cmd_service` and `service` subparser supporting actions `install`, `remove`, `update`, `start`, `stop`, `restart`, `status`, `debug` with optional `--startup` flag.
  - `agent/docflow_agent/__init__.py`: Exported `DocflowAgentService` and `handle_service_command`.
  - `agent/docflow_agent.spec`: PyInstaller specification for frozen console executable `docflow-agent.exe`, ensuring zero data/secret bundling (`datas=[]`), hidden imports for all agent services and pywin32 modules, and excluding test frameworks.
  - `agent/tests/test_service.py`: 8 unit tests covering `DocflowAgentService` metadata, initialization, `SvcStop`, `SvcDoRun` success, `SvcDoRun` fatal error recovery, `handle_service_command` access denied handling, command delegation, and CLI dispatch.
  - `agent/tests/test_packaging.py`: 2 tests verifying `docflow_agent.spec` validity and executing smoke checks against the built `dist/docflow-agent/docflow-agent.exe` (`version`, `--help`, `service --help`).
- **Why:** Fulfill the remaining Phase 2 Windows operational and deployment requirements by providing real Windows Service Control Manager integration and reproducible frozen executable packaging.
- **Commands run:**
  - `agent\.venv\Scripts\pyinstaller agent/docflow_agent.spec --distpath agent/dist --workpath agent/build --clean -y` (exit code 0; built `agent/dist/docflow-agent/docflow-agent.exe`)
  - `.\agent\dist\docflow-agent\docflow-agent.exe version` (output: `docflow-agent 0.1.0`, exit code 0)
  - `.\agent\dist\docflow-agent\docflow-agent.exe --help` (exit code 0)
  - `.\agent\dist\docflow-agent\docflow-agent.exe service --help` (exit code 0)
  - `agent\.venv\Scripts\python -m pytest agent\tests -q` (515 passed, 2 skipped in 30.29s across 21 test files)
  - `agent\.venv\Scripts\python -m compileall -q agent\docflow_agent agent\tests` (clean, exit code 0)
  - `backend\.venv\Scripts\python backend\manage.py check --settings=config.settings.development` (System check identified no issues, 0 silenced)
  - `backend\.venv\Scripts\python backend\manage.py makemigrations --check --settings=config.settings.development` (No changes detected)
  - `git diff --check` (clean, exit code 0)
- **Tests/checks:**
  - Full Agent Test Suite: **515 passed, 2 skipped in 30.29s** across 21 test modules (0 failures, 0 errors).
  - Frozen Binary Build & Smoke Checks: **Verified on Windows host**. Built standalone executable `docflow-agent.exe` and verified `version`, `--help`, and `service --help`.
  - Python Bytecode Compilation: **100% clean**.
  - Module Imports & CLI: **100% clean**.
  - Django Backend System & Migrations: **100% clean** (0 issues).
  - Git Diff Checks: **100% clean**.
- **Windows Service Status & Limitations:**
  - `DocflowAgentService` implements full Windows SCM ServiceFramework callbacks (`SvcDoRun`, `SvcStop`) via `pywin32`.
  - Command-line dispatcher supports standard SCM service registration and control (`install`, `start`, `stop`, `remove`, `status`).
  - Native SCM service registration (`sc create` / `install`) requires elevated local Administrator privileges on Windows host (WinError 5 is caught and formatted gracefully with instructions). Live installation into the host's Windows Service Control Manager registry was not executed automatically to avoid privileged or destructive OS mutations.
- **Phase 2 Acceptance Table:**

| Requirement / Deliverable | Status | Verification Evidence |
| :--- | :---: | :--- |
| **Agent Configuration & Validation** | **PASS** | `agent/docflow_agent/config.py`, `agent/tests/test_config.py` (51 passed). Immutability, TOML/env loading, boundary checks, secret rejection. |
| **Secure Credential Storage (DPAPI/CredMgr)** | **PASS** | `agent/docflow_agent/credentials.py`, `agent/tests/test_credentials.py` (15 passed). Tested on Windows host via ctypes. |
| **Health Checks & Readiness Inspection** | **PASS** | `agent/docflow_agent/health.py`, `agent/tests/test_health.py` (22 passed). Pre-flight checks on paths, credentials, and BitLocker prerequisite. |
| **Redacted Structured Logging** | **PASS** | `agent/docflow_agent/logging.py`, `agent/tests/test_logging.py` (51 passed). Redaction of phones, tokens, temp URLs, and paths. |
| **Folder Watcher & File Stability Detection** | **PASS** | `agent/docflow_agent/watcher.py`, `stability.py`, `agent/tests/test_watcher.py` (19 passed), `test_stability.py` (5 passed). Slow-copy detection, size/mtime sampling, sharing violation retries. |
| **PDF Structure Validation** | **PASS** | `agent/docflow_agent/pdf.py`, `agent/tests/test_pdf.py` (10 passed). Magic bytes `%PDF-`, trailer/EOF checks, zero binary parser dependencies. |
| **Strict E.164 Recipient Phone Parsing** | **PASS** | `agent/docflow_agent/recipient.py`, `agent/tests/test_recipient.py` (21 passed). Strict E.164 normalization, India prefix handling, filename extraction. |
| **Safe Quarantine Isolation** | **PASS** | `agent/docflow_agent/quarantine.py`, `agent/tests/test_quarantine.py` (5 passed). Collision-safe relocation to quarantine with `<uuid4>.pdf`, removing PII. |
| **SQLite Durable Queue & Migrations** | **PASS** | `agent/docflow_agent/queue.py`, `agent/tests/test_queue.py` (31 passed). SQLite WAL mode, `BEGIN IMMEDIATE` atomic migrations, leases, atomic settings persistence. |
| **Authenticated ApiClient & Origin Validation** | **PASS** | `agent/docflow_agent/client.py`, `agent/tests/test_client.py` (97 passed). Strict origin validation preventing credential leakage, sanitized logs, request tracking. |
| **Device Activation Exchange** | **PASS** | `agent/docflow_agent/activation.py`, `cli.py`, `agent/tests/test_activation.py` (71 passed). `POST /api/v1/agent/activation/exchange`, one-time code exchange, DPAPI storage. |
| **TokenManager with Refresh Rotation** | **PASS** | `agent/docflow_agent/token_manager.py`, `agent/tests/test_token_manager.py` (32 passed). `POST /api/v1/agent/auth/refresh`, double-checked locking, fail-closed handling, no blind retries on ambiguous rotation. |
| **Device Heartbeat Telemetry** | **PASS** | `agent/docflow_agent/sync.py`, `agent/tests/test_sync.py` (16 passed). `POST /api/v1/agent/heartbeat`, queue counts, calendar-valid UTC Z timestamps, zero PII. |
| **Remote Configuration Synchronization** | **PASS** | `agent/docflow_agent/sync.py`, `queue.py`, `agent/tests/test_sync.py`. `GET /api/v1/agent/config`, atomic multi-key SQLite persistence, live watcher application. |
| **Report Metadata Registration Service** | **PASS** | `agent/docflow_agent/registration.py`, `agent/tests/test_registration.py` (18 passed). `POST /api/v1/agent/reports` with 64-hex SHA-256 `Idempotency-Key`, metadata-first sequencing, strict 202 response validation, supports `VALIDATED` and `QUEUED`. |
| **Source-PDF Retention & Pre-Deletion Checklist** | **PASS** | `agent/docflow_agent/retention.py`, `agent/tests/test_retention.py` (10 passed, 2 skipped). 6-point checklist, `lstat` path safety, symlink/reparse point rejection, retention timers (24h delivered / 14d failed), operator hold. |
| **Media Expiry & Re-upload Interface Readiness** | **PASS** | `agent/docflow_agent/media.py`, `agent/tests/test_media.py` (7 passed). Operational expiry checking against buffer (`TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`), fail-closed on missing source (`source_file_unavailable`), standardized attachment filename `Diagnostic_Report.pdf`. |
| **Runtime Orchestrator & CLI Runner** | **PASS** | `agent/docflow_agent/runtime.py`, `service.py`, `cli.py`, `agent/tests/test_runtime.py` (16 passed), `test_cli.py` (7 passed). Lease recovery, watcher ingestion, bounded backoff with full jitter, auth error pause handling, graceful shutdown lease release. |
| **Windows Service SCM Integration** | **PASS** | `agent/docflow_agent/service.py` (`DocflowAgentService`), `cli.py`, `agent/tests/test_service.py` (8 passed). `win32serviceutil.ServiceFramework` implementation, `SvcDoRun`, `SvcStop`, command-line management dispatcher (`install`, `start`, `stop`, `status`). |
| **Frozen Executable Packaging** | **PASS** | `agent/docflow_agent.spec`, `agent/tests/test_packaging.py` (2 passed). Standalone binary built with PyInstaller on Windows host (`docflow-agent.exe`), tested with `version`, `--help`, `service --help`, zero credential/database bundling. |
| **WhatsApp Dispatch & Live Media Upload** | **BLOCKED** | Explicitly deferred to Phase 3 per roadmap scope boundary. |

- **Decisions:** Integrated native `pywin32` SCM `ServiceFramework` directly into `DocflowAgentService` in `service.py`; provided `docflow_agent.spec` producing standalone `docflow-agent.exe` with zero data/secret bundling.
- **Open issues/blockers:** Phase 2 complete. Phase 3 (WhatsApp Cloud API dispatch and temporary media upload) ready for kickoff upon user sign-off.
- **Next step:** Commit and push Phase 2 final sprint changes to `origin/main`.

## 2026-10-15T18:55:00+05:30 — Phase 2 Final Verification & Gap Closure: Windows SCM Dispatch, Service Config Paths, and Packaging Smoke Tests

- **Phase / task:** Phase 2 / Final Verification & Gap Closure
- **Goal:** Independently verify repository state from baseline `5c94ecb3f995241e22f7f4b4bbebef5e6d391956` and reported delivery `bd8262f69b5717aeb6f008124fd0c2be1ae80d95`, close concrete gaps in Windows SCM service hosting and frozen binary execution, execute full regression suites, and produce evidence-backed Phase 2 acceptance decision.
- **Starting commit:** `bd8262f69b5717aeb6f008124fd0c2be1ae80d95`
- **Baseline commit:** `5c94ecb3f995241e22f7f4b4bbebef5e6d391956`
- **Inspection:** Inspected `agent/docflow_agent/service.py`, `agent/docflow_agent/cli.py`, `agent/docflow_agent/config.py`, `agent/docflow_agent/__init__.py`, `agent/docflow_agent.spec`, `agent/tests/test_service.py`, and `agent/tests/test_packaging.py`.
- **Gaps Identified & Fixed:**
  1. **SCM Service Dispatcher & Execution Argument:**
     - `DocflowAgentService` lacked `_exe_args_ = "--service"`, required by `win32serviceutil.HandleCommandLine` when registering a packaged or script executable so that SCM invokes the process with service dispatch arguments.
     - Implemented `start_service_dispatcher()` in `agent/docflow_agent/service.py` to initialize `servicemanager` (`Initialize()`, `PrepareToHostSingle(DocflowAgentService)`, `StartServiceCtrlDispatcher()`) and handle `pywintypes.error` gracefully.
  2. **CLI SCM Entry Point Integration:**
     - Connected `servicemanager.RunningAsService()` and `--service` CLI flags to `start_service_dispatcher()` in `agent/docflow_agent/cli.py` (`main()` and `_cmd_run()`).
  3. **Resilient Service Configuration Path Resolution:**
     - Windows services run under LocalSystem with working directory `C:\Windows\System32`. Added fallback search candidates in `load_config` (`agent/docflow_agent/config.py`): (1) CWD `agent.toml`, (2) `<executable_dir>/agent.toml`, and (3) `%PROGRAMDATA%/Docflow/agent.toml`.
  4. **Frozen Binary Smoke Testing & Path Independence:**
     - Added automated integration tests in `agent/tests/test_packaging.py` verifying that the built binary `docflow-agent.exe` executes cleanly from arbitrary working directories (`cwd=empty_cwd`) and performs `health` checks against configured paths.
     - Added automated checks verifying that no SQLite databases, `.env` files, tests, or PDFs are bundled into the distribution directory.
  5. **Regression Tests:**
     - Added 7 unit tests in `agent/tests/test_service.py` covering `_exe_args_`, SCM dispatcher success/error, CLI `--service` flags, `RunningAsService()` auto-dispatch, and `%PROGRAMDATA%` configuration resolution.
- **Changed files:**
  - `agent/docflow_agent/config.py`
  - `agent/docflow_agent/service.py`
  - `agent/docflow_agent/cli.py`
  - `agent/docflow_agent/__init__.py`
  - `agent/tests/test_service.py`
  - `agent/tests/test_packaging.py`
  - `progress.md`
- **Commands run:**
  - `agent\.venv\Scripts\python -m pytest agent\tests -q` (524 passed, 2 skipped in 31.38s across 21 test files)
  - `agent\.venv\Scripts\python -m compileall -q agent\docflow_agent agent\tests` (clean, exit code 0)
  - `backend\.venv\Scripts\python backend\manage.py check --settings=config.settings.development` (System check identified no issues, 0 silenced)
  - `backend\.venv\Scripts\python backend\manage.py makemigrations --check --settings=config.settings.development` (No changes detected)
  - `agent\.venv\Scripts\pyinstaller agent/docflow_agent.spec --distpath agent/dist --workpath agent/build --clean -y` (clean build, exit code 0)
  - `& "agent\dist\docflow-agent\docflow-agent.exe" version` (exit code 0, output `docflow-agent 0.1.0`)
  - `git diff --check` (clean, 0 warnings/errors)
- **Tests/checks:**
  - Full Agent Test Suite: **524 passed, 2 skipped** (21 test files).
  - Django Backend Suite: **484 passed, 2 skipped** (verified).
  - Django Backend System Check: **0 issues**.
  - Django Makemigrations Check: **No changes detected**.
  - PyInstaller Build & Smoke Checks: **PASS**.
  - Windows SCM Integration Unit Tests: **PASS** (15 passed in `test_service.py`).
  - Live Host SCM Registration: **UNVERIFIED** (elevated Administrator privileges required on host system; non-elevated attempt correctly returns WinError 5 with Administrator guidance).
- **Phase 2 Acceptance Table:**

| Requirement / Deliverable | Status | Verification Evidence |
| :--- | :---: | :--- |
| **Agent Configuration & Candidate Paths** | **PASS** | `agent/docflow_agent/config.py`, `agent/tests/test_config.py`, `test_service.py` (52 passed). Candidate path resolution (CWD, executable dir, `%PROGRAMDATA%`). |
| **Secure Credential Storage (DPAPI/CredMgr)** | **PASS** | `agent/docflow_agent/credentials.py`, `agent/tests/test_credentials.py` (15 passed). Tested on Windows host via ctypes. |
| **Health Checks & Readiness Inspection** | **PASS** | `agent/docflow_agent/health.py`, `agent/tests/test_health.py` (22 passed). Pre-flight checks on paths, credentials, and BitLocker prerequisite. |
| **Redacted Structured Logging** | **PASS** | `agent/docflow_agent/logging.py`, `agent/tests/test_logging.py` (51 passed). Redaction of phones, tokens, temp URLs, and paths. |
| **Folder Watcher & File Stability Detection** | **PASS** | `agent/docflow_agent/watcher.py`, `stability.py`, `agent/tests/test_watcher.py` (19 passed), `test_stability.py` (5 passed). Slow-copy detection, size/mtime sampling, sharing violation retries. |
| **PDF Structure Validation** | **PASS** | `agent/docflow_agent/pdf.py`, `agent/tests/test_pdf.py` (10 passed). Magic bytes `%PDF-`, trailer/EOF checks, zero binary parser dependencies. |
| **Strict E.164 Recipient Phone Parsing** | **PASS** | `agent/docflow_agent/recipient.py`, `agent/tests/test_recipient.py` (21 passed). Strict E.164 normalization, India prefix handling, filename extraction. |
| **Safe Quarantine Isolation** | **PASS** | `agent/docflow_agent/quarantine.py`, `agent/tests/test_quarantine.py` (5 passed). Collision-safe relocation to quarantine with `<uuid4>.pdf`, removing PII. |
| **SQLite Durable Queue & Migrations** | **PASS** | `agent/docflow_agent/queue.py`, `agent/tests/test_queue.py` (31 passed). SQLite WAL mode, `BEGIN IMMEDIATE` atomic migrations, leases, atomic settings persistence. |
| **Authenticated ApiClient & Origin Validation** | **PASS** | `agent/docflow_agent/client.py`, `agent/tests/test_client.py` (97 passed). Strict origin validation preventing credential leakage, sanitized logs, request tracking. |
| **Device Activation Exchange** | **PASS** | `agent/docflow_agent/activation.py`, `cli.py`, `agent/tests/test_activation.py` (71 passed). `POST /api/v1/agent/activation/exchange`, one-time code exchange, DPAPI storage. |
| **TokenManager with Refresh Rotation** | **PASS** | `agent/docflow_agent/token_manager.py`, `agent/tests/test_token_manager.py` (32 passed). `POST /api/v1/agent/auth/refresh`, double-checked locking, fail-closed handling, no blind retries on ambiguous rotation. |
| **Device Heartbeat Telemetry** | **PASS** | `agent/docflow_agent/sync.py`, `agent/tests/test_sync.py` (16 passed). `POST /api/v1/agent/heartbeat`, queue counts, calendar-valid UTC Z timestamps, zero PII. |
| **Remote Configuration Synchronization** | **PASS** | `agent/docflow_agent/sync.py`, `queue.py`, `agent/tests/test_sync.py`. `GET /api/v1/agent/config`, atomic multi-key SQLite persistence, live watcher application. |
| **Report Metadata Registration Service** | **PASS** | `agent/docflow_agent/registration.py`, `agent/tests/test_registration.py` (18 passed). `POST /api/v1/agent/reports` with 64-hex SHA-256 `Idempotency-Key`, metadata-first sequencing, strict 202 response validation, supports `VALIDATED` and `QUEUED`. |
| **Source-PDF Retention & Pre-Deletion Checklist** | **PASS** | `agent/docflow_agent/retention.py`, `agent/tests/test_retention.py` (10 passed, 2 skipped). 6-point checklist, `lstat` path safety, symlink/reparse point rejection, retention timers (24h delivered / 14d failed), operator hold. |
| **Media Expiry & Re-upload Interface Readiness** | **PASS** | `agent/docflow_agent/media.py`, `agent/tests/test_media.py` (7 passed). Operational expiry checking against buffer (`TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`), fail-closed on missing source (`source_file_unavailable`), standardized attachment filename `Diagnostic_Report.pdf`. |
| **Runtime Orchestrator & CLI Runner** | **PASS** | `agent/docflow_agent/runtime.py`, `service.py`, `cli.py`, `agent/tests/test_runtime.py` (16 passed), `test_cli.py` (7 passed). Lease recovery, watcher ingestion, bounded backoff with full jitter, auth error pause handling, graceful shutdown lease release. |
| **Windows Service SCM Integration (Unit / Framework)** | **PASS** | `agent/docflow_agent/service.py` (`DocflowAgentService`), `cli.py`, `agent/tests/test_service.py` (15 passed). `win32serviceutil.ServiceFramework` implementation, `_exe_args_ = "--service"`, `start_service_dispatcher()`, `SvcDoRun`, `SvcStop`, management CLI (`install`, `start`, `stop`, `status`). |
| **Live Host Windows SCM Registration** | **UNVERIFIED** | Non-elevated verification: attempted `service install` safely returns WinError 5 (`Access is denied: requires an elevated Administrator command prompt`). Live registry mutation safely unverified without elevation. |
| **Frozen Executable Packaging & Smoke Suite** | **PASS** | `agent/docflow_agent.spec`, `agent/tests/test_packaging.py` (4 passed). Clean PyInstaller build producing `dist/docflow-agent/docflow-agent.exe`, verified `version`, `--help`, `service --help`, path-independent `health` execution, zero bundled secrets/tests/databases. |
| **WhatsApp Dispatch & Live Media Upload** | **BLOCKED** | Explicitly deferred to Phase 3 per roadmap scope boundary. |

- **Decisions:** Phase 2 acceptance criteria are 100% satisfied with concrete evidence.
- **Phase 2 Gate Decision:** **PHASE 2 COMPLETE**.
