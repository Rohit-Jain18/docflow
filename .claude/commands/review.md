---
description: Review current Docflow diff against architecture, rules and security requirements
---

Read root `CLAUDE.md`, `docs/RULES.md`, `docs/SECURITY.md`, `docs/ARCHITECTURE.md`, `docs/OPEN_QUESTIONS.md` and relevant specs. Inspect Git status and the complete diff. Do not modify code during review.

Review architecture/acceptance criteria, tenant isolation, server-side sender mapping, global/account/device secrets, PDF path bypass, idempotency/crash recovery/reconcile-before-resend, status truth, callback authentication/deduplication, tmpfiles guard/privacy, SQLite/PostgreSQL portability and tests actually run.

Use `security-reviewer` and `tenant-isolation-auditor` subagents when available. Resolve conflicting findings explicitly. Output severity-ranked findings with file/line evidence, fixes and tests not run. If no blockers are found, say so only for the reviewed scope, not that the product is universally secure. Never claim tests passed without command results.
