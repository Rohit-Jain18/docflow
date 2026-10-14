---
description: Start one approved Docflow roadmap phase safely
argument-hint: "<phase-number>"
---

Read root `CLAUDE.md`, `progress.md`, `docs/ROADMAP.md`, `docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md` and phase-specific specs first.

Requested phase: `$ARGUMENTS`

1. Verify the phase exists and all earlier gates are complete and explicitly approved. Otherwise stop and explain.
2. Inspect Git status/repository before modifications. Report uncommitted changes and preserve them.
3. Restate goal, in/out of scope, acceptance criteria and blockers. For a new phase, wait for user approval of the plan before implementation.
4. Implement in small slices; run relevant checks and append factual progress after each meaningful task.
5. Never infer unresolved WhatsApp contracts. Stop at interface boundary and record evidence/next action in `OPEN_QUESTIONS.md`.
6. Report files changed, commands actually run, results, acceptance criteria completed/failed/skipped/unverified, review findings and one next step. Do not advance automatically.
