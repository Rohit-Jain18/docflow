# Backend Folder Rules

Read root `CLAUDE.md` and `docs/ARCHITECTURE.md`, `DATA_MODEL.md`, `API_CONTRACTS.md`, `RULES.md`, `SECURITY.md`, `DELIVERY_STATE_MACHINE.md`, `WHATSAPP_ADAPTER.md`, `ENVIRONMENT.md`, `TESTING.md`, `OPEN_QUESTIONS.md` before editing.

- Django + DRF. Choose custom user model before the first migration.
- Development uses Django-default SQLite. Production uses PostgreSQL from environment settings and fails closed for unsafe/missing config.
- Scope every queryset/object operation to authenticated membership/device. Never fetch unscoped then trust frontend. Test cross-tenant access for every endpoint/action.
- Derive organization/branch from membership or device. Do not trust body `organization_id`, `branch_id`, `whatsapp_account_id` or `phone_number_id` as authorization/routing.
- Use strict request validation for security-sensitive schemas; reject unknown routing/secret fields and avoid mass assignment.
- Use transactions for activation redemption, assignment, idempotency and report/outbox creation.
- Persist report/attempt/outbox state before external send. Redis/Celery is optional and not the sole source of truth; implement crash/reclaim behavior.
- Django never receives/proxies/stores PDF bytes. Report API takes metadata and validated reference only; backend does not fetch arbitrary user URLs.
- Keep WhatsApp logic behind adapter. Never invent upload URLs, credential provisioning, webhook signature contracts or reconciliation endpoints. Unknown behavior remains disabled and documented.
- Global credentials (`WA_PLATFORM_DEVELOPER_TOKEN`) backend-only; account tokens stay platform-managed unless approved contract says otherwise. Development verification override is strictly development-only, restricted to allowlisted test accounts, and rejected in production. No secrets/raw provider bodies in logs/responses.
- API acceptance means `accepted`, not `delivered`. API acceptance alone does not permit local source PDF deletion; source is retained until delivery confirmation (`delivered`/`read`) or operator resolution. Ambiguous send timeout means `reconciliation_required`.
- Test tenant isolation, redaction, timeout behavior, callback dedupe, idempotency races and state transitions.
- Append factual entries to root `progress.md`.
