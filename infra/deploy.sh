#!/usr/bin/env bash
# ProcessPatch AWS deploy (SAM). See docs/deployment-runbook.md.
# NOTE: `sam deploy --parameter-overrides` takes explicit
# ParameterKey=...,ParameterValue=... pairs (NOT file://...), so we expand
# infra/parameters.json with stdlib python (no jq dependency).
set -euo pipefail
STACK="${STACK:-processpatch-demo}"
REGION="${AWS_REGION:-ap-south-1}"
PARAMS="$(dirname "$0")/parameters.json"

command -v sam >/dev/null || { echo "install AWS SAM CLI first"; exit 1; }
command -v aws >/dev/null || { echo "install AWS CLI first"; exit 1; }
[ -n "${AMPLIFY_TOKEN:-}" ] || { echo "export AMPLIFY_TOKEN (GitHub token for Amplify hosting) first"; exit 1; }

OVERRIDES=$(python3 -c "import json;print(' '.join(f\"ParameterKey={k},ParameterValue={v}\" for k,v in json.load(open('$PARAMS')).items()))")
# shellcheck disable=SC2086
sam build --template-file infra/template.yaml
# shellcheck disable=SC2086
sam deploy --stack-name "$STACK" --region "$REGION" --capabilities CAPABILITY_IAM \
  --parameter-overrides $OVERRIDES ParameterKey=AmplifyAccessToken,ParameterValue="$AMPLIFY_TOKEN" \
  --no-confirm-changeset --no-fail-empty-changeset

API=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
echo "API: $API"
bash scripts/smoke.sh "$API"
