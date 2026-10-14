# Agent Folder Rules

Read root `CLAUDE.md` and `docs/AGENT_SPEC.md`, `docs/DELIVERY_STATE_MACHINE.md`, `docs/SECURITY.md`, `docs/RULES.md`, `docs/API_CONTRACTS.md`, `docs/TESTING.md` before editing Agent code.

- Use Python; Agent has its own SQLite queue and lifecycle, separate from Django/Next.js.
- Windows is the production target. Watcher events are hints; rescan after startup and recover persisted jobs.
- Wait for stable file size + modification-time samples; validate PDF/filename before upload.
- Parse number from basename locally, normalize to E.164 using configured region, reject ambiguous names. V1 example: `919876543210.pdf`. Original phone-bearing filename is strictly local and never transmitted in API metadata.
- Persist job and deterministic fingerprint before side effects. Version/migrate local SQLite.
- Store refresh credential using Windows Credential Manager or DPAPI; never plaintext `.env`, JSON, code, PyInstaller bundle or logs.
- Never store PDF bytes in SQLite or send them to Django. Provider API acceptance alone (`accepted`) MUST NOT delete local PDF; retain source PDF through all in-flight states (queued, uploading, retrying, awaiting delivery confirmation, reconciliation). Delivered/read reports are retained for configurable window (`AGENT_CLEANUP_RETENTION_HOURS`, default 24h, clock starts upon delivery confirmation) before best-effort file deletion. Failed/quarantined reports retain for `AGENT_FAILED_RETENTION_DAYS` (default 14d, clock starts upon terminal failure/quarantine). Retries cancel cleanup eligibility; operator hold suspends cleanup. Pre-deletion checklist verifies terminal status, no active lease, no active retry, no operator hold, no pending reconciliation, and elapsed retention timer. Host storage should have full-disk encryption (BitLocker) enabled. Persist cleanup state in SQLite across restarts. If source PDF is missing/corrupt, fail closed with `source_file_unavailable`.
- Check media reference expiry before dispatch and re-upload if expired or near expiry buffer. Expiry timestamp is a local operational estimate (~60 min tmpfiles default TTL), not an upstream provider guarantee. On provider-side fetch failure, preserve source PDF and retry/re-upload under backoff policy. For tmpfiles, extract and validate direct-download binary URL (`/dl/`); ordinary HTML landing-page URL is strictly prohibited in WhatsApp payloads. Upload only to approved media destination (`TEMP_UPLOAD_EXPECTED_HOST=tmpfiles.org`). tmpfiles is fictional-data-only and explicit-development-only.
- Never place global developer token (`WA_PLATFORM_DEVELOPER_TOKEN`) or per-account WhatsApp token on Agent. Agent cannot select `phone_number_id` or account.
- Network/registration retries must be idempotent. If a send may already have been accepted, use `reconciliation_required`; do not blindly resend, even if temporary media reference expired.
- Invalid input goes to quarantine. Transient network failure must not delete/misclassify a valid report. Never delete source without verifying terminal confirmation and retention policy.
- Redact phone numbers, filenames/paths, direct URLs, provider payloads and tokens from logs.
- Test duplicate watcher events, copying/locked files, service restart, stale leases, revocation, DB corruption, and failures at network state boundaries.
- Claim Windows Service/PyInstaller behavior tested only after testing on Windows.
- Append factual entries to root `progress.md` after meaningful tasks; never invent test results.
