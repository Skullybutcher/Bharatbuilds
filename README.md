# **A policy changed. Which procedure steps are wrong now?**

![ci](https://github.com/Skullybutcher/Bharatbuilds/actions/workflows/ci.yml/badge.svg)

> Policies are source code. Procedures are compiled artifacts. Amendments are commits.
> ProcessPatch finds the people or cases that prove a procedure is stale, patches the affected logic, reruns regression tests, and requires human approval of exact artifact hashes before anything changes.

```
Policy change
     ↓
Compile (+ rule review)
     ↓
Witness ("who gets the wrong outcome?")
     ↓
Impact (blast radius from evidence, never estimates)
     ↓
Localized patch
     ↓
Regression tests
     ↓
Certificate → Human approval → New procedure version
```

**Canonical example (synthetic university research grant):** Policy V2 relaxes CGPA
8.0 → 7.5 and makes recommendation required only when CGPA < 8.0. The stale portal
still enforces V1. ProcessPatch returns witness A (CGPA 7.80: expected ELIGIBLE,
portal INELIGIBLE) and witness B (CGPA 8.20: expected rec SKIP, portal REQUIRE),
localizes `NODE-GATE` + `NODE-STEP`, proposes a localized patch, validates 16/16
(witnesses, boundaries, unchanged, ordering, integrity, metamorphic, provenance), quantifies
impact over a 100-case generated cohort, and mints a source-linked certificate.
A second domain (reimbursement: tightened limit, conditional approval, ordering,
deadline) validates 20/20.

## Quickstart

```bash
pip install -e ".[dev]"        # pytest + pyyaml (clean-machine repro)
make app                        # ONE command: full app on http://localhost:8080
python scripts/verify.py        # 178 assertions, no network/LLM/AWS
make verify                     # same
python scripts/verify_bundle.py evidence.json
                                # recompute a governance bundle's seal
                                # yourself, stdlib only, no AWS, no our-code
make benchmark                  # ProcessPatchBench v0.3.0, 31 scenarios
make infra-validate             # SAM/ASL/dashboard checks, no credentials
python scripts/demo.py          # terminal person-first demo
python -m services.api.server 8000   # REST API only (§45 + §57E)
```

## Public judge demo

The deployed demo has a shared reviewer account for evaluation:

- **Username:** `judge@processpatch.demo`
- **Password:** `JudgePass2026!`
- **Permissions:** create and execute builds, review rules, and decide patches.

This account is intentionally limited to the `pp-reviewers` group. It cannot
activate procedure versions or administer Cognito. Do not use this account for
real data or production workloads; it is a public demo credential.

## API highlights

- **Canonical example:** `GET /demo/canonical`
- **Build creation:** `POST /builds` with idempotency support
- **Build artifacts:** `GET /builds/{id}/{diff,witnesses,patch,certificate,impact,guardrails,audit}`
- **Rule review:** `POST /builds/{id}/rules/{rid}/{accept,edit,reject,escalate}`
- **Patch review:** `POST /builds/{id}/patch/{approve,reject,request-revision}`
- **Witness replay:** replay witnesses against the compiled procedure
- **Procedure activation:** `POST /procedures/{v}/activate`, with hash verification
- **Build resumption:** `POST /builds/{id}/resume`, using server-side Step Functions resume; clients never hold task tokens
- **Runtime traces:** `POST /traces` and `GET /builds/{id}/trace-compare` for read-only, real-world evidence comparison; see [`docs/traces.md`](docs/traces.md)
- **Bulk trace ingestion:** `POST /traces/csv`, with all-or-nothing and idempotent CSV ingestion
- **Multi-procedure workspaces:** `POST /procedures`, then build against any registered version via `procedure_version_id`; DAG validation is fail-closed; see [`docs/workspaces.md`](docs/workspaces.md)

### Governed evidence exports

Approved builds can export a SHA-256-sealed evidence pack through:

```http
GET /builds/{id}/governance-bundle
```

The bundle covers canonical bytes, reviews, approvals, guardrails, witnesses, patches, certificates, and audit records.

Exports are refused with `409 Conflict` when no human approval is recorded. An unapproved candidate therefore cannot be presented as a governed artifact.

### Witness nomination

A runtime trace can be nominated as a witness candidate:

```http
POST /builds/{id}/nominate-witness
```

Nomination does not create a witness by assertion. It reruns the verified pipeline behind an honesty gate: the trace must disagree with the stale procedure before it can qualify as evidence.

### Full re-verification

Re-verify an approved build with:

```http
POST /builds/{id}/reverify
```

Re-verification recomputes the entire proof from the accepted rule IR, including:

- Compile key
- Patched workflow
- Patch operations
- Certificate content
- Validation results
- Witnesses
- Exact Gate-2 artifact hashes signed by a human

The endpoint returns a `VERIFIED` or `MISMATCH` verdict with per-check details. Tampered evidence and compiler drift are explicitly identified rather than silently accepted.

### Drift monitoring

After activation, the drift monitor is available at:

```http
GET /drift
```

It replays recent runtime traces against the active procedure graph under the standing policy, reporting the disagreement rate and every drifted dimension.

`trace-compare` is the pre-activation half of the CI loop; `/drift` is the standing post-activation half. Both use the same mismatch definition.

### Workspace isolation

Builds are workspace-scoped. `ws-*` Cognito groups gate list endpoints and every per-build surface, while denials are audited.

Identical compiles remain isolated across workspaces. The local server and Lambda `ApiFn` share the same implementation in `services/api/actions.py`, keeping both surfaces behaviorally identical.
## Layout

`services/` deterministic pipeline + impact/governance/registry/bench/aws_handlers ·
`shared/schemas/` all contracts · `demo/` two domains · `frontend/` 10-tab UI ·
`benchmark/processpatchbench/` 31 heterogeneous cases + manifest ·
`benchmark_runs/` reference runs · `tests/` 8 suites · `infra/` full SAM setup ·
`docs/` 21 notes (incl. auth, traces, workspaces) · `scripts/` verify/demo/benchmark/smoke/infra-validate/judge_demo/verify_bundle.

## Trust

A deterministic parser extracts the bounded rule language into typed candidates
with source spans; a Bedrock model fallback engages only when the parser yields
nothing usable (and is schema-validated + Gate-1 reviewed like everything
else). Deterministic code decides correctness. Humans approve exact hashes,
and are authenticated while doing it: Cognito groups gate reviews (pp-reviewers)
and activation (pp-admins), and verified identities are stamped into the audit
trail (docs/auth.md). Ambiguity → NEEDS_REVIEW, conflict →
COMPILATION BLOCKED. Patches are VALIDATED_WITHIN_TESTED_MODEL, never
"compliance guaranteed".

> Software gets regression tests when code changes. Real-world procedures should get them when rules change.
