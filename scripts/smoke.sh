#!/usr/bin/env bash
# Post-deploy smoke test: health + canonical build + guardrails.
set -euo pipefail
API="${1:?usage: smoke.sh <api-url>}"
echo "== health =="; curl -fsS "$API/" | head -c 200; echo
echo "== canonical build =="; curl -fsS "$API/demo/canonical" -o /tmp/pp-build.json; echo saved
python3 -c "import json;b=json.load(open('/tmp/pp-build.json'));print(b['build_id'],b['status'],len(b.get('witnesses',[])))"
BID=$(python3 -c "import json;print(json.load(open('/tmp/pp-build.json'))['build_id'])")
echo "== guardrails =="; curl -fsS "$API/builds/$BID/guardrails" | head -c 400; echo
echo SMOKE_OK
