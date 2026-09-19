# AWS setup (full)

## Prereqs

AWS CLI + SAM CLI + an AWS account. Region default `ap-south-1`
(override via `--region` / `infra/deploy.ps1 -Region`).
The GitHub repo **must be public** for the First Commit submission — and for
Amplify hosting you need a GitHub token in `AMPLIFY_TOKEN` (used once as the
`AmplifyAccessToken` CloudFormation parameter, `NoEcho`; never committed).

## What deploys

`infra/template.yaml` (SAM): 7 Lambdas (Api, Extractor, Compiler, Witness,
Validator, Impact, Govern; Python 3.12, X-Ray tracing), HttpApi (Cognito JWT
authorizer by default; health/canonical/auth-config are public), Cognito
user pool + hosted-UI domain + public PKCE client with pp-admins/pp-reviewers
groups (docs/auth.md), S3 source +
artifact buckets (private, encrypted, versioned; EventBridge notifications),
DynamoDB single-table registry (on-demand + PITR + GSI1 for idempotency),
Step Functions state machine (40 states: ingest, hash, build-id, extract,
validate, idempotency, review gates, compile, diff, witnesses, localize,
patch, validate, impact-after-validation, certificate, persist, approval
wait, fetch-candidate, activation wait, activate, mark-active, plus
terminals; logging + tracing, task-token human
gates), EventBridge S3→SFN rule, CloudWatch alarms + dashboard, Amplify
frontend auto-built from `main`.

IAM is least-privilege: per-function DynamoDB/S3/Bedrock scopes, SFN role
scoped to the 7 function ARNs, EventBridge role scoped to StartExecution.

## GitHub Actions AWS authentication

The `deploy` job in `.github/workflows/ci.yml` uses GitHub's OIDC token; it
does not use long-lived AWS access keys. In IAM, create an identity provider
with:

```text
Provider URL: https://token.actions.githubusercontent.com
Audience: sts.amazonaws.com
```

The role used by the workflow must trust that provider with
`sts:AssumeRoleWithWebIdentity` and restrict the subject to this repository. A
suffix wildcard accommodates GitHub branch and environment subject formats:

```text
repo:Skullybutcher/Bharatbuilds:*
repo:Skullybutcher@*/Bharatbuilds@*:ref:refs/heads/main
```

GitHub repositories using immutable subject claims include numeric owner and repository IDs, so the role must allow both forms for the `main` branch:

The workflow uses the verified role ARN directly so a stale or malformed
repository secret cannot select a different role:

```text
arn:aws:iam::262786914860:role/GitHubActionsProcessPatchDeploy
```

The workflow must retain `id-token: write` and `contents: read` permissions.
It also prints the non-secret repository/ref/event context immediately before
the credential step, which makes any future trust-subject mismatch visible in
the job log.
The Node 20 message from older versions of the credentials action is only a
warning; this repository uses `configure-aws-credentials@v5`.

## Deploy

```bash
# bash
STACK=processpatch-demo REGION=ap-south-1 bash infra/deploy.sh
# powershell
.\infra\deploy.ps1 -Stack processpatch-demo -Region ap-south-1
```

Parameters live in `infra/parameters.json` (EnvName, GitHubRepo, ModelId,
AmplifyBranch) plus the `AmplifyAccessToken` secret passed via
`$AMPLIFY_TOKEN` — `sam deploy --parameter-overrides` takes explicit
`ParameterKey=…,ParameterValue=…` pairs (not `file://…`), which the deploy
scripts expand with stdlib python. Model calls are restricted to extraction (Bedrock InvokeModel
scoped to `ModelId`, default `amazon.nova-micro-v1:0`).

## Validate without credentials

`make infra-validate` parses the template (CFN-aware YAML), checks every
handler file/function, ASL graph integrity (all refs resolve, terminals,
≥6 governance gates, 3 task-token waits), and dashboard widgets.

## Storage

Lambdas set `PROCESSPATCH_STORAGE=dynamodb` (`services/storage.py`); local
runs default to `./data` JSON files. Same interface both sides.
