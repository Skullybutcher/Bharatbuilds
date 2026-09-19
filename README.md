# **A policy changed. Which procedure steps are wrong now?**

![ci](https://github.com/Stakeylock/Bharatbuilds/actions/workflows/ci.yml/badge.svg)

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
localizes `NODE-GATE` + `NODE-STEP`, proposes a localized patch, validates 12/12
(witnesses, boundaries, unchanged, ordering, metamorphic, provenance), quantifies
impact over a 100-case generated cohort, and mints a source-linked certificate.
A second domain (reimbursement: tightened limit, conditional approval, ordering,
deadline) validates 16/16.

## Quickstart

```bash
pip install -e ".[dev]"        # pytest + pyyaml (clean-machine repro)
python scripts/verify.py        # 142 assertions, no network/LLM/AWS
make verify                     # same
make benchmark                  # ProcessPatchBench v0.1.0, 26 scenarios
make infra-validate             # SAM/ASL/dashboard checks, no credentials
python scripts/demo.py          # terminal person-first demo
python -m services.api.server 8000   # REST API (§45 + §57E)
# open frontend/index.html → COMPILE AMENDMENT
```

API highlights: `GET /demo/canonical`, `POST /builds` (idempotent),
`GET /builds/{id}/{diff,witnesses,patch,certificate,impact,guardrails,audit}`,
rule review `POST .../rules/{rid}/{accept,edit,reject,escalate}`,
`POST .../patch/{approve,reject,request-revision}`, witness replay,
`POST /procedures/{v}/activate` (hash-verified), `POST /builds/{id}/resume`
(server-side Step Functions resume — clients never hold task tokens),
benchmark endpoints. The local server and the Lambda `ApiFn` share one
implementation (`services/api/actions.py`) so both surfaces stay identical.

## Layout

`services/` deterministic pipeline + impact/governance/registry/bench/aws_handlers ·
`shared/schemas/` all contracts · `demo/` two domains · `frontend/` 11-tab UI ·
`benchmark/processpatchbench/` 26 heterogeneous cases + manifest ·
`benchmark_runs/` reference run · `tests/` 7 suites · `infra/` full SAM setup ·
`docs/` 12 notes · `scripts/` verify/demo/benchmark/smoke/infra-validate.

## Trust

A deterministic parser extracts the bounded rule language into typed candidates
with source spans; a Bedrock model fallback engages only when the parser yields
nothing usable (and is schema-validated + Gate-1 reviewed like everything
else). Deterministic code decides correctness. Humans approve exact hashes. Ambiguity → NEEDS_REVIEW, conflict →
COMPILATION BLOCKED. Patches are VALIDATED_WITHIN_TESTED_MODEL, never
"compliance guaranteed".

> Software gets regression tests when code changes. Real-world procedures should get them when rules change.
