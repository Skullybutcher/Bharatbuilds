# Auth — Cognito, hosted UI (PKCE), group-gated HITL actions

Closes the deferred "Cognito/JWT auth" item. Doctrine unchanged: **humans
approve activation** — auth just proves *which* human, and gates who may do it.
Model output is still never auto-accepted; verified identities are stamped into
the audit trail, so approvals bind the exact human who made them.

## Model

- **Cognito UserPool** (`AWS::Cognito::UserPool`), email usernames, invite-only
  (no self-signup — an admin creates users and assigns groups).
- **Two groups**:
  - `pp-admins` — approve candidates + activate procedure versions (Gates 2/3).
  - `pp-reviewers` — rule review (Gate 1) + patch decisions (Gate 2).
  - Users in neither group are **read-only**.
- **Public client** (`WebClient`): no secret, PKCE only, hosted-UI login,
  `code` flow with `openid email` scopes. Access/id tokens are 8 hours.
- **Enforcement is two-layered**:
  1. HttpApi **Cognito JWT authorizer** on every route (API Gateway rejects
     bad tokens before Lambda), except explicit `NO_AUTH` routes:
     `GET /`, `GET /health`, `GET /demo/canonical`, `GET /auth/config`.
  2. Inside `ApiFn`/local server, `services/api/authz.py` re-checks claims and
     **stamps the verified identity into the request body** — a caller can no
     longer spoof `reviewer`/`role`, which previously were trusted as-is.

## Roles → routes (enforced in `services/api/authz.py`)

| Action | pp-reviewers | pp-admins | read-only |
|---|---|---|---|
| Read anything (builds, impact, witnesses…) | ✓ | ✓ | ✓ |
| Create builds / execute / replay / resume | ✓ | ✓ | ✗ |
| Gate-1 rule accept/edit/reject/escalate | ✓ | ✓ | ✗ |
| Patch approve / reject / request-revision | ✓ | ✓ | ✗ |
| Activate procedure version (Gate 3) | ✗ | ✓ | ✗ |

`POST /builds/{id}/resume` with `gate: activation` is admin-only (same Gate 3).

## Deployed demo login

The pool is invite-only with no self-signup. The deployed demo has an admin
login for the full approval path and a separate reviewer login for public
evaluation. `demo-admin@processpatch.demo` is the
`AWS::Cognito::UserPoolUser` declared in `infra/template.yaml` (`DemoAdmin`,
confirmation SUPPRESS), attached to `pp-admins` (`DemoAdminMembership`).
CloudFormation cannot set a password, so `infra/deploy.sh` generates a random
one, sets it `--permanent`, and prints a `DEMO LOGIN` block exactly once —
never written to disk or git, so a lost password means re-running that step
(the script prints the manual `admin-set-user-password` fallback, and a
`NOTE` when the user is missing on pre-existing stacks). As a `pp-admins`
member the demo login unlocks Gates 2/3 (patch approve + activation) on top
of everything `pp-reviewers` can do; there is no reviewer demo account, so
Gate-1 review on the deployed demo goes through the same admin login. Never
commit, screenshot, or stream the password — rotate it with
`admin-set-user-password` after the demo window.

The public reviewer account is `judge@processpatch.demo` with password
`JudgePass2026!`. It is attached only to `pp-reviewers`, so judges can create
and review builds but cannot activate procedure versions or administer
Cognito. It is a shared demo credential and must not be used with real data.

## Identity flow (cloud)

1. UI redirects to the Cognito hosted UI (PKCE verifier in sessionStorage).
2. Cognito redirects back with `?code=...`; UI exchanges it at `/oauth2/token`
   and stores id/access tokens in `localStorage` (`pp_tokens`).
3. Every API call sends `Authorization: Bearer <access token>`.
4. API Gateway verifies the JWT; `ApiFn` reads verified claims from
   `event.requestContext.authorizer.jwt.claims` (no re-verification needed).
5. `authz.authorize()` maps `cognito:groups` → role, enforces the route
   policy, and stamps `reviewer`/`role` into the body before routing.

## Local development

Auth is **off** by default (`PROCESSPATCH_AUTH=off`): credential-free, legacy
behavior, UI shows a demo reviewer. The UI calls `GET /auth/config` at startup
to learn whether auth is enabled (public endpoint, non-secret values only).

To exercise enforcement locally without Cognito:

```bash
PROCESSPATCH_AUTH=hs256-test PP_DEV_HS256_SECRET=dev-secret \
  python -m services.api.server 8000
# tokens must be HS256 JWTs signed with PP_DEV_HS256_SECRET
```

`hs256-test` is a **test-only** mode (unit tests + the live smoke above use
it); never enable it in production. Cognito RS256 tokens are verified against
the pool JWKS when running the real thing outside API Gateway.

## Deploy wiring (handled by `infra/deploy.sh|.ps1`)

1. First `sam deploy` creates the pool, client, hosted-UI domain, and Amplify.
2. Scripts read `UserPoolId` / `UserPoolClientId` / `AuthDomain` /
   `AmplifyAppId` from stack outputs and **redeploy once** with
   `PP_USER_POOL_ID`, `PP_CLIENT_ID`, `PP_AUTH_DOMAIN` set on `ApiFn` and
   `FrontendOrigin` locked to the Amplify branch URL (never `*`).
3. `GET /auth/config` then serves the client id + hosted-UI domain to the UI.

First admin bootstrap (invite-only; run after deploy):

```bash
aws cognito-idp admin-create-user --user-pool-id <pool> --username <email> \
  --user-attributes Name=email,Value=<email> Name=email_verified,Value=true \
  --message-action SUPPRESS --region <region>
aws cognito-idp admin-add-user-to-group --user-pool-id <pool> \
  --group-name pp-admins --username <email> --region <region>
# the user sets a password via the "forgot password" flow at the hosted UI
```

## Operations

- Callback URLs: Amplify branch URL + `http://localhost:8000/` (dev). Add
  more in `WebClient.CallbackURLs` if you branch (e.g., PR preview URLs).
- Hosted-UI domain prefix is `processpatch-<env>-<account-id>` (globally
  unique; change in `UserPoolDomain` if it collides).
- The HttpApi CORS `FrontendOrigin` must equal the Amplify origin in
  production — the deploy scripts set it automatically from stack outputs.
- Audit entries now carry verified emails (Gate 1/2/3), so the approval trail
  is attributable end to end.
