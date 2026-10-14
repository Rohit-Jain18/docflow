# Dashboard Folder Rules

Read root `CLAUDE.md`, `docs/DASHBOARD_SPEC.md`, `API_CONTRACTS.md`, `RULES.md`, `SECURITY.md`, `DELIVERY_STATE_MACHINE.md` before editing frontend code.

- Next.js App Router, TypeScript, Tailwind and shadcn/ui. Use one package manager and lockfile.
- Dashboard is not a security boundary. Django authorizes every action.
- Do not implement authorization, sender-routing decisions or delivery transitions only in UI code.
- Never put platform/account tokens, device refresh secrets, encryption keys or secret-manager values in client bundles, public env vars, browser localStorage/sessionStorage or API responses.
- Use server-managed secure session cookies and CSRF according to `API_CONTRACTS.md`; don't invent a parallel token storage scheme.
- No PDF bytes or public media URL in dashboard; don't add PDF preview/download without reviewed product/privacy decision.
- Account assignment is an admin action; backend validates tenant/account ownership and verification. UI values cannot select sender for Agent reports.
- Keep accepted/sent/delivered/read distinct. Disable resend while `reconciliation_required`.
- Redact patient numbers and hide media URLs/provider raw payloads. Error/toast must not echo sensitive values.
- Cover loading/empty/error/permission-denied states, keyboard access, labels, visible focus and non-color-only status cues.
- Tests for role UI/API failures/no token display/misleading statuses; frontend tests do not prove backend security.
- Append factual entries to root `progress.md`.
