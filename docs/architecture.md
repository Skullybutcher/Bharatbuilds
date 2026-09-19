# Architecture — ProcessPatch (Ultimate)

Event-driven, serverless, bursty. Policy compilations are intermittent; no always-on compute.

```
Amplify (frontend, auto-built from main)
  → HttpApi → ApiFn (proxy + task-token resume callbacks)
  → S3 SourceBucket (presigned uploads; EventBridge notifications)
  → EventBridge rule → Step Functions BuildStateMachine
       INGEST → HASH_ARTIFACT → EXTRACT_RULES → VALIDATE_RULE_IR
       → RESOLVE_AUTHORITY → RULE_REVIEW? → WAIT_FOR_RULE_REVIEW (task token)
       → COMPILE_CONSTRAINTS → SEMANTIC_DIFF → FIND_WITNESSES
       → COMPUTE_IMPACT → LOCALIZE_PATCH → VALIDATE_PATCH
       → GENERATE_CERTIFICATE → WAIT_FOR_PATCH_APPROVAL (task token)
       → CREATE_PROCEDURE_VERSION → WAIT_FOR_ACTIVATION_APPROVAL (task token)
       → ACTIVATE → READY
       Lambdas: Extractor / Compiler / Witness / Validator / Impact / Govern
DynamoDB single table (on-demand + PITR): builds, versions, reviews, approvals, audit.
ArtifactBucket: certificates, benchmark reports. CloudWatch: logs, alarms, dashboard.
Bedrock/approved model runtime: semantic extraction ONLY (ExtractorFn).
```

Trust boundary: model proposes typed candidates; deterministic Lambdas decide
correctness. Same Python (`services/`) runs locally (file storage) and on Lambda
(DynamoDB via `services/storage.py` selected by `PROCESSPATCH_STORAGE`).

Why no Neptune: ~20–100 nodes/workflow. DynamoDB/JSON + in-memory traversal is
simpler and cheaper; Neptune only if cross-workflow scale justifies it.
