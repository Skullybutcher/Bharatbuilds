# Deployment runbook

0. Rehearse with zero risk: `make app` — serves the UI + same-origin API on
   http://localhost:8080 (credential-free; auth off). Walk the full demo flow
   (compile → witnesses → approval → activation) locally before touching AWS.
   Nothing here bills, deploys, or mutates cloud state.
1. Make the GitHub repo **public** (First Commit judges only score public repos).
2. `make verify` — 178/178 local assertions.
3. `make benchmark` — reference run matches committed metrics.
4. `make infra-validate` — IaC checks pass.
5. Deploy (`infra/deploy.sh` or `deploy.ps1` — needs `AMPLIFY_TOKEN` set); note ApiUrl output.
   The script does a second pass to wire Cognito into the API and lock CORS to
   the Amplify origin, then prints the admin-bootstrap commands — create your
   `pp-admins` user there (docs/auth.md).
6. `scripts/smoke.sh <api-url>` — health, auth config, canonical build, and a
   401 check proving protected routes reject anonymous access.
7. Open the Amplify URL (Outputs.AmplifyAppId → branch URL); set the UI's API
   field to the ApiUrl; SIGN IN (hosted UI, groups gate the actions);
   COMPILE AMENDMENT; walk Impact → Witnesses → Patch → Tests → Approval
   (approve + activate).
8. Record the 3-minute demo from this flow; screenshot the CloudWatch
   dashboard (name in Outputs) for the write-up.

## Rollback

SAM keeps prior versions: `aws cloudformation rollback-stack`, or redeploy a
previous commit (Amplify auto-rebuilds). DynamoDB PITR restores registry state.
`sam delete` + bucket emptying tears everything down (see cost doc).

## Failure modes

EXTRACTION_FAILURE → fix text / constrained retry → NEEDS_REVIEW. No witness →
clean bill (no invented witnesses). NO_VALIDATED_PATCH → HUMAN_REVIEW_REQUIRED.
Bedrock outage → deterministic stages keep working from stored Rule IR.
Duplicate compile → idempotent reuse via compile_key.
