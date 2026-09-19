# Deploy status — live status page (re-audited 2026-09-19)

Target: `https://main.d1bq8os9dwj0d.amplifyapp.com/` + its HttpApi
(`https://ssv1hifpvl.execute-api.ap-south-1.amazonaws.com/prod`, read from the
live `/config.js`). Method: unauthenticated curl from outside AWS. Prior
doom-report: T25 audit same URL (localhost `config.js`, 404 `/api/*`, stale
shell) — all three fixed since.

## Verdict table (today's evidence)

| Check | Result | Evidence |
|---|---|---|
| `/config.js` points at the real API | WORKS | Serves `window.PROCESSPATCH_API = ... "https://ssv1hifpvl.execute-api.ap-south-1.amazonaws.com/prod"` — zero `localhost:8000` |
| Deployed UI is current | WORKS | Shell (2763 B) carries fonts, phosphor icons, theme boot, and palette markers (was 1731 B pre-T12) |
| API reachable + auth wall | WORKS | `/auth/config` 200 with real pool (`processpatch-demo-…`, client `3ri60…`); unauthenticated `POST /builds` → 401 |
| CORS origin echo | WORKS | `Access-Control-Allow-Origin: https://main.d1bq8os9dwj0d.amplifyapp.com` + `Vary: origin` on live responses |
| Preflight from a real browser | BLOCKED (new finding) | `OPTIONS /builds` with Origin → **401** (`WWW-Authenticate: Bearer`): the authorizer runs on preflight, and a non-2xx preflight fails every browser call that needs one — i.e. all POSTs and everything carrying `Authorization`. curl is green; browsers are not |
| `/health` is 401 | MINOR / STALE DOC | `docs/auth.md` lists `/health` as NO_AUTH, but `infra/template.yaml` exempts only `/`, `/demo/canonical`, `/auth/config` — deployed matches the template, so the doc (or the template) needs a one-liner. Flagged, not fixed here |
| Cognito callback whitelist | PRIOR VERIFIED, not re-probed | T35 verified evil-origin `redirect_mismatch` vs ours → login page; today's direct probes of the authorize endpoint didn't complete from this network — no change claimed either way |
| Demo password set by human | REMAINING (owner action) | Unverifiable from outside; see `docs/auth.md` "Deployed demo login" (print-once block from `deploy.sh`) |
| Full cloud E2E | REMAINING | `scripts/cloud_smoke.sh` exists; needs a run with real creds + URL by the human |

## Done on 2026-09-19 (old fix-runbook, shrunk)

Config generation, CORS allow-list, callback whitelist, and DemoAdmin +
print-once password all shipped via the T33/T35/T37 deploy work — detail in
those agents.md log rows, not repeated here. The one piece still open from
that runbook is a **browser-visible preflight failure**: per AWS, when a
`$default` route plus authorizer catches `OPTIONS`, add an `OPTIONS /{proxy+}`
route without authorization so preflight returns 2xx (AWS docs, "Configuring
CORS for an HTTP API with a `$default` route and an authorizer"). That's an
infra change for Buffy/human — the ACAO echo being correct is necessary but
not sufficient, and no curl-based check can catch it.

## AWS docs cited

- HTTP API CORS + the `$default`-route preflight case:
  https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-cors.html
- Amplify environment variables:
  https://docs.aws.amazon.com/amplify/latest/userguide/setting-env-vars.html
- CloudFormation Outputs:
  https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html

## Judge-readiness checklist (current state)

1. `/config.js` serves the real API URL; network tab shows zero `localhost:8000` calls.
2. Unauthenticated protected call returns 401 (authorizer working, verified live).
3. In a REAL browser (not curl): sign in and complete an authenticated POST — blocked until the unauthenticated `OPTIONS /{proxy+}` route ships (preflight 401s today).
4. Demo password set by human; sign-in as demo-admin verified before showtime.
5. `scripts/judge_demo.py` ALL 6 BEATS VERIFIED + `scripts/cloud_smoke.sh` green against the live API.
