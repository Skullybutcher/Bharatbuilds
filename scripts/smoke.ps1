# Post-deploy smoke test (PowerShell).
param([string]$Api)
$ErrorActionPreference = "Stop"
if (-not $Api) { throw "usage: smoke.ps1 -Api <api-url>" }
Write-Output "== health =="; Invoke-RestMethod "$Api/"
Write-Output "== canonical build =="
$b = Invoke-RestMethod "$Api/demo/canonical"
Write-Output "$($b.build_id) $($b.status) witnesses=$($b.witnesses.Count)"
Write-Output "== guardrails =="; Invoke-RestMethod "$Api/builds/$($b.build_id)/guardrails" | ConvertTo-Json -Depth 4
Write-Output "SMOKE_OK"
