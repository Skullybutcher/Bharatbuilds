# agents.md — Multi-Agent Coordination Protocol

This repo is worked on by **three AI agents** (plus the human owner, Aman, who
is the only one who commits/pushes). This file prevents conflicts and keeps a
durable record of who did what.

**Rule zero: read this file before starting any task. Append a claim before
touching a file. Append a log entry when you stop.**

---

## 1. Agent roster

| Agent | Capabilities | Default ownership |
|---|---|---|
| **Buffy** (Freebuff/Codebuff) | Full repo, runs tests/verify/terminal, no web search | `services/**`, `tests/**`, `scripts/**`, `infra/**`, `benchmark/**`, root config |
| **opencode** | Code edits + **web search** (docs, design references) | `frontend/**` (while a UI task is open) |
| **IBM Bob** | Code edits + analysis, **no web access** | Read-only reviews, new standalone test files, docs, CHANGELOG |

The human (Aman) reviews all work and is the only committer. Agents never
commit, push, or deploy.

## 2. Conflict prevention (the important part)

- **One file, one agent, at a time.** Before editing, add a *claim* to the
  Task Board (section 4): your name, task id, and the exact paths you will
  touch. If another agent has an open claim on those paths, **stop and pick a
  different task** (or wait until the claim is released).
- **Never edit outside your claimed paths**, even for "tiny fixes" — log the
  need as a note on the task board instead.
- Cross-cutting files (`README.md`, `agents.md`): factual log/appending is
  always allowed; structural edits need a claim.
- Keep tasks **small**: claim → do → verify → log → release. Long-lived claims
  are how conflicts happen.
- If you must break these rules (emergency), log it loudly in section 6 with
  `!!` prefix and tell the human.

## 3. Definition of Done (every task)

1. All claimed changes complete; no drive-by edits elsewhere.
2. `python scripts/verify.py` → PASS and `python -m pytest tests -q` → all
   green (agents without terminal access: state this in the log and request
   the human/Buffy to run verification).
3. `scripts/validate_infra.py` → PASS (only if `infra/**` was touched).
4. Log entry written (section 6) and claim released (section 4).
5. A one-line commit message proposal included in the log entry.

## 4. Task board

Format: `T<id> | <title> | owner | paths | state (OPEN / CLAIMED / DONE / BLOCKED)`

| ID | Title | Owner | Paths | State |
|---|---|---|---|---|
| T1 | Complete UI upgrade (design-system pass, anti-slop rules — prompt provided separately) | **opencode** | `frontend/**` | DONE |
| T2 | Docs consistency audit (stale counts, broken cross-refs after v0.3 auth/traces/workspaces changes) | **IBM Bob** | `docs/**`, `README.md`, `docs/consistency-audit.md` (new) | DONE |
| T3 | New unit tests for `services/normalizer/normalizer.py` interval + delta edge cases | **IBM Bob** | `tests/unit/test_normalizer_ext.py` (new file only) | DONE |
| T4 | `CHANGELOG.md` for v0.3.0 features (auth, traces, language, workspaces, judge demo) | **IBM Bob** | `CHANGELOG.md` (new file only) | DONE |
| T5 | Backend standing by: fixes/reviews requested by T1–T4; no frontend edits | **Buffy** | everything except `frontend/**` | STANDBY |
| T6 | Repair GitHub Actions AWS OIDC deployment authentication | **GitHub Copilot** | `.github/workflows/ci.yml`, `docs/aws-setup.md`, `agents.md` | DONE |

Backlog (unassigned): Cognito MFA toggle, trace CSV bulk ingestion, benchmark
v0.4 families, SFN ASL tests for auth-related resume gates.

**T1 special rule:** while T1 is CLAIMED, Buffy and Bob must not edit
`frontend/**`. Buffy may *read* it for review. The UI↔API contract must not
change (see T1 notes below); if opencode needs a backend change, it logs a
`NEEDS_BACKEND` note and stops that part — Buffy implements it.

## 5. Facts every agent needs (do not re-derive)

- Repo: ProcessPatch — operational rule compiler; docs in `docs/` (16 notes);
  session history in `ProcessPatch_Session_Context.md` (repo root, never committed).
- Verification is credential-free: `python scripts/verify.py` (178 assertions),
  `pytest tests` (52), `python scripts/validate_infra.py`.
- Benchmark is **v0.3.0, 31 cases** (22 auto-repaired / 3 no-op / 4 escalated /
  2 unsupported). Never hardcode metric counts; compute them.
- Auth: Cognito groups `pp-admins` (activate) / `pp-reviewers` (review) —
  `services/api/authz.py` stamps verified identity; `docs/auth.md`.
- Doctrine: ambiguity → NEEDS_REVIEW; no witness without verified pipeline;
  never "compliance guaranteed"; traces are evidence only (`docs/traces.md`).
- The human commits. Propose commit messages; never run git commit/push.

## 6. Activity log (append-only, newest first)

Format: `- YYYY-MM-DD HH:MM | agent | task | files touched | result | notes/commit-msg-proposal`

- 2026-09-19 18:00 | GitHub Copilot | T6 | `.github/workflows/ci.yml`, `docs/aws-setup.md`, AWS IAM OIDC provider | DONE: registered `https://token.actions.githubusercontent.com` with audience `sts.amazonaws.com`; verified role `GitHubActionsProcessPatchDeploy` trust for `repo:Skullybutcher/Bharatbuilds:ref:refs/heads/main`; upgraded credentials action to v5; infra validation, 178/178 verify, 70/70 pytest, and workflow YAML parse PASS | commit: "Fix GitHub Actions AWS OIDC deployment auth"; human should rerun the failed workflow

- 2026-09-19 14:10 | Buffy | T5 (NEEDS_BUFFY closure) | `scripts/smoke.ps1` | DONE: mirrored bash smoke auth checks (auth-config fetch, 401 checks on /builds + guardrails via StatusCode helper); PowerShell Parser::ParseFile → parse OK; verify 178/178 PASS after edit | commit: "Smoke (ps1): assert auth-gated routes like bash smoke" — resolves the NEEDS_BUFFY note from T2 review prep
- 2026-09-19 14:00 | Buffy | integration review of T1–T4 | read-only across frontend/**, tests/**, docs/**, CHANGELOG.md | VERDICT: all four tasks verified independently — 178/178 verify, 70/70 pytest (Bob's 18 included), INFRA PASS, judge_demo 6/6 beats, app.js syntax OK, zero banned patterns in styles.css, all 10 tabs + contract functions + esc() (48 uses) intact, Bob's doc numbers spot-checked correct (31-scenario, 16-case, 178, auth cross-refs) | both agents' DONE claims confirmed; tree ready for human to commit
- 2026-09-19 13:30 | opencode | T1 UI upgrade | `frontend/index.html` (shell rewrite) + `frontend/styles.css` (new, design tokens) + `frontend/lib/app.js` (new, all 29 contract functions ported) + `frontend/DESIGN.md` (new) | DONE: verify 178/178 PASS, pytest 70/70, judge_demo ALL 6 BEATS VERIFIED; all 10 tabs + 6-step Judge bar + API paths/bodies + esc() + trust badges + VALIDATED_WITHIN_TESTED_MODEL preserved; no NEEDS_BACKEND gaps | proposed commit: "UI upgrade: design-system pass on frontend (tokens, Stripe-density layout, prune slop, split styles/app.js)"
- 2026-09-19 09:30 | IBM Bob | T2 | `docs/consistency-audit.md` (new); `docs/submission.md`, `docs/benchmark.md`, `docs/deployment-runbook.md`, `docs/architecture.md`, `docs/governance.md`, `docs/trust-boundary.md`, `README.md` (mechanical fixes) | Audit: 11 findings (5 stale counts, 6 missing cross-refs). Mechanical fixes applied: "26-scenario"→"31-scenario" (submission.md); "13-case"→"16-case" eval split + "20"→"22" auto-repaired (benchmark.md); "176/176"→"178/178" (deployment-runbook.md); "176"→"178" (README.md); auth/traces/workspaces cross-refs added to architecture.md, governance.md, trust-boundary.md. Prose-only changes (demo-script.md flow extension) proposed in consistency-audit.md, not auto-applied. | commit: "Docs consistency pass for v0.3.0"
- 2026-09-19 09:00 | IBM Bob | T3 | `tests/unit/test_normalizer_ext.py` (new) | 18 tests, 5 coverage areas: same-field-only delta, interval satisfiability, IN/NOT_IN eval, validate_rule rejections, provenance-only delta. Ran `pytest tests/unit/test_normalizer_ext.py` → 18/18 PASS; full `pytest tests` → 70/70 PASS (52 prior + 18 new). No existing files touched. | commit: "Add normalizer/delta edge-case tests"
- 2026-09-19 08:30 | IBM Bob | T4 | `CHANGELOG.md` (new) | Keep-a-Changelog format; v0.3.0 (auth, traces, language, workspaces, judge demo), v0.2.0 (4 bullets from git log), v0.1.0 (3 bullets). All claims verified against benchmark_runs/BENCH-v030-REF metrics.json + git log. No existing files touched. | commit: "Add CHANGELOG; document v0.3.0"
- 2026-09-19 07:30 | Buffy | setup | `agents.md` | created coordination protocol | task board seeded (T1–T5)
- 2026-09-19 05:00–07:00 | Buffy | (pre-agents.md) auth + traces + language v0.3.0 + workspaces + judge demo | see git status; 178/178 verify, 52/52 pytest, INFRA PASS, bench v0.3.0 all green | 5 commit messages proposed to human; no commits made by agents
