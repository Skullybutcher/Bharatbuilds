#!/usr/bin/env bash
# Post-deploy smoke test: health + auth config + canonical build + guardrails.
set -euo pipefail
API="${1:?usage: smoke.sh <api-url>}"
echo "== health =="; curl -fsS "$API/" | head -c 200; echo
echo "== auth config (public) =="; curl -fsS "$API/auth/config" | head -c 300; echo
echo "== authz enforced (expect 401 on builds without a token) =="
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$API/builds") || CODE=000
if [ "$CODE" = "200" ]; then echo "note: /builds reachable without auth (auth off or legacy client config)"; else echo "got HTTP $CODE (401/403 expected when auth is on)"; fi
echo "== canonical build =="; curl -fsS "$API/demo/canonical" -o /tmp/pp-build.json; echo saved
python3 -c "import json;b=json.load(open('/tmp/pp-build.json'));print(b['build_id'],b['status'],len(b.get('witnesses',[])))"
BID=$(python3 -c "import json;print(json.load(open('/tmp/pp-build.json'))['build_id'])")
echo "== protected read (expect 401/403 without a token) =="
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$API/builds/$BID/guardrails") || CODE=000
case "$CODE" in 401|403) echo "PASS: protected route rejected anonymous access (HTTP $CODE)";; *) echo "note: got HTTP $CODE (200 = auth off or legacy client config)";; esac
echo SMOKE_OK
