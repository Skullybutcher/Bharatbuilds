# ProcessPatch AWS deploy (PowerShell). See docs/deployment-runbook.md.
param([string]$Stack = "processpatch-demo", [string]$Region = "ap-south-1")
$ErrorActionPreference = "Stop"
if (-not (Get-Command sam -ErrorAction SilentlyContinue)) { throw "install AWS SAM CLI first" }
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw "install AWS CLI first" }
sam build --template-file infra/template.yaml
sam deploy --stack-name $Stack --region $Region --capabilities CAPABILITY_IAM `
  --parameter-overrides file://infra/parameters.json --no-confirm-changeset --no-fail-empty-changeset
$api = aws cloudformation describe-stacks --stack-name $Stack --region $Region `
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text
Write-Output "API: $api"
powershell -File scripts/smoke.ps1 -Api $api
