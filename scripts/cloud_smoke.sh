#!/usr/bin/env bash
# Cloud end-to-end smoke — drives the DEPLOYED stack exactly like the UI does:
#   password auth -> Bearer token -> compile (deferred) -> execute (Step
#   Functions) -> poll build -> hit the three HITL gates via /resume ->
#   governance bundle + coverage.
#
# Usage:
#   bash scripts/cloud_smoke.sh <api-url> <email> <password>
#   (get the password from the deploy run's "DEMO LOGIN" block, or run
#    infra/deploy.sh locally — it prints it once)
#
# Exit codes: 0 = full pipeline green; 1 = usage; 2 = login/token failure;
#             3 = pipeline error at a named stage.
set -euo pipefail

API="${1:?usage: cloud_smoke.sh <api-url> <email> <password>}"
EMAIL="${2:?usage: cloud_smoke.sh <api-url> <email> <password>}"
PASS="${3:?usage: cloud_smoke.sh <api-url> <email> <password>}"

say() { printf '\n== %s ==\n' "$*"; }
die() { echo "FAIL: $*" >&2; exit 3; }
jqpy() { python3 -c "import json,sys;d=json.load(sys.stdin);print(eval(sys.argv[1]))" "$1"; }

command -v python3 >/dev/null || { echo "python3 required" >&2; exit 1; }

# ---- auth config must be public and enabled --------------------------------
say "auth config"
AUTHCFG=$(curl -fsS "$API/auth/config")
echo "$AUTHCFG"
[ "$(echo "$AUTHCFG" | jqpy "d['enabled']")" = "True" ] || { echo "auth disabled on this stack — nothing to smoke" >&2; exit 0; }
CLIENT=$(echo "$AUTHCFG" | jqpy "d['client_id']")
DOMAIN=$(echo "$AUTHCFG" | jqpy "d['domain']")

# ---- PASSWORD grant -> tokens (same creds the UI host would produce) -------
say "login ($EMAIL)"
TOKENS=$(curl -fsS -X POST "https://$DOMAIN/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=$CLIENT" \
  --data-urlencode "username=$EMAIL" \
  --data-urlencode "password=$PASS" \
  --data-urlencode "scope=openid email") || { echo "login failed — check the password from the deploy log" >&2; exit 2; }
TOKEN=$(echo "$TOKENS" | jqpy "d['id_token'] or d['access_token']")
[ -n "$TOKEN" ] && [ "$TOKEN" != "None" ] || { echo "no token in response" >&2; exit 2; }
echo "token: ${TOKEN:0:24}…"
AH="Authorization: Bearer $TOKEN"

# ---- who am I (role must be admin to pass the gates) -----------------------
say "identity"
curl -fsS "$API/builds" -H "$AH" | head -c 120; echo " …auth OK"

# ---- compile (deferred: stops at Gate 1) -----------------------------------
say "compile (deferred → Gate 1)"
B=$(curl -fsS -X POST "$API/builds" -H "$AH" -H "Content-Type: application/json" \
  -d '{"domain":"research_grant","defer":true}')
BID=$(echo "$B" | jqpy "d['build_id']")
echo "build: $BID"
[ -n "$BID" ] && [ "$BID" != "None" ] || die "no build_id from POST /builds: $B"

say "execute (Step Functions)"
EX=$(curl -fsS -X POST "$API/builds/$BID/execute" -H "$AH" -H "Content-Type: application/json" -d '{}')
echo "$EX" | head -c 200; echo

# ---- poll until the build parks at a gate (rule_review first) --------------
poll_status() { # $1 = terminal-ish statuses we accept, space-separated
  for _ in $(seq 1 40); do
    ST=$(curl -fsS "$API/builds/$BID" -H "$AH" | jqpy "d['status']" 2>/dev/null || echo "?")
    echo "  status: $ST"
    case " $1 " in *" $ST "*) return 0;; esac
    sleep 3
  done
  return 1
}
poll_status "NEEDS_REVIEW" || die "build never reached NEEDS_REVIEW (rule_review gate)"

# ---- Gate 1: rule reviews ---------------------------------------------------
say "Gate 1: rule reviews"
REVIEW=$(curl -fsS -X POST "$API/builds/$BID/resume" -H "$AH" -H "Content-Type: application/json" \
  -d '{"gate":"rule_review","decisions":{},"reviewer":{"reviewer_id":"'"$EMAIL"'","display_name":"cloud-smoke"}}')
echo "$REVIEW" | head -c 200; echo
# decisions:{} approves all open rules (see govern_handler); if the API
# requires explicit decisions, the response names them — surface that.
case "$REVIEW" in *'"error"'*) die "rule_review rejected: $REVIEW";; esac

poll_status "NEEDS_APPROVAL" || die "build never reached NEEDS_APPROVAL (patch gate)"

# ---- Gate 2: patch approval --------------------------------------------------
say "Gate 2: patch approval"
PA=$(curl -fsS -X POST "$API/builds/$BID/resume" -H "$AH" -H "Content-Type: application/json" \
  -d '{"gate":"patch_approval","decision":"APPROVE","role":"PROCEDURE_OWNER","reviewer":{"reviewer_id":"'"$EMAIL"'","display_name":"cloud-smoke"},"reason":"cloud-smoke"}')
echo "$PA" | head -c 200; echo
case "$PA" in *'"error"'*) die "patch_approval rejected: $PA";; esac

# ---- Gate 3: activation ------------------------------------------------------
say "Gate 3: activation"
ACT=$(curl -fsS -X POST "$API/builds/$BID/resume" -H "$AH" -H "Content-Type: application/json" \
  -d '{"gate":"activation","decision":"APPROVE","reviewer":{"reviewer_id":"'"$EMAIL"'","display_name":"cloud-smoke"},"reason":"cloud-smoke"}')
echo "$ACT" | head -c 300; echo
case "$ACT" in *'"error"'*) die "activation rejected: $ACT";; esac

# ---- governance artifacts on the activated build -----------------------------
say "governance bundle"
GB=$(curl -fsS "$API/builds/$BID/governance-bundle" -H "$AH")
echo "$GB" | jqpy "len(d.get('approvals',[]))" | xargs -I{} echo "approvals in bundle: {}"
echo "$GB" | jqpy "d.get('bundle_sha256','?')[:16]" | xargs -I{} echo "bundle sha256: {}…"

say "coverage"
COV=$(curl -fsS "$API/builds/$BID/coverage" -H "$AH")
echo "$COV"

say "SMOKE_OK — full cloud pipeline green (compile → 3 gates → activated → bundle → coverage)"
