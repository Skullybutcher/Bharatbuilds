# Deployment runbook

0. Make the GitHub repo **public** (First Commit judges only score public repos).
1. `make verify` — 142/142 local assertions.
2. `make benchmark` — reference run matches committed metrics.
3. `make infra-validate` — IaC checks pass.
4. Deploy (`infra/deploy.sh` or `deploy.ps1` — needs `AMPLIFY_TOKEN` set); note ApiUrl output.
5. `scripts/smoke.sh <api-url>` — health, canonical build, guardrails.
6. Open the Amplify URL (Outputs.AmplifyAppId → branch URL); set the UI's API
   field to the ApiUrl; COMPILE AMENDMENT; walk Impact → Witnesses → Patch →
   Tests → Approval (approve + activate).
7. Record the 3-minute demo from this flow; screenshot the CloudWatch
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
