# ProcessPatch AWS deploy (PowerShell). See docs/deployment-runbook.md + docs/auth.md.
# NOTE: `sam deploy --parameter-overrides` takes explicit
# ParameterKey=...,ParameterValue=... pairs (NOT file://...).
param([string]$Stack = "processpatch-demo", [string]$Region = "ap-south-1")
$ErrorActionPreference = "Stop"
if (-not (Get-Command sam -ErrorAction SilentlyContinue)) { throw "install AWS SAM CLI first" }
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw "install AWS CLI first" }
if (-not $env:AMPLIFY_TOKEN) { throw "set `$env:AMPLIFY_TOKEN (GitHub token for Amplify hosting) first" }
$pairs = (Get-Content infra/parameters.json | ConvertFrom-Json).PSObject.Properties | ForEach-Object { "ParameterKey=$($_.Name),ParameterValue=$($_.Value)" }
sam build --template-file infra/template.yaml
sam deploy --stack-name $Stack --region $Region --capabilities CAPABILITY_IAM `
  --parameter-overrides @pairs "ParameterKey=AmplifyAccessToken,ParameterValue=$env:AMPLIFY_TOKEN" `
  --no-confirm-changeset --no-fail-empty-changeset
$api = aws cloudformation describe-stacks --stack-name $Stack --region $Region `
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text

# Auth wiring: read pool outputs back and redeploy once so ApiFn gets the real
# values and CORS is locked to the Amplify origin (docs/auth.md).
$pool   = aws cloudformation describe-stacks --stack-name $Stack --region $Region --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text
$client = aws cloudformation describe-stacks --stack-name $Stack --region $Region --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text
$domain = aws cloudformation describe-stacks --stack-name $Stack --region $Region --query "Stacks[0].Outputs[?OutputKey=='AuthDomain'].OutputValue" --output text
$appId  = aws cloudformation describe-stacks --stack-name $Stack --region $Region --query "Stacks[0].Outputs[?OutputKey=='AmplifyAppId'].OutputValue" --output text
$branchUrl = "https://main.$appId.amplifyapp.com"
Write-Output "AUTH: pool=$pool client=$client domain=$domain"
Write-Output "Re-deploying with auth parameters (FrontendOrigin=$branchUrl)..."
sam deploy --stack-name $Stack --region $Region --capabilities CAPABILITY_IAM `
  --parameter-overrides @pairs "ParameterKey=AmplifyAccessToken,ParameterValue=$env:AMPLIFY_TOKEN" `
  "ParameterKey=FrontendOrigin,ParameterValue=$branchUrl" `
  "ParameterKey=PP_USER_POOL_ID,ParameterValue=$pool" `
  "ParameterKey=PP_CLIENT_ID,ParameterValue=$client" `
  "ParameterKey=PP_AUTH_DOMAIN,ParameterValue=$domain" `
  --no-confirm-changeset --no-fail-empty-changeset

Write-Output "Create the first admin after deploy:"
Write-Output "  aws cognito-idp admin-create-user --user-pool-id $pool --username <email> --user-attributes Name=email,Value=<email> Name=email_verified,Value=true --message-action SUPPRESS --region $Region"
Write-Output "  aws cognito-idp admin-add-user-to-group --user-pool-id $pool --group-name pp-admins --username <email> --region $Region"

Write-Output "API: $api"
powershell -File scripts/smoke.ps1 -Api $api
