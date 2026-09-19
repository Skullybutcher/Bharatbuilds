# Production readiness review

## Verdict

The repository is a working, tested demonstration, but is **not ready for a public production release**. This review hardens confirmed defects and improves the existing UI. Passing deterministic tests does not establish concurrency safety, tenant isolation, or cloud operational readiness.

Scope: API entry points, authentication and authorization, persistence, governance and registry flows, extraction trust boundaries, frontend shell and interaction code, infrastructure and CI configuration, and the existing unit/integration/journey/benchmark checks. This was a risk-focused repository review, not a line-by-line certification or penetration test. No cloud resources were changed, no credentials were used, and nothing was committed or deployed.

## Implemented

- OAuth authorization now sends an S256 PKCE challenge and verifies callback state before exchanging a code. Token-exchange errors are visible.
- Malformed JWTs return unauthorized responses; invalid expiration values and unsupported Cognito token uses are rejected. Gateway group claims support array and serialized-array forms.
- Model-extracted rules cannot bypass human review by submitting `auto_accept: true`.
- Both API surfaces reject malformed/non-object JSON and bodies above 1 MiB. Shared Lambda action dispatch maps persistence outages to a generic 503 response.
- Build persistence errors propagate instead of returning false success. Build reads use persisted state rather than stale process memory; history no longer combines duplicate cached and persisted records.
- DynamoDB collection queries traverse every page with consistent reads. File replacement is atomic and preserves the previous file if replacement fails.
- Infrastructure declares unauthenticated preflight and `/health` routes.
- The UI fixes desktop editor overflow and mobile layout, moves connection details out of the primary controls, labels file/text inputs, makes recent activity keyboard accessible, corrects validation labels, preserves theme on initial paint, and fixes palette focus, empty-result navigation and Escape/reopen behavior.

## Release blockers still open

| Priority | Finding and evidence | Required completion |
|---|---|---|
| P0 | `services/storage.py` rewrites collections with delete/put batches; registry and governance callers use read-modify-write. Concurrent Lambda requests can overwrite one another, and a failed batch can leave partial state. Atomic local file replacement does not solve concurrent updates. | Introduce per-record persistence, conditional version checks and transactions for governance transitions; migrate stored data and test concurrent writers and injected partial failures. |
| P0 | `services/registry/store.py` stores every build in one dictionary, serialized into one DynamoDB META item. Growth can exceed DynamoDB's item-size limit. | Store builds individually; put large artifacts in versioned object storage, with integrity hashes and a tested migration. |
| P0 for multiple organizations | `services/api/authz.py` authorizes global groups, not workspace membership. List/read actions are global. | Define the deployment's trust boundary. For multiple organizations, enforce workspace ownership on every resource read/write and test cross-workspace denial. |
| P1 | Public `GET /demo/canonical` performs compilation, writes reviews and persists a build. Other review creation paths still swallow exceptions. | Isolate or disable demo mutations in production, require authenticated writes, and make review initialization fail closed with explicit recovery behavior. |
| P1 | Several frontend renderers interpolate identifiers into inline JavaScript handlers. HTML escaping alone does not safely quote JavaScript string contexts. Tokens remain in localStorage. | Replace dynamic inline handlers with event listeners and data attributes; test hostile identifiers, enforce a compatible CSP, and define session expiry/refresh and token storage policy. Recent activity handlers were migrated in this pass. |
| P1 | The custom RS256 verifier caches signing keys and does not refresh on an unknown key. Real hosted login and cloud callback flows were not exercised. | Use a maintained JWT implementation or thoroughly test key rotation and claim validation. Complete hosted login, refresh/expiry, reviewer/admin denial tests, and all cloud gates in staging. |
| P1 | UI async actions can overwrite a newer tab after delayed responses; some mutation failures still discard the current form. | Introduce request cancellation/navigation guards and persistent form feedback; test delayed and failed responses. |
| P1 | Infra includes backups and dashboards but production restore, retention, load limits and alert delivery have not been demonstrated. CI pushes to main trigger deployment. | Exercise restore and rollback, configure operational ownership and alarms, protect production deployment with environment gates, and load-test realistic artifact sizes. |

The storage changes above require a deliberate data migration. They should not be replaced by a process-local lock: independent Lambda workers do not share locks.

## Verification

- Full Python suite: **118 passed** (94 existing plus 24 new regression cases).
- Deterministic verification: **178/178 passed**.
- Infrastructure validation: **PASS**.
- JavaScript syntax validation: **PASS**.
- Browser: canonical compile, all ten tabs at a 390px viewport without visible error panels or page overflow; desktop editor fits at 1264px; palette keyboard focus, Tab containment, Escape and reopening checked.
- These browser checks are smoke tests, not a complete accessibility or visual regression suite. Live Cognito login, cloud deployment, concurrent writes, backup restoration and load testing remain unverified.

Python was run using the bundled runtime because this workstation's default `python` command points at an unavailable Store alias. Test dependencies were installed into that runtime.

## References

- [AWS HTTP API CORS and unauthenticated OPTIONS routes](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-cors.html)
- [AWS DynamoDB Query pagination](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_Query.html)

Proposed commit message: `Harden auth, persistence and request validation; improve responsive UI and document release blockers`
