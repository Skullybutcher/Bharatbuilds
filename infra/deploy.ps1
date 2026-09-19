# ProcessPatch AWS deploy (PowerShell). See docs/deployment-runbook.md.
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
Write-Output "API: $api"
powershell -File scripts/smoke.ps1 -Api $api
