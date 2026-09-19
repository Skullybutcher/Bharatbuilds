# Changelog

All notable changes to ProcessPatch are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow the project's milestone numbering.

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
