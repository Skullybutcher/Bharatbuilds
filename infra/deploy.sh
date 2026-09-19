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
[ -n "${AMPLIFY_TOKEN:-}" ] || { echo "AMPLIFY_TOKEN is required; add it as a GitHub Actions secret before deployment" >&2; exit 2; }

# Auth params are passed explicitly below (resolved from stack outputs), so
# exclude them here to avoid duplicate --parameter-overrides keys.
OVERRIDES=$(python3 -c 'import json,sys; excluded={"FrontendOrigin","PP_USER_POOL_ID","PP_CLIENT_ID","PP_AUTH_DOMAIN"}; parameters=json.load(open(sys.argv[1], encoding="utf-8")); print(" ".join("ParameterKey={},ParameterValue={}".format(key,value) for key,value in parameters.items() if key not in excluded))' "$PARAMS")
BOOTSTRAP_ORIGIN="https://main.dummy.amplifyapp.com"
# shellcheck disable=SC2086
sam build --template-file infra/template.yaml
# shellcheck disable=SC2086
sam deploy --stack-name "$STACK" --region "$REGION" --capabilities CAPABILITY_IAM \
  --parameter-overrides $OVERRIDES ParameterKey=FrontendOrigin,ParameterValue="$BOOTSTRAP_ORIGIN" \
  --resolve-s3 --no-confirm-changeset --no-fail-on-empty-changeset

API=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
if [ -z "$API" ] || [ "$API" = "None" ]; then
  echo "CloudFormation returned no ApiUrl; deployment did not complete successfully" >&2
  exit 1
fi
echo "API: $API"

# Auth wiring: read pool outputs back and redeploy once so ApiFn/FrontendOrigin
# get the real values (docs/auth.md). Amplify needs the final URL to exist first.
POOL=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)
CLIENT=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text)
DOMAIN=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='AuthDomain'].OutputValue" --output text)
# FrontendOrigin must be the REAL deployed URL — CORS for the API and the
# Cognito callback both hang off it. Discovery order (T33: the silent-dummy
# fallback once shipped and CORS-blocked every real browser):
#   1. FRONTEND_ORIGIN env (explicit override, always wins)
#   2. Amplify app lookup by name pattern
#   3. Loud failure — never silently deploy a placeholder again
if [ -n "${FRONTEND_ORIGIN:-}" ]; then
  BRANCH_URL="$FRONTEND_ORIGIN"
  echo "FrontendOrigin: $BRANCH_URL (from FRONTEND_ORIGIN env)"
else
  # Try 1: app name matching the stack suffix.
  AMPLIFY_URL=$(aws amplify list-apps --region "$REGION" --query "apps[?name=='processpatch-${STACK##*-}']|[0].defaultDomain" --output text 2>/dev/null || echo "")
  # Try 2: if the name didn't match (apps get renamed/created manually), scan
  # every Amplify app; if exactly one hosts an amplifyapp.com domain, it's ours.
  if [ -z "$AMPLIFY_URL" ] || [ "$AMPLIFY_URL" = "None" ]; then
    AMPLIFY_URL=$(aws amplify list-apps --region "$REGION" --output json 2>/dev/null | python3 -c '
import json,sys
apps=json.load(sys.stdin).get("apps",[])
doms=[a.get("defaultDomain","") for a in apps if a.get("defaultDomain","").endswith("amplifyapp.com")]
print(doms[0] if len(doms)==1 else "")' || echo "")
  fi
  if [ -n "$AMPLIFY_URL" ] && [ "$AMPLIFY_URL" != "None" ]; then
    BRANCH_URL="https://main.${AMPLIFY_URL}"
    echo "FrontendOrigin: $BRANCH_URL (discovered from Amplify)"
  else
    echo "ERROR: could not discover the Amplify app URL." >&2
    echo "  Either export FRONTEND_ORIGIN=https://<branch>.<app>.amplifyapp.com" >&2
    echo "  or create the Amplify app (name pattern: processpatch-${STACK##*-})." >&2
    echo "  Deploying with a placeholder would CORS-block every real browser." >&2
    exit 3
  fi
fi
echo "AUTH: pool=$POOL client=$CLIENT domain=$DOMAIN"
echo "Re-deploying with auth parameters (FrontendOrigin=$BRANCH_URL)…"
sam deploy --stack-name "$STACK" --region "$REGION" --capabilities CAPABILITY_IAM \
  --parameter-overrides $OVERRIDES ParameterKey=AmplifyAccessToken,ParameterValue="$AMPLIFY_TOKEN" \
  ParameterKey=FrontendOrigin,ParameterValue="$BRANCH_URL" \
  ParameterKey=PP_USER_POOL_ID,ParameterValue="$POOL" \
  ParameterKey=PP_CLIENT_ID,ParameterValue="$CLIENT" \
  ParameterKey=PP_AUTH_DOMAIN,ParameterValue="$DOMAIN" \
  --resolve-s3 \
  --no-confirm-changeset --no-fail-on-empty-changeset

echo "API: $API"

# Demo admin: the template creates demo-admin@processpatch.demo (SUPPRESS,
# pp-admins). CloudFormation cannot set a password. We NEVER rotate an
# existing password automatically (T40: an auto-rotate silently clobbered
# the human-set password on every deploy). Set it explicitly:
#   DEMO_PASSWORD='...' bash infra/deploy.sh          (this deploy)
#   aws cognito-idp admin-set-user-password --user-pool-id <pool> \
#     --username demo-admin@processpatch.demo --password '<pass>' --permanent
DEMO_USER="demo-admin@processpatch.demo"
if aws cognito-idp admin-get-user --user-pool-id "$POOL" --username "$DEMO_USER" --region "$REGION" >/dev/null 2>&1; then
  if [ -n "${DEMO_PASSWORD:-}" ]; then
    if aws cognito-idp admin-set-user-password --user-pool-id "$POOL" --username "$DEMO_USER" --password "$DEMO_PASSWORD" --permanent --region "$REGION" >/dev/null 2>&1; then
      echo "DEMO LOGIN: $DEMO_USER / password set from DEMO_PASSWORD env"
    else
      echo "WARNING: could not set demo-admin password from DEMO_PASSWORD (policy?)" >&2
    fi
  else
    echo "DEMO LOGIN: $DEMO_USER exists — password unchanged (set via DEMO_PASSWORD env or admin-set-user-password)"
  fi
else
  echo "NOTE: demo user $DEMO_USER not found in pool (pre-existing stack?) — create manually."
fi

bash scripts/smoke.sh "$API"
