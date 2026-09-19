# ProcessPatch AWS deploy (PowerShell). See docs/deployment-runbook.md + docs/auth.md.
# NOTE: `sam deploy --parameter-overrides` takes explicit
# ParameterKey=...,ParameterValue=... pairs (NOT file://...).
param([string]$Stack = "processpatch-demo", [string]$Region = "ap-south-1")
$ErrorActionPreference = "Stop"
if (-not (Get-Command sam -ErrorAction SilentlyContinue)) { throw "install AWS SAM CLI first" }
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw "install AWS CLI first" }
$pairs = (Get-Content infra/parameters.json | ConvertFrom-Json).PSObject.Properties | ForEach-Object { "ParameterKey=$($_.Name),ParameterValue=$($_.Value)" }
sam build --template-file infra/template.yaml
sam deploy --stack-name $Stack --region $Region --capabilities CAPABILITY_IAM `
  --parameter-overrides @pairs `
  --resolve-s3 `
  --no-confirm-changeset --no-fail-on-empty-changeset
if ($LASTEXITCODE -ne 0) { throw "SAM deployment failed with exit code $LASTEXITCODE" }
$api = aws cloudformation describe-stacks --stack-name $Stack --region $Region `
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text
if (-not $api -or $api -eq "None") { throw "CloudFormation returned no ApiUrl; deployment did not complete successfully" }
Write-Output "API: $api"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke.ps1 -Api $api
