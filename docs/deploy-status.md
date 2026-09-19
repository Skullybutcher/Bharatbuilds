# Deploy status — live outside-in audit (2026-09-19)

Target: `https://main.d1bq8os9dwj0d.amplifyapp.com/`. Method: unauthenticated
curl from outside AWS, exactly what a judge's browser would do. No console
access, no credentials, nothing changed.

## Verdict table

| Check | Result | Evidence |
|---|---|---|
| UI shell `/` | WORKS | 200 `text/html`; renders brand header, build badge, nav skeleton |
| `/config.js` | SERVES BUT STALE | 200, byte-identical to the checked-in Amplify default (see below) |
| `/api/health` through the site | BROKEN (404) | No rewrite/proxy to the HttpApi — by repo design the UI must call the HttpApi URL directly |
| Protected route without token | UNTESTABLE via site | `POST /api/builds` 404s before any auth layer runs; direct-API 401 check deferred until the API URL is wired |
| Deployed frontend version | STALE | Shell links only `./styles.css` — no `./fonts/fonts.css`, no `./vendor/phosphor.css`, old meta description: predates the T12 design-system build |

## The confirmed known issue (precise)

`/config.js` serves this, verbatim:

```js
// Generated at Amplify build time from $API_URL (deploy default: localhost).
window.PROCESSPATCH_API = window.PROCESSPATCH_API || "http://localhost:8000";
```

`$API_URL` was never injected at build time — this is the repo default, not a
generated file. Exact judge-visible failure: clicking Compile Amendment makes
the browser fetch `http://localhost:8000/demo/canonical?...`, which fails
with `ERR_CONNECTION_REFUSED` (a judge's laptop runs no API), and the UI
renders "Request failed: Failed to fetch" plus the hint "Start the API with
`python -m services.api.server`" — a local-dev instruction that is wrong on a
deployed site and will read as a broken demo.

Root causes, both verified: (1) **no buildspec in the repo consumes
`$API_URL`** — there is no `amplify.yml` or buildspec anywhere, so nothing
could have generated `config.js` even if the variable were set
(`docs/architecture.md` says "API_URL injected at build"; the wiring was
never implemented); (2) `/api/*` 404s because Amplify serves static
`frontend/` only — the fix is pointing the UI at the HttpApi, not proxying.

## Fix runbook (human; console + CLI, no code changes needed for steps 0–1, 3–5)

**Step 0 — get the real API URL** from the stack that `infra/deploy.sh`
already queries:

```bash
aws cloudformation describe-stacks --stack-name <stack> \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text
```

(Outputs tab of the CloudFormation console shows the same value; see the
Outputs docs below. This mirrors `infradeploy.sh` lines 16–25.)

**Step 1 — set `API_URL` on the Amplify app.** Amplify console → Hosting →
Environment variables → Manage variables → Variable `API_URL`, Value
`<ApiUrl from step 0>` → Save. Console path per AWS docs (Hosting →
Environment variables → Manage variables; variables apply across branches
unless overridden).

**Step 2 — wire `$API_URL` into `config.js` at build time.** Nothing in the
repo does this today, so pick one: (a) Amplify console → Hosting → Build
settings → Edit build spec, add a pre-build command that generates the file,
e.g. `printf 'window.PROCESSPATCH_API = "%s";\n' "$API_URL" >
frontend/config.js` (the app reads `window.PROCESSPATCH_API` at boot, so
this format is compatible); or (b) ask Buffy to add repo-side buildspec
wiring (infra-adjacent, backend-owned — logged as a follow-up, not done
here).

**Step 3 — redeploy so the new build picks up the variable.** App overview
page → branch → deployment → **Redeploy this version** (env vars only take
effect on a fresh build).

**Step 4 — confirm CORS allows the Amplify origin.** API Gateway console →
the HTTP API → CORS: `allowOrigins` must include
`https://main.d1bq8os9dwj0d.amplifyapp.com`. The repo design already intends
this (`infra/template.yaml` sets `AllowOrigins: [FrontendOrigin]` and
`deploy.sh` redeploys with `FrontendOrigin=$BRANCH_URL`) — verify it stuck;
if not, fix via console or `aws apigatewayv2 update-api --api-id <id>
--cors-configuration AllowOrigins=https://main.d1bq8os9dwj0d.amplifyapp.com`.
Cognito callback URLs are wired the same way (`CallbackURLs` includes
`${FrontendOrigin}/`), so sign-in redirect breaks identically if this is
wrong — check it in the same pass.

**Step 5 — re-audit live.** `curl /config.js` must show the real URL, not
localhost; a browser session must show zero `localhost:8000` calls in the
network tab; an unauthenticated `POST` to a protected route on the real API
URL must return 401 (authorizer working), not 404 or CORS errors.

## AWS docs cited

- Amplify environment variables (console path, branch overrides):
  https://docs.aws.amazon.com/amplify/latest/userguide/setting-env-vars.html
- Redeploy pattern (overview → branch → deployment → Redeploy this version):
  https://docs.aws.amazon.com/amplify/latest/userguide/custom-build-instance.html
- HTTP API CORS (`allowOrigins`, console + CLI):
  https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-cors.html
- CloudFormation Outputs (Outputs tab / `describe-stacks`):
  https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html

## Judge-readiness checklist (after the fix)

1. `/config.js` serves the real API URL; no `localhost:8000` anywhere in it.
2. Compile Amendment in a clean browser completes without console errors.
3. Unauthenticated protected call returns 401, never 404 or a CORS failure.
4. Sign-in redirect returns to the Amplify domain (Cognito callbacks wired).
5. `scripts/judge_demo.py` still prints ALL 6 BEATS VERIFIED against local.
