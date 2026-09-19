#!/usr/bin/env bash
# Cloud end-to-end smoke — drives the DEPLOYED stack exactly like the UI does:
#   password auth -> Bearer token -> compile (deferred) -> execute (Step
#   Functions) -> poll build -> the three HITL gates via /resume ->
#   governance bundle + coverage.
#
# NOTE: the smoke compiles a NOVEL amendment (threshold 7.25, not the
# canonical 7.5). The canonical demo policy already exists as a build, and the
# product's idempotency would return it — the pipeline would short-circuit
# READY_CACHED and never wait at a gate. Correct product behavior; wrong smoke
# input. A fresh policy exercises the full gate path.
#
# Usage:
#   bash scripts/cloud_smoke.sh <api-url> <email> <password>
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

TMP="${TMPDIR:-.}/pp-smoke.$$"          # repo-local temp: Windows curl can't see git-bash /tmp
PAYLOAD="pp-smoke-payload.$$.json"
trap 'rm -f "$TMP" "$PAYLOAD"' EXIT

# ---- auth config must be public and enabled --------------------------------
say "auth config"
AUTHCFG=$(curl -fsS "$API/auth/config")
echo "$AUTHCFG"
[ "$(echo "$AUTHCFG" | jqpy "d['enabled']")" = "True" ] || { echo "auth disabled on this stack — nothing to smoke" >&2; exit 0; }
CLIENT=$(echo "$AUTHCFG" | jqpy "d['client_id']")
DOMAIN=$(echo "$AUTHCFG" | jqpy "d['domain']")

# ---- PASSWORD auth via InitiateAuth (USER_PASSWORD_AUTH) --------------------
# NOTE: the OAuth2 /oauth2/token endpoint only serves AllowedOAuthFlows ([code]);
# the password grant lives on the InitiateAuth API (ALLOW_USER_PASSWORD_AUTH).
say "login ($EMAIL)"
REGION=$(echo "$API" | sed -E 's#https://[^.]+\.execute-api\.([a-z0-9-]+)\.amazonaws\.com.*#\1#')
TOKENS=$(curl -fsS -X POST "https://cognito-idp.$REGION.amazonaws.com/" \
  -H "Content-Type: application/x-amz-json-1.1" \
  -H "X-Amz-Target: AWSCognitoIdentityProviderService.InitiateAuth" \
  -d '{"AuthFlow":"USER_PASSWORD_AUTH","ClientId":"'"$CLIENT"'","AuthParameters":{"USERNAME":"'"$EMAIL"'","PASSWORD":"'"$PASS"'"}}') \
  || { echo "login failed — check the password" >&2; exit 2; }
IDTOK=$(echo "$TOKENS" | jqpy "d['AuthenticationResult']['IdToken']")
ACCTOK=$(echo "$TOKENS" | jqpy "d['AuthenticationResult']['AccessToken']")
# Some HTTP-API authorizer configs accept the ID token, others want the access
# token — probe /builds with each and keep whichever the stack honors.
TOKEN=""
for CAND in "$IDTOK" "$ACCTOK"; do
  [ -n "$CAND" ] && [ "$CAND" != "None" ] || continue
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "$API/builds" -H "Authorization: Bearer $CAND")
  if [ "$CODE" = "200" ]; then TOKEN="$CAND"; break; fi
  echo "  token rejected on /builds (HTTP $CODE) — trying next"
done
[ -n "$TOKEN" ] || { echo "both tokens rejected by the API authorizer" >&2; exit 2; }
echo "token: ${TOKEN:0:24}…"
AH="Authorization: Bearer $TOKEN"

# ---- who am I (role must be admin to pass the gates) -----------------------
say "identity"
curl -fsS "$API/builds" -H "$AH" -o "$TMP" || { echo "GET /builds failed" >&2; exit 2; }
python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print('auth OK —',len(d.get('builds',[])),'builds on record')" "$TMP"

# ---- compile (deferred): NOVEL amendment so idempotency can't short-circuit -
say "compile (deferred → gates)"
python3 - "$PAYLOAD" <<'PYEOF'
import json, sys
policy = """# Smoke amendment (2026-09-19, POLICY-V2) — amends POLICY-V1

### Sec 4.1 Eligibility threshold (amended)
Applicants must have CGPA >= 7.25. (Relaxed from 8.0.)

### Sec 4.2 Recommendation (amended)
A faculty recommendation is required only when CGPA < 8.0.

### Sec 4.3 Ordering / prerequisite (unchanged)
Department approval must occur before final submission.
"""
json.dump({"domain": "research_grant", "defer": True, "policy_text": policy},
          open(sys.argv[1], "w"))
PYEOF
B=$(curl -fsS -X POST "$API/builds" -H "$AH" -H "Content-Type: application/json" --data-binary @"$PAYLOAD")
BID=$(echo "$B" | jqpy "d['build_id']")
echo "build: $BID  (idempotent_reuse: $(echo "$B" | jqpy "d.get('idempotent_reuse', False)"))"
[ -n "$BID" ] && [ "$BID" != "None" ] || die "no build_id from POST /builds: $B"
case "$(echo "$B" | jqpy "d.get('idempotent_reuse', False)")" in
  True) die "POST /builds returned an existing build — the smoke policy is no longer novel (7.25 compiled before?); pick a fresh threshold" ;;
esac

say "execute (Step Functions)"
EX=$(curl -fsS -X POST "$API/builds/$BID/execute" -H "$AH" -H "Content-Type: application/json" -d '{}')
ARN=$(echo "$EX" | jqpy "d['executionArn']")
echo "execution: ${ARN##*/}"
[ -n "$ARN" ] && [ "$ARN" != "None" ] || die "no executionArn from /execute: $EX"

# ---- wait for the execution to park at a gate, then adopt the real build id --
# A DRAFT never mutates (by design); Step Functions compiles under a NEW hash-
# derived BUILD- id and persists it. Follow the execution output to find it.
poll_exec() {
  local OUT=""
  for _ in $(seq 1 60); do
    OUT=$(curl -fsS "$API/executions/$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1], safe=''))" "$ARN")" -H "$AH" 2>/dev/null || echo "")
    ES=$(echo "$OUT" | jqpy "d['status']" 2>/dev/null || echo "?")
    BS=$(echo "$OUT" | jqpy "(d.get('output') or '')" 2>/dev/null | python3 -c "import json,sys;print(json.loads(sys.stdin.read() or '{}').get('build_id','-'))" 2>/dev/null || echo "-")
    echo "  exec: $ES  build_id: $BS"
    case "$ES" in
      SUCCEEDED|FAILED|TIMED_OUT|ABORTED) break;;
    esac
    sleep 3
  done
  [ "$ES" = "SUCCEEDED" ] || die "execution ended $ES — check the SFN console / GovernFn logs"
  [ "$BS" != "-" ] || die "execution output carried no build_id — cloud persist op did not return the doc"
  BID="$BS"
  echo "  adopted cloud build: $BID"
}
poll_exec

# ---- poll until the build parks at a gate ------------------------------------
# Two paths by design:
#   NEEDS_REVIEW    -> Gate 1 (rule_review) first, then Gate 2/3
#   PATCH_VALIDATED -> extraction clean + auto-accepted: Gate 1 auto-passed,
#                      skip straight to Gate 2 (patch_approval)
#   NO_VALIDATED_PATCH -> compile/validation failed upstream (fail loudly)
poll_status() { # $1 = terminal-ish statuses we accept, space-separated
  local ST="?"
  for _ in $(seq 1 40); do
    ST=$(curl -fsS "$API/builds/$BID" -H "$AH" | jqpy "d['status']" 2>/dev/null || echo "?")
    echo "  status: $ST"
    case " $1 " in *" $ST "*) return 0;; esac
    sleep 3
  done
  return 1
}
poll_status "NEEDS_REVIEW PATCH_VALIDATED NO_VALIDATED_PATCH" \
  || die "build never parked at a gate (wanted NEEDS_REVIEW/PATCH_VALIDATED/NO_VALIDATED_PATCH)"

if [ "$ST" = "NEEDS_REVIEW" ]; then
  # ---- Gate 1: rule reviews ---------------------------------------------------
  say "Gate 1: rule reviews"
  REVIEW=$(resume_gate '{"gate":"rule_review","decisions":{},"reviewer":{"reviewer_id":"'"$EMAIL"'","display_name":"cloud-smoke"}}')
  case "$REVIEW" in *'"error"'*) die "rule_review rejected: $REVIEW";; esac
  poll_status "PATCH_VALIDATED" || die "build never reached PATCH_VALIDATED after rule review"
fi

# resume_gate: POST /builds/$BID/resume with retry while Step Functions hasn't
# armed the gate's callback yet (status can flip PATCH_VALIDATED a beat before
# the wait state registers its taskToken).
resume_gate() { # $1 = json body
  local TRY OUT=""
  for TRY in $(seq 1 12); do
    OUT=$(curl -s -X POST "$API/builds/$BID/resume" -H "$AH" \
      -H "Content-Type: application/json" -d "$1" || true)
    case "$OUT" in
      *"no waiting callback"*) echo "  gate not armed yet (retry $TRY)…" >&2; sleep 3;;
      *) printf '%s' "$OUT"; return 0;;
    esac
  done
  printf '%s' "$OUT"
}

# ---- Gate 2: patch approval ---------------------------------------------------
# ASL contract: PATCH_APPROVED? matches decision == APPROVE_CANDIDATE
# (REQUEST_REVISION / REJECT_PATCH are the other branches). decide_patch
# validates the same vocabulary.
say "Gate 2: patch approval"
PA=$(resume_gate '{"gate":"patch_approval","decision":"APPROVE_CANDIDATE","role":"PROCEDURE_OWNER","reviewer":{"reviewer_id":"'"$EMAIL"'","display_name":"cloud-smoke"},"reason":"cloud-smoke"}')
echo "$PA" | head -c 200; echo
case "$PA" in *'"error"'*) die "patch_approval rejected: $PA";; esac

# ---- Gate 3: activation -------------------------------------------------------
say "Gate 3: activation"
ACT=$(resume_gate '{"gate":"activation","decision":"APPROVE","reviewer":{"reviewer_id":"'"$EMAIL"'","display_name":"cloud-smoke"},"reason":"cloud-smoke"}')
echo "$ACT" | head -c 300; echo
case "$ACT" in *'"error"'*) die "activation rejected: $ACT";; esac

say "final status"
poll_status "PATCH_ACTIVE" || die "build never reached PATCH_ACTIVE after activation"

# ---- governance artifacts on the activated build -----------------------------
say "governance bundle"
GB=$(curl -fsS "$API/builds/$BID/governance-bundle" -H "$AH")
echo "$GB" | jqpy "len(d.get('approvals',[]))" | xargs -I{} echo "approvals in bundle: {}"
echo "$GB" | jqpy "d.get('bundle_sha256','?')[:16]" | xargs -I{} echo "bundle sha256: {}…"

say "coverage"
COV=$(curl -fsS "$API/builds/$BID/coverage" -H "$AH")
echo "$COV"

say "SMOKE_OK — full cloud pipeline green (novel compile → gates → activated → bundle → coverage)"
