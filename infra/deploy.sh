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

# Auth params are passed explicitly below (resolved from stack outputs), so
# exclude them here to avoid duplicate --parameter-overrides keys.
OVERRIDES=$(python3 -c "import json;print(' '.join(f\"ParameterKey={k},ParameterValue={v}\" for k,v in json.load(open('$PARAMS')).items() if k not in ('FrontendOrigin','PP_USER_POOL_ID','PP_CLIENT_ID','PP_AUTH_DOMAIN')))")
# shellcheck disable=SC2086
sam build --template-file infra/template.yaml
# shellcheck disable=SC2086
sam deploy --stack-name "$STACK" --region "$REGION" --capabilities CAPABILITY_IAM \
  --parameter-overrides $OVERRIDES ParameterKey=AmplifyAccessToken,ParameterValue="$AMPLIFY_TOKEN" \
  --no-confirm-changeset --no-fail-empty-changeset

API=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
echo "API: $API"

# Auth wiring: read pool outputs back and redeploy once so ApiFn/FrontendOrigin
# get the real values (docs/auth.md). Amplify needs the final URL to exist first.
POOL=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)
CLIENT=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text)
DOMAIN=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='AuthDomain'].OutputValue" --output text)
AMPLIFY_URL=$(aws amplify list-apps --region "$REGION" --query "apps[?name=='processpatch-${STACK##*-}']|[0].defaultDomain" --output text 2>/dev/null || echo "")
BRANCH_URL="https://main.${AMPLIFY_URL}" ; [ "$AMPLIFY_URL" = "None" ] || [ -z "$AMPLIFY_URL" ] && BRANCH_URL="https://main.dummy.amplifyapp.com"
echo "AUTH: pool=$POOL client=$CLIENT domain=$DOMAIN"
echo "Re-deploying with auth parameters (FrontendOrigin=$BRANCH_URL)…"
sam deploy --stack-name "$STACK" --region "$REGION" --capabilities CAPABILITY_IAM \
  --parameter-overrides $OVERRIDES ParameterKey=AmplifyAccessToken,ParameterValue="$AMPLIFY_TOKEN" \
  ParameterKey=FrontendOrigin,ParameterValue="$BRANCH_URL" \
  ParameterKey=PP_USER_POOL_ID,ParameterValue="$POOL" \
  ParameterKey=PP_CLIENT_ID,ParameterValue="$CLIENT" \
  ParameterKey=PP_AUTH_DOMAIN,ParameterValue="$DOMAIN" \
  --no-confirm-changeset --no-fail-empty-changeset

echo "Create the first admin after deploy:"
echo "  aws cognito-idp admin-create-user --user-pool-id $POOL --username <email> --user-attributes Name=email,Value=<email> Name=email_verified,Value=true --message-action SUPPRESS --region $REGION"
echo "  aws cognito-idp admin-add-user-to-group --user-pool-id $POOL --group-name pp-admins --username <email> --region $REGION"

echo "API: $API"
bash scripts/smoke.sh "$API"
