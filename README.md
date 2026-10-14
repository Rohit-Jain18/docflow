# Docflow Planning Pack

This is the pre-development source-of-truth pack for **Docflow**. It intentionally contains no application code, package manifests, Dockerfiles, or generated migrations. Use the pack as the project root, review the documents, and let Claude Code complete Phase 0 before implementing the product.

## Confirmed product decisions

- Product name: **Docflow**.
- V1 audience: diagnostic laboratories. Keep core document ingestion and delivery reusable for future invoice/receipt/statement workflows, but do not broaden V1 beyond diagnostic reports.
- Recipient phone number is in the PDF filename, initially `919876543210.pdf`.
- An authorized Docflow administrator configures and verifies WhatsApp account assignments.
- Backend: Django + Django REST Framework.
- Dashboard: Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui.
- Local development database: Django's default SQLite. Production database: PostgreSQL via environment-specific settings.
- Windows Agent: Python, watchdog, local SQLite durable queue, HTTPX, Pydantic, Windows Service integration and PyInstaller packaging.
- The existing WhatsApp platform sends messages and its existing inbox handles replies. Docflow does not build a second inbox.
- Django stores control-plane data and metadata only. PDF bytes must not pass through Django.
- tmpfiles.org is development-only and only for entirely fictional PDFs. Never upload real patient data there.

## How to use this pack

1. Extract the archive so the project root is named `docflow/`.
2. Open the **root folder** in Claude Code, not only `docs/`.
3. Ask Claude Code to read `CLAUDE.md`, `docs/OPEN_QUESTIONS.md`, `docs/ARCHITECTURE.md` and `docs/ROADMAP.md` first.
4. Start with Phase 0 only. Do not ask it to implement the entire product in one prompt.
5. Review the Phase 0 repository inspection report before approving Phase 1.
6. Run `python scripts/validate_pack.py` to check document completeness and selected cross-document consistency. A pass is not application/security testing.
7. Keep `progress.md` append-only. Record each implementation task or cohesive change batch, why it was done, exact commands/tests run, outcomes and blockers.

## Source-of-truth hierarchy

1. `docs/` contains product and engineering specifications. `DECISIONS.md` records accepted choices; `OPEN_QUESTIONS.md` records unconfirmed facts.
2. Root `CLAUDE.md` sets the operating rules for Claude Code.
3. Folder-specific `CLAUDE.md` files provide local conventions for the Agent, backend and dashboard.
4. Code must follow these documents. When implementation exposes a contradiction, stop and explain it; do not silently change a decision.
5. `progress.md` is the chronological activity log, not a replacement for product requirements or decisions.

## Folder naming

The frontend root is `dashboard/` to match the requested `dashboard/CLAUDE.md`. Earlier planning used `web/`; this pack standardizes on `dashboard/`. Do not create both frontend folders.

## Current status

This pack is a specification, not proof that an API, service, webhook, installer or security control exists. Unconfirmed details are explicitly marked in `docs/OPEN_QUESTIONS.md` and `docs/WHATSAPP_ADAPTER.md`.
