from pathlib import Path
import re, sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path(__file__).resolve().parents[1]
issues=[]
passed=[]
required = [
'CLAUDE.md','README.md','progress.md','.env.example','.gitignore','scripts/validate_pack.py','docs/PACK_VALIDATION.md',
'agent/CLAUDE.md','backend/CLAUDE.md','dashboard/CLAUDE.md','infrastructure/README.md',
'.claude/agents/security-reviewer.md','.claude/agents/tenant-isolation-auditor.md',
'.claude/commands/start-phase.md','.claude/commands/review.md','.claude/commands/update-progress.md',
'docs/INDEX.md','docs/ARCHITECTURE.md','docs/ROADMAP.md','docs/RULES.md','docs/DATA_MODEL.md',
'docs/API_CONTRACTS.md','docs/AGENT_SPEC.md','docs/DELIVERY_STATE_MACHINE.md','docs/WHATSAPP_ADAPTER.md',
'docs/SECURITY.md','docs/DASHBOARD_SPEC.md','docs/TESTING.md','docs/ENVIRONMENT.md','docs/DECISIONS.md',
'docs/OPEN_QUESTIONS.md']
for rel in required:
    if (ROOT/rel).is_file() and (ROOT/rel).stat().st_size>0: passed.append(f'required file exists and non-empty: {rel}')
    else: issues.append(f'missing/empty required file: {rel}')
allmd=sorted(ROOT.rglob('*.md'))
for p in allmd:
    try: txt=p.read_text(encoding='utf-8')
    except Exception as e: issues.append(f'UTF-8 read failed: {p.relative_to(ROOT)}: {e}'); continue
    if not txt.strip(): issues.append(f'empty markdown: {p.relative_to(ROOT)}')
    if txt.count('```') % 2: issues.append(f'unbalanced fenced code block marker count: {p.relative_to(ROOT)}')
    links=re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)',txt)
    for target in links:
        target=target.split('#',1)[0]
        if not target or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith('#'): continue
        if not (p.parent/target).resolve().exists(): issues.append(f'broken relative markdown link in {p.relative_to(ROOT)}: {target}')
passed.append(f'all {len(allmd)} Markdown files decode as UTF-8, non-empty and have balanced fenced code markers')
# exactly seven testable rules
rules=(ROOT/'docs/RULES.md').read_text(encoding='utf-8')
rn=re.findall(r'^## Rule [1-7] —',rules,re.M)
if len(rn)==7 and all(f'## Rule {i} —' in rules for i in range(1,8)): passed.append('RULES.md has exactly seven numbered non-negotiable rules')
else: issues.append(f'expected exactly seven rules, found headings={rn}')
# Roadmap phases
roadmap=(ROOT/'docs/ROADMAP.md').read_text(encoding='utf-8')
if all(re.search(rf'^## Phase {i} —',roadmap,re.M) for i in range(6)): passed.append('ROADMAP.md has Phases 0 through 5')
else: issues.append('ROADMAP.md missing one or more phases 0 through 5')
# Critical phrases/policies
checks = [
('docs/ARCHITECTURE.md','```mermaid','architecture contains Mermaid source'),
('docs/RULES.md','No Agent endpoint accepts `phone_number_id`','server-authoritative sender routing rule is explicit'),
('docs/RULES.md','No Django endpoint accepts/proxies PDF bytes','PDF-bytes-bypass-Django rule is explicit'),
('docs/WHATSAPP_ADAPTER.md','tmpfiles.org','temporary uploader is documented'),
('docs/WHATSAPP_ADAPTER.md','External contracts NOT confirmed','WhatsApp unknowns are separated from confirmed facts'),
('docs/DELIVERY_STATE_MACHINE.md','reconciliation_required','ambiguous delivery reconciliation status exists'),
('docs/ENVIRONMENT.md','SQLite','SQLite dev setting documented'),
('docs/ENVIRONMENT.md','PostgreSQL','PostgreSQL production setting documented'),
('docs/OPEN_QUESTIONS.md','OQ-010','ten numbered open questions exist'),
('CLAUDE.md','Do not implement Phase 1 or later until the user explicitly approves it.','Claude is constrained to Phase 0 by default'),
('docs/AGENT_SPEC.md','Register metadata first.','Agent contract registers metadata before media upload'),
('docs/ARCHITECTURE.md','Agent first submits report metadata only to Django.','Architecture narrative matches metadata-first sequence'),
('docs/API_CONTRACTS.md','DEV_ACCOUNT_VERIFICATION_OVERRIDE','API contracts document development account verification override'),
('docs/SECURITY.md','DEV_ACCOUNT_VERIFICATION_OVERRIDE','Security spec documents fail-closed verification override'),
('docs/DECISIONS.md','D-023','Decision log contains decisions D-001 through D-023'),
('docs/ENVIRONMENT.md','AGENT_CLEANUP_RETENTION_HOURS','Environment spec documents source cleanup retention'),
('docs/ENVIRONMENT.md','TEMP_UPLOAD_EXPECTED_HOST','Environment spec documents expected uploader host'),
('docs/AGENT_SPEC.md','source_file_unavailable','Agent spec documents source_file_unavailable error handling'),
('docs/WHATSAPP_ADAPTER.md','/dl/','WhatsApp adapter specifies direct download /dl/ path'),
('docs/SECURITY.md','source_file_unavailable','Security spec documents source_file_unavailable error handling'),
('docs/AGENT_SPEC.md','best-effort file deletion','Agent spec documents best-effort file deletion'),
('docs/SECURITY.md','BitLocker','Security spec documents full-disk encryption (BitLocker) for Agent storage'),
('docs/AGENT_SPEC.md','operator_hold','Agent spec documents operator hold suspending cleanup'),
('docs/WHATSAPP_ADAPTER.md','operational estimate','WhatsApp adapter documents expiry as local operational estimate'),
('docs/TESTING.md','Failed-retention deadline calculation','Testing requirements document failed-retention deadline calculation'),
('docs/TESTING.md','Provider-side early expiry or media fetch failure','Testing requirements document provider fetch failure test'),
]
for rel, needle, label in checks:
    if needle in (ROOT/rel).read_text(encoding='utf-8'): passed.append(label)
    else: issues.append(f'{rel} missing required content: {needle}')
# state-model consistency
state=(ROOT/'docs/DELIVERY_STATE_MACHINE.md').read_text(encoding='utf-8')
api=(ROOT/'docs/API_CONTRACTS.md').read_text(encoding='utf-8')
data=(ROOT/'docs/DATA_MODEL.md').read_text(encoding='utf-8')
if 'media preparation/reference attachment is pending' in state and 'create the first `DeliveryAttempt` plus its dispatch-outbox item in the same transaction' in api and 'when a valid media reference transitions the report from `queued` to `uploaded`' in data:
    passed.append('queued -> uploaded -> first attempt/outbox is consistent across state machine, API and data model')
else: issues.append('queued/uploaded/attempt/outbox lifecycle inconsistent')
if '## 9. Endpoint inventory' in api and '## 10. Idempotency and status semantics' in api and api.count('### `GET /api/v1/agent/reports/{report_id}`') == 1:
    passed.append('API contract has inventory and separate idempotency section')
else: issues.append('API contract section numbering/inventory incomplete')
# catch previously identified out-of-order API instructions
agent_spec=(ROOT/'docs/AGENT_SPEC.md').read_text(encoding='utf-8')
if 'Persist upload reference and local state, then POST metadata/reference' not in agent_spec and agent_spec.find('Register metadata first.') < agent_spec.find('Upload second.') < agent_spec.find('Attach reference third.'):
    passed.append('Agent spec uses metadata -> upload -> media-reference sequence and has no stale reversed sequence')
else: issues.append('Agent spec contains stale or incorrectly ordered upload/registration instructions')

# Check provider acceptance non-deletion rule
if 'Provider API acceptance' in agent_spec and 'alone MUST NOT permit deletion' in agent_spec:
    passed.append('Agent spec enforces that provider acceptance alone must not delete local source PDF')
else:
    issues.append('Agent spec missing provider acceptance non-deletion rule')

# Check tmpfiles direct download URL vs landing-page URL distinction
wa_adapter = (ROOT/'docs/WHATSAPP_ADAPTER.md').read_text(encoding='utf-8')
if '/dl/' in wa_adapter and 'landing' in wa_adapter.lower():
    passed.append('WhatsApp adapter differentiates direct-download URL from HTML landing-page URL')
else:
    issues.append('WhatsApp adapter missing direct-download vs landing-page distinction')

# Review subagents tool restrictions (must be read-only: Read, Grep, Glob; no Edit or Write)
for agent_file in ['.claude/agents/security-reviewer.md', '.claude/agents/tenant-isolation-auditor.md']:
    agent_text = (ROOT/agent_file).read_text(encoding='utf-8')
    if re.search(r'tools:\s*Read,\s*Grep,\s*Glob', agent_text) and 'Edit' not in agent_text and 'Write' not in agent_text:
        passed.append(f'{agent_file} has read-only tools (Read, Grep, Glob) and forbids Edit/Write')
    else:
        issues.append(f'{agent_file} is not properly restricted to read-only tools')

# Check for obsolete product name 'reportflow' across specifications
rf_matches = []
for p in allmd:
    if p.name in {'progress.md', 'PACK_VALIDATION.md'}:
        continue
    txt = p.read_text(encoding='utf-8', errors='ignore')
    if 'reportflow' in txt.lower():
        rf_matches.append(str(p.relative_to(ROOT)))
if not rf_matches:
    passed.append('no occurrences of obsolete product identifier "reportflow" found in specifications')
else:
    issues.append(f'obsolete "reportflow" identifier found in: {rf_matches}')

# Check that global platform token is standardized on WA_PLATFORM_DEVELOPER_TOKEN (no legacy token names)
waba_matches = []
for p in ROOT.rglob('*'):
    if p.is_file() and p.name not in {'validate_pack.py', 'progress.md', 'PACK_VALIDATION.md'} and p.suffix in {'.md', '.py', '.txt', '.example'}:
        txt = p.read_text(encoding='utf-8', errors='ignore')
        if 'WABA_DEVELOPER_TOKEN' in txt:
            waba_matches.append(str(p.relative_to(ROOT)))
if not waba_matches:
    passed.append('standardized on WA_PLATFORM_DEVELOPER_TOKEN (no obsolete token names found in specifications)')
else:
    issues.append(f'obsolete token name WABA_DEVELOPER_TOKEN found in: {waba_matches}')

# Check that temporary media expires_at is never null in API examples
if 'expires_at: null' not in api and '"expires_at": null' not in api:
    passed.append('no permanent "expires_at: null" in media reference API contracts')
else:
    issues.append('found "expires_at: null" in API contracts')

# Check that file_name is not in POST /api/v1/agent/reports request JSON
if '"file_name":' not in api:
    passed.append('file_name removed from POST /api/v1/agent/reports schema in API contracts')
else:
    issues.append('found "file_name" in API contracts report registration request')

# ensure no credential literal in env examples and no token pattern in pack
for p in ROOT.rglob('*'):
    if p.is_file():
        text=p.read_text(encoding='utf-8',errors='ignore')
        if re.search(r'(?i)waba_dev_[A-Za-z0-9_-]{8,}',text): issues.append(f'possible literal developer token in {p.relative_to(ROOT)}')
        if p.name == '.env.example':
            for line in text.splitlines():
                if re.match(r'(?i)^\s*(?:DJANGO_SECRET_KEY|WA_PLATFORM_DEVELOPER_TOKEN|DATABASE_URL)\s*=\s*[^#\s]',line):
                    issues.append(f'non-placeholder secret/database assignment in .env.example: {line.split("=",1)[0]}')
if not any('possible literal developer token' in x or '.env.example:' in x for x in issues): passed.append('no detected literal developer token or live secret assignment in .env.example')
# The doc pack intentionally must not include app code or dependency manifests
app_artifacts=[p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and p.name in {'manage.py','package.json','pyproject.toml','requirements.txt','Dockerfile'}]
if not app_artifacts: passed.append('no application scaffolding/package manifests generated in planning-only pack')
else: issues.append(f'planning pack unexpectedly includes application scaffolding: {app_artifacts}')
print('DOCFLOW PACK VALIDATION')
print(f'Root: {ROOT}')
print(f'Markdown files: {len(allmd)}')
print(f'Checks passed: {len(passed)}')
for item in passed: print('PASS:',item)
print(f'Issues: {len(issues)}')
for item in issues: print('FAIL:',item)
sys.exit(1 if issues else 0)
