# HANDOFF — ProcessPatch (Bharatbuilds), hackathon build day 2

**Rule zero for every agent working here: read `agents.md` first.** It is the
canonical task board + engineering log (newest entries at the bottom of the
log section). Claim a row before working; log an entry + commit-message
proposal when done; never commit yourself — the human owner commits.

**Owner is away. This file is the source of truth until they are back.**

---

## 1. Where things stand

- **Live stack (AWS ap-south-1):**
  - UI: https://main.d1bq8os9dwj0d.amplifyapp.com/
  - API: https://ssv1hifpvl.execute-api.ap-south-1.amazonaws.com/prod
  - Demo user: `demo-admin@processpatch.demo` (password is set by the owner
    via Cognito `admin-set-user-password` — ask them, do NOT commit secrets)
- **The core claim is PROVEN live:** full 3-gate cloud E2E green —
  compile → rule review → patch approval (candidate minted) → activation →
  `PATCH_ACTIVE`, SFN execution SUCCEEDED, governance bundle 2 approvals,
  coverage verified. Rehearsal script `scripts/demo_run.py` has itself
  activated a build end-to-end on the live stack.
- **Test posture:** `pytest 194/194`, `scripts/verify.py 178/178`,
  `scripts/validate_infra.py` PASS. Keep all three green before any commit.

## 2. JUST finished — committed locally, NOT pushed. Do this first

**Local main is 36 commits ahead of origin.** All work through T64 is
committed (latest: `27ec3a0 T63+T64`), including:

- **T58/T60/T62 — D1 storage:** per-record writes + optimistic concurrency;
  gate claims, approvals, audit ledger, procedure/candidate/patch-review
  records all race-safe; bulk saves are diffs, not wipe-and-rewrite.
- **T61 — evidence viewer** (frontend): human-readable governance bundle +
  print path in the console.
- **T63 — workspace isolation:** `ws-*` Cognito group membership, scoped
  lists, per-build subtree gate on BOTH API surfaces, audited denials;
  zero-setup compat (no ws-groups ⇒ `default`).
- **T64 — re-verify:** `POST /builds/{id}/reverify` re-runs the deterministic
  pipeline from the accepted Rule IR, names tampering/compiler drift,
  checks the Gate-2 signed hashes. Audited REVERIFY_PASS/FAIL.
- Plus T55-T57 (flagged purge, live demo driver, honest env flags) and
  `HANDOFF.md` (this file — stage/commit it if not yet committed).

**Step 1: `git push` (owner), CI must go GREEN.** Copilot may have pushed
concurrently — if rejected: `git fetch && git rebase FETCH_HEAD`, re-run
tests, push again. Never force-push.

**Step 2: backend deploy** via the GitHub Actions SAM workflow (owner
generally triggers; ask before deploying — it touches the live stack).
Amplify deploys the frontend from the same push automatically.

**Step 3: live verification (section 3, N2)** — nothing after T52 has been
exercised against real AWS yet.

## 3. Immediately next (in order)

| # | Task | Who | Notes |
|---|---|---|---|
| N1 | Push the two commits, wait for CI green, deploy backend | human owner | destructive-ish: ask owner first |
| N2 | **Live verification of T63+T64** against the deployed API: (a) `POST /builds/{id}/reverify` on the activated build → expect `verified:true` + REVERIFY_PASS audit; (b) craft a token WITHOUT `ws-default` → lists scoped, build GET denied+audited; (c) `scripts/demo_run.py` still green end-to-end | any agent (claim in agents.md) | uses the smoke/demo drivers; read `scripts/cloud_smoke.sh` for the auth mechanics |
| N3 | `python scripts/demo_cleanup.py <api> <email> <pw> --apply` to archive the debug builds (keeps activated ones) | human/agent | dry-run default; `--purge` stays refused unless `DemoPurge=1` — that is intended |
| N4 | **T65 (frontend):** workspace switcher + "Re-verify" button next to "Download governance bundle" + render reverify result as a verdict card | opencode | endpoints exist; render only real responses |
| N5 | **Docs sweep:** README + `docs/architecture.md` + `docs/submission.md` numbers/sections for everything since T60 (D1 storage atomics, T63 isolation, T64 reverify, audit timeline) | opencode or human | keep the "verify these numbers" block honest |

## 4. Bigger build items (breadth/depth — pick if time remains)

| Item | Value | Size |
|---|---|---|
| **B1: second domain end-to-end** (healthcare or procurement — proposals in `docs/`, search "domain") | proves the engine generalizes: "same pipeline, three domains" is the strongest breadth claim at judging | large — compiler demo content + tests; do NOT rush it |
| **Scheduled re-validation** (EventBridge rule → Lambda that re-runs reverify on ACTIVE builds; drift alarm) | "CI for real-world procedures" literally becomes continuous | medium |
| **Gate notifications** (email when a gate arms / approval requested) | ops credibility; demo line "the right human gets pinged" | small-medium (SES) |
| **T63 follow-up A (owner decision):** workspace-aware idempotency — identical compiles across workspaces currently share one record (reads then deny non-members; leak-free but confusing) | multi-tenant correctness polish | medium, needs design decision |
| **T63 follow-up B:** trace-id hash excludes workspace — same content twice = duplicate invisible to 2nd writer | correctness polish | small |
| **Architecture diagram** for `docs/` (the 40-state ASL + 3 gates + surfaces) | judges love it; Bob (docs) is out of credits | small |
| **Audit-timeline enrichment**: bundle export / reverify events already land in `audit.json` — make sure T59's timeline renders the new event kinds (REVERIFY_*, ACCESS_DENIED) with sensible tones | continuity polish | small |

## 5. Demo-day runbook (already exists — follow it)

- **Presenter script:** `docs/demo-script.md` (timed 4-minute run, Judge Mode
  order, exact clicks + SAY lines + fallbacks).
- **Fresh demo state:** `python scripts/demo_run.py <api> <email> <pw>` —
  rewrites the canonical policy to an uncompiled CGPA threshold and drives
  compile → Gate 2 → Gate 3 → `PATCH_ACTIVE` with evidence. This IS the
  rehearsal path; it has succeeded live.
- **Evidence beats in the UI:** audit timeline (T59), evidence viewer (T61),
  bundle download (sha256-sealed), reverify (T64 — after deploy).
- **Cleanup:** `scripts/demo_cleanup.py --apply` (archive, never delete).

## 6. Quirks & guardrails (read before touching anything)

- **The owner never lets agents run `git commit`/`git push`** — agents stage
  and propose messages; the human commits. This has caused friction before;
  keep respecting it.
- **Copilot teammate pushes concurrently** — if your push is rejected:
  `git fetch`, `git rebase FETCH_HEAD` (fix conflicts), re-run tests, push.
  No force-push, ever.
- **Commits are message-only coordination:** shared files are being edited by
  multiple agents; commit promptly after green to shrink overlap windows.
- Backend has TWO surfaces (local stdlib `services/api/server.py` and Lambda
  `services/aws_handlers.py`) — every route/behavior change goes in BOTH, or
  better in the shared `actions.py`/`authz.py` they both call.
- Env flags parse strictly (`services/aws_handlers.py `_flag()``): the string
  `'0'` is OFF. `PP_DEMO_PURGE` (deploy param `DemoPurge`) gates the only hard
  delete; `/archive` is the supported retirement path.
- Storage is per-record with optimistic concurrency (T58/T60/T62): new
  collection writers MUST use `put_item(..., expect=version)` where a lost
  update matters; bulk `_save` is a diff now but is still last-writer-wins for
  full-state semantics — prefer per-record.
- Step Functions gate payloads are contract-tested against the ASL itself
  (`tests/unit/test_asl_gate_contracts.py`) — if you touch
  `infra/statemachine.asl.json` or gate outputs, those tests will tell you.
- Demo data lives in DynamoDB single-table (`processpatch-registry`);
  procedure versions are a GLOBAL shared registry by design (T63 brief §6).

## 7. Reference commands

```bash
python -m pytest -q                 # 194 expected
python scripts/verify.py            # 178/178 expected
python scripts/validate_infra.py    # infra checks
python scripts/demo_run.py <api> <email> <pw>          # live E2E demo
python scripts/demo_cleanup.py <api> <email> <pw>      # dry-run plan
python scripts/demo_cleanup.py <api> <email> <pw> --apply
bash scripts/cloud_smoke.sh <api> <email> <pw>         # 3-gate cloud E2E
make app                            # one-command local app on :8080
```

## 8. If something breaks on the live stack

1. `describe_execution` now surfaces SFN error/cause via
   `GET /executions/{arn}` — failed executions name their killer; use it.
2. Lambda logs: AUTHDEBUG / RESUMEDEBUG flags exist as deploy parameters
   (`AuthDebug`), default 0 — flipping them needs a deploy, ask the owner.
3. Archived builds are hidden but resumable: `GET /builds?include_archived=1`.
4. Nothing is ever deleted except the flagged purge; `BUILD_ARCHIVED`,
   `ACCESS_DENIED`, `REVERIFY_*` are all in the audit ledger.
