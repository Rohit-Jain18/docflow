# Docflow Dashboard Specification

## 1. Principles

Frontend root is `dashboard/`, built with Next.js App Router, TypeScript, Tailwind CSS and shadcn/ui. It is an admin/monitoring surface, not a security boundary. Django authorizes every action. Never put WhatsApp tokens, PDF bytes, public media URLs or authorization/business rules in client code.

## 2. Roles

| Role | Scope / permissions |
|---|---|
| Platform administrator | Manage organizations/platform operations; sensitive actions audited. |
| Organization administrator | Manage own labs, branches, memberships, devices and verified WhatsApp assignments; view own reports; request permitted resend. |
| Branch manager | Manage assigned branch devices/configuration and view branch reports. |
| Operator | View delivery states/errors and permitted operational tasks; no credentials/role management. |
| Viewer | Read-only authorized reports/devices. |
| Auditor | Read-only scoped audit/delivery history; no resend/config changes. |

Backend owns final permission matrix; frontend gating is usability only.

## 3. Pages and behaviors

### Authentication
- Login, logout, session-expired and unauthorized states.
- Secure session cookies and CSRF; no browser localStorage token storage.
- Login errors don't reveal whether a particular email exists.

### Dashboard overview
- Counts by state (`queued`, `accepted`, `sent`, `delivered`, `read`, `failed`, `quarantined`, `reconciliation_required`), recent activity, Agent health/last seen and configuration warnings.
- Counts reflect evidence; no delivered claims from API acceptance alone.
- Empty/loading/error states. API times UTC; display using configured organization/branch timezone.

### Organizations / Labs / Branches
- Platform admin lists/creates/updates organizations. Tenant admin sees only their organization.
- Lab name/type/support phone/status; branch identity/contact/time zone and active WhatsApp account.
- Warn about account-assignment changes; backend audits them and defines when assignment snapshot applies.

### WhatsApp accounts
- List display name, masked phone, `phone_number_id` only for authorized admins, safe provider reference, verification state/time.
- Never display/retrieve access token. If a supported backend-managed credential-entry mechanism is approved later, show one-time success only and do not re-display the secret.
- States: `pending_verification`, `verified`, `disabled`, `error`. Entering an ID alone is not verification. When development test verification override is active on an allowlisted account, display an explicit test-mode indicator/badge; production requires provider-confirmed verification.
- Assignment picker offers only verified accounts belonging to the same org; backend validates independently.

### Devices
- List name, branch, status, Agent version, last seen, queue counts and activation state.
- Create device, issue a one-time activation code and show it exactly once with explicit copy/warning; never log or allow later retrieval.
- Revoke confirmation includes impact and reason code. No token display.
- Alert when Agent is old/offline.

### Reports
- Filters: branch, status, date range, document type; recipient search only if exact and permission-limited. Redact full numbers by default.
- Timeline: report registration, media prepared, provider acceptance, sent/delivered/read callbacks, failure/reconciliation events. Show event source/time where supported.
- Distinguish `accepted` from `sent` and `delivered`.
- `reconciliation_required` message: “Checking send status — do not resend yet”; disable resend until resolved.
- Show normalized safe error, not raw provider response or public media URL.
- Quarantine view exposes reason code and permitted review/release action, never local absolute file path.
- Resend requires role, valid state, confirmation and reason; UI cannot override recipient/account/template.

### Delivery attempts
- Attempt number, provider message ID if safe, normalized state, timings and safe error. No WhatsApp inbox/conversation or inbound replies UI.

### Audit events
- Admin/auditor only; scoped list with actor, action, target ID, time, request ID and allowlisted metadata. Never show credentials or media URLs.

### Settings
- Organization/branch settings, default region (`IN` in V1), folder policy description, stability values and retention options if enabled.
- Show when Agent config will apply; local folder path stays on Agent by default.

## 4. Shared states and UX

Every list/detail supports loading, empty, success, API error, retry, permission denied, not-found and stale states. No optimistic UI for revoke, assignment change or resend until server confirms. Confirmation states exactly what will happen and whether a new message attempt is created.

## 5. Accessibility

Keyboard navigation, visible focus, semantic labels, adequate contrast, explicit text labels (not color-only status) and responsive operational views.

## 6. V1 exclusions

No second inbox, no PDF preview/download from Docflow, no invoice workflows, no AI report interpretation, no arbitrary template composer, no patient portal and no billing enforcement until separately approved. Reusable data abstractions must not silently expand launch scope.
