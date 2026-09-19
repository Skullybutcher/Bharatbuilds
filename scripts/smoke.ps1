# Post-deploy smoke test (PowerShell) — mirrors scripts/smoke.sh.
param([string]$Api)
$ErrorActionPreference = "Stop"
if (-not $Api) { throw "usage: smoke.ps1 -Api <api-url>" }

function Get-StatusCode([string]$url) {
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 30
    return [int]$r.StatusCode
  } catch {
    $resp = $_.Exception.Response
    if ($resp) { return [int]$resp.StatusCode }
    return 0
  }
}

Write-Output "== health =="
Invoke-RestMethod "$Api/" | ConvertTo-Json -Depth 3
Write-Output "== auth config (public) =="
Invoke-RestMethod "$Api/auth/config" | ConvertTo-Json -Depth 3
Write-Output "== authz enforced (expect 401/403 on /builds without a token) =="
$code = Get-StatusCode "$Api/builds"
if ($code -eq 200) { Write-Output "note: /builds reachable without auth (auth off or legacy client config)" }
else { Write-Output "got HTTP $code (401/403 expected when auth is on)" }
Write-Output "== canonical build =="
$b = Invoke-RestMethod "$Api/demo/canonical"
Write-Output "$($b.build_id) $($b.status) witnesses=$($b.witnesses.Count)"
Write-Output "== protected read (expect 401/403 without a token) =="
$code = Get-StatusCode "$Api/builds/$($b.build_id)/guardrails"
if ($code -eq 401 -or $code -eq 403) { Write-Output "PASS: protected route rejected anonymous access (HTTP $code)" }
else { Write-Output "note: got HTTP $code (200 = auth off or legacy client config)" }
Write-Output "SMOKE_OK"
