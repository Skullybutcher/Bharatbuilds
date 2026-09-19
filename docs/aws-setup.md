# AWS setup (full)

## Prereqs

AWS CLI + SAM CLI + an AWS account. Region default `ap-south-1`
(override via `--region` / `infra/deploy.ps1 -Region`).

## What deploys

`infra/template.yaml` (SAM): 7 Lambdas (Api, Extractor, Compiler, Witness,
Validator, Impact, Govern; Python 3.12, X-Ray tracing), HttpApi, S3 source +
artifact buckets (private, encrypted, versioned; EventBridge notifications),
DynamoDB single-table registry (on-demand + PITR + GSI1 for idempotency),
Step Functions state machine (31 states, logging + tracing, task-token human
gates), EventBridge S3→SFN rule, CloudWatch alarms + dashboard, Amplify
frontend auto-built from `main`.

IAM is least-privilege: per-function DynamoDB/S3/Bedrock scopes, SFN role
scoped to the 7 function ARNs, EventBridge role scoped to StartExecution.

## Deploy

```bash
# bash
STACK=processpatch-demo REGION=ap-south-1 bash infra/deploy.sh
# powershell
.\infra\deploy.ps1 -Stack processpatch-demo -Region ap-south-1
```

Parameters live in `infra/parameters.json` (EnvName, GitHubRepo, ModelId,
AmplifyBranch). Model calls are restricted to extraction (Bedrock InvokeModel
scoped to `ModelId`, default `amazon.nova-micro-v1:0`).

## Validate without credentials

`make infra-validate` parses the template (CFN-aware YAML), checks every
handler file/function, ASL graph integrity (all refs resolve, terminals,
≥6 governance gates, 3 task-token waits), and dashboard widgets.

## Storage

Lambdas set `PROCESSPATCH_STORAGE=dynamodb` (`services/storage.py`); local
runs default to `./data` JSON files. Same interface both sides.
