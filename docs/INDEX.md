# Docflow Documentation Index

Read root `CLAUDE.md` first.

| Document | Authoritative for |
|---|---|
| `ARCHITECTURE.md` | Component boundaries, data/control flows and trust boundaries |
| `ROADMAP.md` | Phases 0–5, deliverables and exit criteria |
| `RULES.md` | Seven testable non-negotiables |
| `DATA_MODEL.md` | Logical entities, fields, relationships and constraints |
| `API_CONTRACTS.md` | Proposed internal endpoints, schemas, auth, errors and idempotency |
| `AGENT_SPEC.md` | Windows Agent behavior, file processing, queue, retries/recovery |
| `DELIVERY_STATE_MACHINE.md` | Report/attempt states, transitions and reconcile-before-resend |
| `WHATSAPP_ADAPTER.md` | Existing wrapper facts, approved template, adapter design and unknowns |
| `SECURITY.md` | Threat model, tenant isolation, secrets, privacy and security tests |
| `DASHBOARD_SPEC.md` | Pages, roles, permissions, UI states and V1 exclusions |
| `TESTING.md` | Test layers, commands to confirm and mandatory cases |
| `ENVIRONMENT.md` | SQLite/production PostgreSQL, variables, setup and safety guards |
| `DECISIONS.md` | Accepted decisions and reasons |
| `OPEN_QUESTIONS.md` | Unconfirmed external contracts and launch blockers |
| `PACK_VALIDATION.md` | Scope/results of the planning-pack validator; not application testing |

`PACK_VALIDATION.md` explains the repeatable pack-only validator (`python scripts/validate_pack.py`).

`progress.md` is the append-only activity log. It records what was done and observed; it is not a requirements document.
