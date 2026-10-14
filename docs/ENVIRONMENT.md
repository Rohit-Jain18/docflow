# Docflow Environment and Local Setup

This documents intended settings, not proof that scaffolding exists. Phase 0 must confirm actual tools and update command details after approval.

## 1. Environments

- **Development:** Django-default SQLite; local dashboard; Agent console mode against a temporary folder; tmpfiles only when explicitly enabled for fictional test data.
- **Test/CI:** SQLite unit tests where useful plus PostgreSQL integration tests before production. Use fake providers/mocks; no live tokens, patients or public uploads in CI.
- **Production:** PostgreSQL, secure secrets, HTTPS, tmpfiles forcibly disabled, only confirmed provider media/credential/status contracts.

## 2. Proposed backend variables

Use only what implementation needs. `.env.example` uses placeholders only; never print the environment.

| Variable | Purpose / rule |
|---|---|
| `DOCFLOW_ENV` | `development`, `test`, `staging`, `production`; required safety mode. |
| `DJANGO_SETTINGS_MODULE` | Environment settings module. |
| `DJANGO_SECRET_KEY` | Required unique production secret from secret storage. |
| `DJANGO_DEBUG` | Must be false in production. |
| `DJANGO_ALLOWED_HOSTS` | Restrictive host allow-list. |
| `DATABASE_URL` | Unset locally means Django-default SQLite; production requires PostgreSQL. |
| `CSRF_TRUSTED_ORIGINS` | Explicit trusted browser origins. |
| `CORS_ALLOWED_ORIGINS` | If needed; prefer same-origin reverse proxy, no wildcard credentials. |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | True in production. |
| `WA_PLATFORM_BASE_URL` | Existing platform base host; never place token in URL. |
| `WA_PLATFORM_API_VERSION` | Current tested route version `v25.0`; change only after compatibility check. |
| `WA_PLATFORM_DEVELOPER_TOKEN` | Global developer token only if wrapper mode is confirmed; backend secret only; never in Agent or frontend. |
| `WHATSAPP_TEMPLATE_NAME` | `lab_report_ready` for V1 diagnostic workflow. |
| `WHATSAPP_TEMPLATE_LANGUAGE` | `en` for tested template. |
| `WHATSAPP_PATIENT_FACING_FILENAME` | Standardized patient-facing document attachment name; default `Diagnostic_Report.pdf`. |
| `TEMP_UPLOAD_MODE` | `disabled` default; `tmpfiles` only in development. |
| `TEMP_UPLOAD_FICTIONAL_DATA_ONLY` | Explicit opt-in required in dev; production must refuse it. |
| `TEMP_UPLOAD_ALLOWED_HOSTS` | Exact host allow-list, never user-controlled per request. |
| `TEMP_UPLOAD_EXPECTED_HOST` | Strict expected host for direct-download URLs; default `tmpfiles.org`. |
| `TEMP_UPLOAD_TTL_SECONDS` | Conservative development TTL for temporary uploader; default `3600` (~60 mins). |
| `TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS` | Safety margin buffer before expiration to trigger re-upload; default `300` (5 minutes). |
| `DEV_ACCOUNT_VERIFICATION_OVERRIDE` | Explicit server setting to enable test-account verification in development only; default `false`. Production fails closed if enabled. |
| `DEV_TEST_ORGANIZATION_ID` | Designates allowlisted test organization for dev verification override; ignored in production. |
| `DEV_TEST_ACCOUNT_ID` | Designates allowlisted test WhatsApp account for dev verification override; ignored in production. |
| `AGENT_CLEANUP_RETENTION_HOURS` | Configurable retention period for delivered/read reports before secure source PDF deletion; default `24` hours. |
| `AGENT_FAILED_RETENTION_DAYS` | Configurable retention period for failed/quarantined reports in quarantine folder before operator dismissal; default `14` days. |
| `REDIS_URL` | Optional Redis only when enabled. |
| `CELERY_BROKER_URL` | Optional; never the sole report/send source of truth. |
| `SECRET_MANAGER_URL` or provider-specific config | Only if an actual secret manager is selected. |
| `FIELD_ENCRYPTION_KEY_REFERENCE` | External key reference for transient media/credentials; key is never stored with ciphertext. |

Keep configuration centralized, typed and environment-aware. Avoid adding every variable by habit.

## 3. SQLite vs PostgreSQL

- Development: rely on Django default SQLite without requiring `DATABASE_URL`; once Django structure exists, local file is normally `backend/db.sqlite3`.
- Production: PostgreSQL from environment configuration (e.g. a chosen `DATABASE_URL` parser or explicit `PG*` values). No database credentials in source.
- Keep migrations portable and test production transaction/concurrency behavior on PostgreSQL; SQLite differs in locking/constraints.
- When `DOCFLOW_ENV=production`, startup must fail if database is SQLite, required settings/secrets are missing, DEBUG is true, development verification override is enabled, or essential security settings are unsafe.
- Agent local SQLite remains separate and is used on every environment for its local job queue.

## 4. Dashboard configuration

Only non-secret public `NEXT_PUBLIC_*` variables are allowed. Prefer same-origin reverse proxy if practical. Never put platform/account tokens, Django secret or encryption keys into frontend env variables/bundles. Do not store reusable auth tokens in browser localStorage.

## 5. Agent configuration

- `DOCFLOW_API_BASE_URL`: Docflow API; HTTPS in production.
- `AGENT_DB_PATH`: local SQLite path with restricted ACL.
- `WATCH_FOLDER`, `ARCHIVE_FOLDER`, `QUARANTINE_FOLDER`: local paths; validate no unsafe recursive overlap.
- `PHONE_DEFAULT_REGION`: `IN` for initial deployment.
- `STABILITY_SAMPLE_SECONDS`: proposed default `2`.
- `STABILITY_REQUIRED_SAMPLES`: proposed default `3`.
- `STABILITY_TIMEOUT_SECONDS`: proposed default `120`.
- `MAX_PDF_SIZE_BYTES`: proposed conservative default `52428800` (50 MiB), pending provider limit confirmation.
- `AGENT_CLEANUP_RETENTION_HOURS`: retention period after delivery confirmation (`delivered`/`read`) before best-effort source PDF deletion; default `24` hours (minimum `1` hour).
- `AGENT_FAILED_RETENTION_DAYS`: quarantine retention period for permanently failed or quarantined reports before operator triage / best-effort cleanup; default `14` days (configurable `1`–`90` days).
- `TEMP_UPLOAD_EXPECTED_HOST`: expected host for direct-download URLs; default `tmpfiles.org`.
- `TEMP_UPLOAD_TTL_SECONDS`: local operational TTL estimate for temporary media; default `3600` seconds (unconfirmed upstream guarantee).
- `TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS`: safety buffer threshold before send triggering re-upload renewal; default `300` seconds.
- `AGENT_LOG_LEVEL`: log verbosity with mandatory redaction.
- Agent host volume storage should have full-disk encryption (such as Windows BitLocker) enabled with protected keys and restrictive ACLs.
- Activation code is only supplied during controlled activation and never persisted. Neither `WA_PLATFORM_DEVELOPER_TOKEN` nor any per-account WhatsApp token belongs in Agent config.

## 6. Local setup after scaffolding

1. Create/select Python virtual environment and install pinned backend dev dependencies.
2. From `backend/`, run `python manage.py check`, then migrations after model review.
3. Start Django with development settings (SQLite).
4. Install dashboard dependencies using the single committed package manager/lockfile and start Next.js.
5. Run Agent tests in console mode with a temporary folder and generated fictional PDF. Do not install service/upload during Phase 0.
6. Keep `.env` untracked; fill local-only test values without production secrets.

Exact commands and versions must be updated in root README after Phase 0/1. Do not claim commands have passed before running them.

## 7. Production preflight

- Validate settings without logging values.
- Confirm PostgreSQL backup/restore.
- Confirm HTTPS, host, CSRF, CORS, cookies and rate limits.
- Confirm tmpfiles is blocked.
- Confirm account credential ownership, media upload and delivery status contracts.
- Run security/tenant tests with production-like config and test accounts.
