#!/usr/bin/env bash
# ProcessPatch AWS deploy (SAM). See docs/deployment-runbook.md.
set -euo pipefail
STACK="${STACK:-processpatch-demo}"
REGION="${AWS_REGION:-ap-south-1}"
PARAMS="$(dirname "$0")/parameters.json"

command -v sam >/dev/null || { echo "install AWS SAM CLI first"; exit 1; }
command -v aws >/dev/null || { echo "install AWS CLI first"; exit 1; }

sam build --template-file infra/template.yaml
sam deploy --stack-name "$STACK" --region "$REGION" --capabilities CAPABILITY_IAM \
  --parameter-overrides file://"$PARAMS" --no-confirm-changeset --no-fail-empty-changeset

API=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
echo "API: $API"
bash scripts/smoke.sh "$API"
