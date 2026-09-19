# Architecture — ProcessPatch (Ultimate)

Event-driven, serverless, bursty. Policy compilations are intermittent; no always-on compute.

```
Amplify (frontend, auto-built from main; API_URL injected at build)
  → HttpApi → ApiFn (full shared-actions surface + execution starts + resume)
  → S3 SourceBucket (versioned evidence; auto-start DISABLED — API starts
    executions with a complete envelope: key + workspace/procedure/policy ids)
  → Step Functions BuildStateMachine (40 states)
       INGEST → LOAD_BUILD_CONTEXT → HASH_ARTIFACT → SET_BUILD_ID
       → EXTRACT_RULES → VALIDATE_RULE_IR → CHECK_IDEMPOTENT
       → RESOLVE_AUTHORITY → RULE_REVIEW? → WAIT_FOR_RULE_REVIEW (task token)
       → COMPILE_CONSTRAINTS → SEMANTIC_DIFF → FIND_WITNESSES
       → LOCALIZE_PATCH → VALIDATE_PATCH → COMPUTE_IMPACT (final: validated
         patch, final nodes, full regression + provenance)
       → GENERATE_CERTIFICATE → PERSIST_BUILD → WAIT_FOR_PATCH_APPROVAL
       → FETCH_CANDIDATE (read-only; resume already minted it once)
       → WAIT_FOR_ACTIVATION_APPROVAL → ACTIVATE → MARK_ACTIVE → READY
       Lambdas: Extractor / Compiler / Witness / Validator / Impact / Govern
DynamoDB single table (on-demand + PITR): builds, versions, reviews, approvals,
callbacks, audit, executions. ArtifactBucket: certificates, benchmark reports.
CloudWatch: logs, alarms, dashboard.
Bedrock/approved model runtime: extraction fallback ONLY (ExtractorFn tries the
deterministic parser first; `PROCESSPATCH_MODEL_FALLBACK=1` on Lambda).
```

Trust boundary: model proposes typed candidates; deterministic Lambdas decide
correctness. Same Python (`services/`) runs locally (file storage) and on Lambda
(DynamoDB via `services/storage.py` selected by `PROCESSPATCH_STORAGE`).

Witness search is **constraint-guided deterministic search** (literal
boundaries ± ε plus bounded cartesian product over the supported
numeric/date/enum fragment) — an executable approximation of
Expected(x) XOR Actual(x), not an SMT solver. Z3 containerization for the
WitnessFn remains a documented future step, not a current claim.

Why no Neptune: ~20–100 nodes/workflow. DynamoDB/JSON + in-memory traversal is
simpler and cheaper; Neptune only if cross-workflow scale justifies it.

Auth: Cognito UserPool + hosted-UI PKCE, HttpApi JWT authorizer (health/demo/auth-config
public), verified identity stamped by `services/api/authz.py` (docs/auth.md).
Trace ingestion: `POST /traces`, read-only `GET /builds/{id}/trace-compare` (docs/traces.md).
Governance bundle: `GET /builds/{id}/governance-bundle` (sha256-sealed evidence pack over canonical bytes; refused 409 without human approval). Witness nomination: `POST /builds/{id}/nominate-witness` (honesty gate — the trace must disagree with the stale procedure; the verified pipeline disposes, never a witness by assertion). Bulk CSV ingest: `POST /traces/csv` (all-or-nothing, idempotent).
Multi-procedure workspaces: `POST /workspaces`, `POST /procedures` (docs/workspaces.md).
