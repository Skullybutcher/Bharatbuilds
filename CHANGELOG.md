# Changelog

All notable changes to ProcessPatch are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow the project's milestone numbering.

---

## [Unreleased] — T18

### Added
- **Witness coverage endpoint + panel**: `GET /builds/{id}/coverage` (both
  surfaces) — how much of the change's blast radius the verified witnesses
  actually touch. Node coverage joins the localizer's faults (a witness
  covers the nodes its own fault cites); field coverage requires a witness
  case to cite the field. Honest by construction: `covered` means a verified
  witness exercises it — nothing else counts; uncovered blast radius is
  reported, not hidden. Panel on the Impact tab with tone-coded bars.
- **Command palette (Ctrl+K / Cmd+K)**: fuzzy launcher over all 10 tabs plus
  real actions (Compile Amendment, Run Cloud Execution, Toggle theme, Judge
  Mode, Download governance bundle, Compile pasted policy). Full keyboard
  support (↑↓/Enter/Esc), dialog semantics, theme-token styling, header
  command button for discoverability.

## [Unreleased] — T15

### Added
- **Governance bundle export**: `GET /builds/{id}/governance-bundle` (both surfaces)
  — one sha256-sealed JSON: rule reviews, approvals, guardrail evaluation,
  witnesses, patch, validation, certificate, audit trail. Refused (409) for
  builds with no human approval on record. UI: download button on the Approval
  tab.
- **Witness nomination**: `POST /builds/{id}/nominate-witness` (both surfaces) —
  human nominates a runtime trace as a candidate witness; refused (409) unless
  the trace disagrees with the build's stale procedure (same honesty criteria
  as trace-compare); the case is verified through the real pipeline
  (`find_witnesses` + regression validator) and only a genuinely new witness is
  added; audited as `WITNESS_NOMINATED`. UI: "Nominate witness" action on
  disagreeing traces in the Traces tab.
- **CSV bulk trace ingest UI**: paste-CSV card on the Traces tab (backend
  endpoint existed since T7; now reachable).

### Fixed
- Local server `GET /builds/{id}/*` now maps `ValueError → 409` (was: handler
  crash / dropped connection) — parity with the Lambda surface; directly
  affected the governance-bundle refusal path.
- `services/api/server.py` binds strictly (no `SO_REUSEADDR`): a second server
  can no longer silently share an occupied port and steal connections
  ("empty reply" failures on Windows).
- `make app` runner now picks a genuinely free **backend** port (strict probe +
  failover) instead of assuming 8001 — orphaned backends from crashed sessions
  previously wedged the app.
- Runner backend stderr is captured to `.app_backend.log` (gitignored) so
  backend failures are diagnosable from the runner.

## [0.3.1] — 2026-09-19

### Added

- **One-command local app**: `make app` (`scripts/app.py`) serves the UI and
  the full API on one port (http://localhost:8080, `/api` same-origin proxy
  onto the stock `services.api.server` backend). Zero-risk rehearsal path for
  demos — step 0 of `docs/deployment-runbook.md`, default path in
  `docs/demo-script.md`.
- **First-run UI polish**: no-build Overview hero (3-step how-it-works + one
  CTA); sentence-plus-action empty states for Traces, Builds, Workspaces,
  Benchmarks (`make benchmark` + copy button), and Approval. Frontend-only,
  no API or contract changes.
- **Seeded demo state**: `make app` pre-loads the canonical research-grant
  build + one runtime trace through the real API paths (idempotent;
  `--no-seed` skips). The app gets its own data dir (`.app_data/`, override
  with `PROCESSPATCH_DATA`), so first boot has content and dev `data/` stays
  untouched.
- **Bulk trace CSV ingestion**: `POST /traces/csv` — paste a CSV export of
  executed decisions; case columns auto-detected (everything not reserved),
  numeric coercion, `;`-separated `required`. All-or-nothing: every row is
  validated before anything is stored; content-hash idempotent. See
  `docs/traces.md`.
- **App E2E suite**: `tests/journey/test_app.py` spawns the real runner on
  free ports with an isolated data dir and asserts shell, config.js, API
  proxy, seeded state, the CSV flow, and that the backend child is reaped on
  shutdown (Windows Job Object in `scripts/app.py`).

### Changed

- **Frontend redesign**: single-file UI split into `frontend/index.html`
  (shell) + `frontend/styles.css` (design tokens: one accent, 8px grid,
  12–24 type scale) + `frontend/lib/app.js` (all view logic). Stripe-
  dashboard density with a prune pass on decorative badges; all 10 tabs,
  Judge Mode, trust badges, and `esc()` escaping preserved.
- **Docs audit**: `docs/consistency-audit.md` (11 findings); stale counts and
  cross-refs fixed across `docs/` + `README.md`; demo script rewritten around
  the `make app` reality.

### Fixed

- `scripts/smoke.ps1` now asserts the auth-gated routes like the bash smoke
  (auth-config fetch, 401 checks on `/builds` + guardrails).
- Local API server returns proper JSON errors for bad client input
  (`ValueError` → 409, `KeyError` → 404), matching the Lambda surface,
  instead of dropping the connection mid-response.
- `/api` proxy in `scripts/app.py` retries once on connection-refused
  (covers the backend's startup race; all actions are idempotent).

---

## [0.3.0] — 2026-09-19

### Added

- **Cognito authentication**: UserPool + `pp-admins`/`pp-reviewers` groups,
  hosted-UI PKCE login, HttpApi Cognito JWT authorizer (health / demo /
  auth-config routes remain public). `services/api/authz.py` stamps verified
  identity into every gate action — caller-supplied `reviewer`/`role` fields
  are no longer trusted. See `docs/auth.md`.
- **Runtime trace ingestion**: `POST /traces` (validated, idempotent,
  content-hashed `TRC-<hash>` ids); `GET /builds/{id}/trace-compare` (read-only
  replay comparison against both stale and patched graphs). Traces are evidence
  only — disagreement nominates candidate witnesses, never grants witness status
  directly. Traces tab added to the UI. See `docs/traces.md`.
- **Bounded rule language v0.3**: enum membership (`IN` / `NOT_IN`) and numeric
  intervals in the deterministic parser; exclusion-gate patch synthesis;
  witness sampler handles list literals as boundary candidates.
- **Multi-procedure workspaces**: `POST /workspaces`, `POST /procedures`
  (fail-closed `INVALID_WORKFLOW` DAG validation), `POST /builds` accepts
  `procedure_version_id` to compile against any registered version. See
  `docs/workspaces.md`.
- **Judge demo**: `scripts/judge_demo.py` verifies all 6 evaluation beats
  against a live server; `demo/judge_script.md` documents the script.

### Fixed

- Delta classifier no longer cross-pairs thresholds from different fields (e.g.
  a `cgpa` bound vs an `amount` bound). Threshold pairing is now same-field
  only (`services/normalizer/normalizer.py`).

### Changed

- **ProcessPatchBench v0.2.0 → v0.3.0**: 29 → 31 scenarios (20 → 22
  `AUTO_REPAIRED`). Two new cases: `EXC-LIST-001` (list waiver → `IN`
  exception) and `ENUM-EXCL-001` (must-not-be list → `NOT_IN` threshold).
  Frozen reference run: `benchmark_runs/BENCH-v030-REF`.
- `scripts/verify.py`: 176 → 178 assertions.
- pytest suite: 25 → 52 tests (new suites: traces, workspaces, language v0.3
  edge cases).

---

## [0.2.0]

- Cloud-executable architecture: `builds/persist/fetch`, unified Lambda/local
  API, `POST /builds/{id}/resume` (server-side Step Functions task-token
  resume; clients never hold task tokens), real policy input, honest impact
  metrics.
- Harden to review: CI pipeline (credential-free verify + benchmark + infra-
  validate), unified `ApiFn`/local-server implementation sharing
  `services/api/actions.py`, real Gate-1 rule review, hash-bound activation,
  Bedrock fallback (`PROCESSPATCH_MODEL_FALLBACK=1`; deterministic parser is
  the fast path).
- Correctness pass: real DAG execution, exact-candidate activation,
  DynamoDB-safe storage, prohibitions, schemas, UI debugger tab.
- ProcessPatchBench v0.2.0: 29 scenarios, 20 `AUTO_REPAIRED`, 3 `CORRECTLY_NO_OP`,
  4 `CORRECTLY_ESCALATED`, 2 `UNSUPPORTED`. Reference run:
  `benchmark_runs/BENCH-v020-REF`.

---

## [0.1.0]

- Initial release: ProcessPatch Ultimate — impact dashboard, HITL governance
  (three-gate Step Functions state machine), 26-scenario benchmark
  (`BENCH-v010-REF`: 19 `AUTO_REPAIRED`), full AWS SAM setup.
- Core pipeline: NL rules → Rule IR → constraints → witnesses → localized
  patch → regression + impact + certificate → hash-bound human approval →
  new procedure version.
- Supported rule kinds: threshold, obligation, conditional_obligation,
  prohibition, prerequisite/ordering, exception, deadline.
