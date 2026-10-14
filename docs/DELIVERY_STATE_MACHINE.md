# Delivery State Machine

Statuses are evidence-backed, not guesses. Persist every transition and its source. Report aggregate status and individual `DeliveryAttempt` status must not erase attempt history.

## 1. Status meanings

- `queued`: report metadata is registered; media preparation/reference attachment is pending. No provider submission or send outbox is ready yet. The backend checks that an active, verified branch assignment exists at registration (or authorized development test verification override is active) and rechecks it before attaching the media reference; if it changes meanwhile, dispatch is blocked until the issue is resolved.
- `uploaded`: a usable media reference/provider media ID with a validated `expires_at` exists and the initial `DeliveryAttempt` plus dispatch-outbox item have been persisted transactionally. With tmpfiles this means a direct URL was obtained with an explicit expiration deadline, not that WhatsApp accepted a send. Before dispatch begins, the media reference's validity and TTL must be checked; if expired or nearing expiry, the reference must be renewed via re-upload from the local retained source PDF before an external send attempt is made. If the retained source PDF is missing or corrupted, the report transitions to `failed` with code `source_file_unavailable`.
- `accepted`: send API acknowledged the request and returned acceptance evidence/message ID. Not proof of sent/delivered/read. Provider API acceptance alone MUST NOT permit deletion of the local source PDF; the source must be retained until delivery confirmation (`delivered`/`read`) or final operator resolution.
- `sent`: trusted provider/platform event confirms sent.
- `delivered`: trusted provider/platform event confirms delivery to recipient's WhatsApp client.
- `read`: trusted provider/platform event confirms read, if that status is available.
- `failed`: definitive failure is known or retry policy exhausted and operator action is needed. Never use this for an ambiguous send timeout.
- `quarantined`: processing blocked for safety (invalid name/PDF, operator hold, untrusted media); no send until explicit audited release/revalidation.
- `reconciliation_required`: send may have reached provider but result is ambiguous. Blocks automatic resend.

## 2. Allowed transitions

| Current | Next | Evidence/reason |
|---|---|---|
| `queued` | `uploaded` | Media adapter confirms a usable reference; persist the first attempt and dispatch-outbox item in the same transaction. |
| `queued` | `failed` | Definitive non-retryable configuration/system failure is recorded. |
| `queued` | `quarantined` | Safety validation blocks processing. |
| `uploaded` | `accepted` | Valid send success response and provider message ID/equivalent acceptance evidence. |
| `uploaded` | `failed` | Definitive failure, unrecoverable expired media where source PDF is missing (`source_file_unavailable`), or known-not-accepted retry budget exhaustion. |
| `uploaded` | `reconciliation_required` | Send request may have reached provider but response timed out/was lost/unreadable. |
| `uploaded` | `quarantined` | Media reference is invalid/untrusted before send. |
| `accepted` | `sent` | Trusted sent event. |
| `accepted` | `delivered` | Trusted delivered event, even if sent event was missed. |
| `accepted` | `read` | Trusted read event, if intermediate events were missed. |
| `accepted` | `failed` | Trusted failure after acceptance according to provider semantics. Preserve message ID/event. |
| `sent` | `delivered` | Trusted delivered event. |
| `sent` | `read` | Trusted read event if delivered event was not observed. |
| `sent` | `failed` | Only if documented provider status semantics allow this transition. |
| `delivered` | `read` | Trusted read event. |
| `reconciliation_required` | `accepted` | Status lookup/verified callback proves accepted. |
| `reconciliation_required` | `failed` | Reliable evidence proves not accepted/failed, or audited operator resolution under documented policy. |
| `reconciliation_required` | `sent`/`delivered`/`read` | Trusted event/status resolves ambiguity directly. |
| `quarantined` | `queued` | Authorized release after correction/revalidation; audit and new attempt key. |
| `failed` | `queued` | Authorized retry after conditions corrected; new `DeliveryAttempt`, old attempt retained. |

No other transition is allowed unless a provider-specific rule is documented and tested. `read` is terminal for an attempt. Never downgrade `delivered` to `sent` because an older event arrived late.

## 3. Attempt vs report status

Each actual external send has its own `DeliveryAttempt`. The report's visible status summarizes the latest valid attempt and trusted evidence. Resend creates a new attempt and preserves earlier attempts/events. Agent-local states (`discovered`, `waiting_stability`, `validated`, `uploading`, `submitting`, `registered`, `retry_wait`, `archived`) are not provider status evidence.

## 4. Timeout, media expiration, source retention, and reconcile-before-resend

1. **Source retention during in-flight operations:** Retain the original local PDF on the Agent PC throughout all in-flight states: `queued`, `uploading`, `retrying`, awaiting delivery confirmation (`delivered` or `read`), or undergoing reconciliation (`reconciliation_required`). Provider API acceptance alone (`accepted`) MUST NOT permit deletion of the local source PDF.
2. Before contacting the provider, verify that the media reference has not expired and is not nearing expiry (within `TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`, default 300 seconds). The persisted `expires_at` is a local operational estimate, not an upstream provider guarantee; tmpfiles.org may purge files earlier without notice. If expired or nearing expiry before send begins, re-upload the retained local PDF, attach a fresh reference with updated `expires_at`, and only then proceed. If the provider rejects the media URL, cannot fetch the document, or reports early expiry (provider-side fetch failure), preserve the local source PDF and retry/re-upload under backoff policy. If the local file is missing/corrupt, transition to `failed` (`source_file_unavailable`). Never attempt to reconstruct the PDF from a temporary link.
3. Persist the attempt and outbox row before contacting the provider. Set `request_started_at` durably immediately before the external call.
4. Submit using server-selected account, approved template, and standardized patient-facing filename (`Diagnostic_Report.pdf`).
5. Valid success response -> record provider message ID and transition to `accepted`.
6. Clear rejection -> classify based on documented provider error semantics.
7. Timeout/connection loss after possible submission or malformed response that leaves acceptance unknown -> transition to `reconciliation_required`.
8. Query a documented provider lookup/status API or await verified callback if one exists. Exact mechanism is still an open question.
9. If evidence proves acceptance, attach message ID and continue tracking. If reliable evidence proves not accepted, retry under policy with recorded reason.
10. If no reconciliation capability exists, keep blocked for operator resolution. Do not automatically resend and risk a duplicate. Even if the temporary media reference expires while in `reconciliation_required`, do NOT resend until the outcome of the earlier attempt is verified.
11. After worker recovery, an outbox item with no `request_started_at` may be safely reclaimed; if the request may have started and no definitive result was recorded, transition to `reconciliation_required` instead of issuing another call.
12. **Cleanup eligibility and lifecycle:**
    - *Delivered/read reports:* When a report reaches confirmed delivery (`delivered` or `read`), the Agent initiates a configurable retention window (`AGENT_CLEANUP_RETENTION_HOURS`, default 24h). The retention clock starts only after delivery confirmation is recorded (`cleanup_eligible_at = terminal_confirmed_at + AGENT_CLEANUP_RETENTION_HOURS`).
    - *Permanently failed and quarantined reports:* Retained for `AGENT_FAILED_RETENTION_DAYS` (default 14d, configurable 1–90d). The retention clock starts at the precise event when the report enters terminal `failed` or `quarantined`, calculating `cleanup_eligible_at = terminal_confirmed_at + (AGENT_FAILED_RETENTION_DAYS * 86400)`.
    - *Retries cancel cleanup eligibility:* Any retry or re-queueing of a failed or quarantined report invalidates previous cleanup eligibility (`cleanup_eligible_at = NULL`). While in-flight, the source PDF is retained. A new deadline is computed only upon reaching a subsequent confirmed terminal outcome.
    - *Operator hold suspends cleanup:* Placing a report on hold (`operator_hold = 1`) suspends cleanup indefinitely across restarts; releasing the hold recalculates eligibility.
    - *Pre-deletion checklist:* Before deleting the source PDF, verify against SQLite: valid terminal state, no active worker lease, no active retry, no operator hold, no pending reconciliation, and current time >= `cleanup_eligible_at`.
    - *Best-effort deletion:* Deletion is best-effort file deletion, not guaranteed secure erasure, due to SSD wear-leveling, journaling (NTFS), copy-on-write filesystems, volume snapshots, and backups. Windows Agent storage should use full-disk encryption (BitLocker) with protected keys.

## 5. Events and trust

- Authenticate/signature-check callback before processing; this contract is not yet confirmed.
- Deduplicate by provider event ID or documented stable compound key.
- Keep provider event timestamp separate from received timestamp.
- Callback may not select tenant/account or provide arbitrary report routing.
- Unknown statuses do not mutate report state. Raw provider payloads are not stored by default; retain allowlisted redacted summary only.

## 6. UI labels

- `queued`: “Queued”
- `uploaded`: “Document prepared” (not “sent”)
- `accepted`: “Accepted by WhatsApp platform”
- `sent`: “Sent”
- `delivered`: “Delivered”
- `read`: “Read”
- `failed`: “Failed” plus safe actionable reason
- `quarantined`: “Needs review”
- `reconciliation_required`: “Checking send status — do not resend yet”

The dashboard must never show delivered on the basis of an API message ID alone.
