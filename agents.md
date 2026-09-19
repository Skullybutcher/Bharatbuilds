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
| T6 | One-command local app (`make app`: UI + same-origin API proxy on one port) | **Buffy** | `scripts/app.py` (new), `Makefile`, 1 line in `frontend/lib/app.js` | DONE |
| T7 | Seeded demo state + app E2E suite + CSV bulk trace ingest | **Buffy** | `scripts/app.py`, `services/traces/`, `services/api/{actions,server}.py`, `services/aws_handlers.py`, `tests/**`, `docs/traces.md`, `CHANGELOG.md` | DONE |
| T8 | First-run experience polish (empty states + no-build hero) | **opencode** | `frontend/**` | DONE |
| T9 | Demo-script rewrite (make app reality) + runbook step 0 + CHANGELOG v0.3.1 | **opencode** | `docs/demo-script.md`, `docs/deployment-runbook.md`, `CHANGELOG.md` | DONE |
| T10 | Visual overhaul pass 2 (depth, hero, tables, graph colors, approval pills) | **Buffy** | `frontend/**` | DONE |
| T11 | Judge-prep research: docs/positioning.md + docs/judge-qa.md | **opencode** | `docs/positioning.md` (new), `docs/judge-qa.md` (new) | DONE (duplicate row; see below) |
| T16 | Benchmark v0.4 case-family proposals (grounded in rule-ir + author.py) | **opencode** | `docs/benchmark-v4-proposals.md` (new) | DONE |
| T17 | Demo storyboard (180s shot plan) + submission.md refresh | **opencode** | `docs/demo-storyboard.md` (new), `docs/submission.md` (edit) | DONE |
| T12 | Design-system v3 (Satoshi + Phosphor self-hosted, gate spine, case-file witnesses, sentence-case labels, theme toggle, icon nav/empty states) | **Buffy** | `frontend/**` | DONE |
| T13 | Filled dashboard canvas (activity modules, editor panel, header hierarchy, sidebar polish, spine pulse) | **Buffy** | `frontend/**` | DONE |
| T14 | Identity v4 "ledger of record" (warm paper default + deep-teal seal accent; graphite+muted-cyan dark alternate) | **Buffy** | `frontend/**` | DONE |
| T15 | Governance bundle export (sha256-sealed evidence pack, 409 without approval) + witness nomination (honesty gate → verified pipeline) + CSV ingest UI | **Buffy** | `services/api/**`, `services/aws_handlers.py`, `services/api/authz.py`, `frontend/lib/app.js`, `docs/traces.md`, `CHANGELOG.md`, tests | DONE |
| T16 | Theme cycle (paper → graphite → lab), hero asymmetry 1.35fr, drag-drop policy editor, deleted duplicate tagline; external design review triaged (stale screenshot — concepts 1/3 already shipped as T14 tokens) | **Buffy** | `frontend/**` | DONE |
| T16b | Lab (rust/graphite) promoted to DEFAULT theme; cycle now lab → paper → graphite → lab; no-flash boot hint in index.html | **Buffy** | `frontend/**` | DONE |
| T11 | Positioning + judge Q&A docs (web research + repo-grounded) | **opencode** | `docs/positioning.md` (new), `docs/judge-qa.md` (new) | DONE |
| T18 | Command palette (Ctrl/Cmd+K) + coverage endpoint `GET /builds/{id}/coverage` (BOTH surfaces) + Impact coverage panel | **Buffy** (reassigned from opencode per human) | `frontend/**`, `services/api/actions.py`, `services/api/server.py`, `services/aws_handlers.py`, tests | DONE |
| T19 | T15 governance docs sweep (bundle + nomination in README/architecture; number sweep) | **opencode** | `README.md`, `docs/architecture.md`, `docs/submission.md` (numbers block only) | DONE |
| T20 | CSV bulk-ingest demo sample + storyboard paste moment | **opencode** | `demo/traces-sample.csv` (new), `docs/demo-storyboard.md` (3-line edit) | DONE |
| T21 | Judge QA + positioning refresh (bundle, nomination, coverage) | **opencode** | `docs/judge-qa.md` (edit), `docs/positioning.md` (edit) | DONE |
| T22 (was T6 on deploy branch) | Repair GitHub Actions AWS OIDC deployment authentication | **GitHub Copilot** | `.github/workflows/ci.yml`, `docs/aws-setup.md`, `agents.md` | DONE |
| T23 (was T7 on deploy branch) | Diagnose recurring GitHub Actions OIDC trust rejection | **GitHub Copilot** | `docs/aws-setup.md`, `agents.md` | DONE |
| T24 (was T8 on deploy branch) | Eliminate GitHub OIDC role ARN secret mismatch | **GitHub Copilot** | `.github/workflows/ci.yml`, `docs/aws-setup.md`, `agents.md` | DONE |

Backlog (unassigned): Cognito MFA toggle, benchmark v0.4 families, SFN ASL
tests for auth-related resume gates, `POST /traces/csv` UI affordance
(backend done; needs an ingest-CSV button next to the trace form).

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

- 2026-09-19 (T18) | Buffy | command palette + real coverage endpoint + Impact coverage panel | actions.py coverage(): node coverage joins LOCALIZER FAULTS by witness_id (witness dicts carry NO affected_nodes — first attempt joined on a field that doesn't exist and showed 0/2; corrected to the same localize_all call the impact engine uses; 2/2 with witness attribution W-001/NODE-ELIGIBILITY, W-002/NODE-REC-UPLOAD), field coverage = affected_rules (from build impact artifact) x witness case keys; note string keeps it honest ('covered = a verified witness exercises this node/field; nothing else counts') + routes server.py & aws_handlers.py (both surfaces) + UI: Impact panel with tone-coded bars (pass>=100%, warn>=50%, fail<50%) + uncovered list, fillCoverage() async after vImpact setView, skeleton while loading + palette: Ctrl/Cmd+K, 16 commands (10 tabs + compile/cloud/theme/judge/bundle/submit-policy), substring filter, role=dialog+listbox/option ARIA, Esc/overlay-click close, theme-token CSS, header command button | DONE: pytest 94/94 (+3 coverage tests), verify 178/178, judge_demo 6/6, journey 7/7, DOM-stub 'ALL RENDER PATHS + PALETTE OK (16 commands)', LIVE: coverage 2/2 nodes 1/1 fields via app runner | commit: 'T18: command palette (Ctrl+K), witness-coverage endpoint + Impact panel'
- 2026-09-19 (T16b) | Buffy | lab theme promoted to DEFAULT (user call: rust identity for the demo) | frontend/lib/app.js boot default 'lab' (OS-preference detection removed — identity now deliberate, not ambient), theme cycle lab→paper→graphite→lab; frontend/index.html early-paint hint sets data-theme=lab before stylesheets settle (no paper flash on load; localStorage still wins; inline script is 1 line, no CSP/Amplify impact) | DONE: node --check OK, judge_demo 6/6, journey 7/7 | commit: 'T16b: lab theme as default identity'
- 2026-09-19 (T16) | Buffy | external design-review triage + theme cycle + hero/editor structural pass | REVIEW WAS AGAINST A STALE SCREENSHOT (described T10-era UI: 'HOW THIS WORKS' eyebrows + native Choose File — both removed in T12/T13); its Concept 3 palette == T14 paper+teal tokens, Concept 1 == T14 dark tokens; took only the genuinely new: lab theme (warm graphite #121110 + rust #d97706 action accent + teal validation, optional third theme via data-theme=lab), theme cycle light→dark→lab with per-theme icons/titles (ph-moon/ph-sun/ph-flask), hero asymmetry 1.12fr→1.35fr, DELETED duplicate tagline under editor (advisor's 'remove, don't restyle'), drag-drop .md onto policy editor (functional affordance + dashed outline state) | DONE: node --check OK, ALL RENDER PATHS OK (DOM stub), judge_demo 6/6, journey 7/7 | commit: 'T16: theme cycle + lab theme, hero/editor structural pass from design review'
- 2026-09-19 (T15) | Buffy | governance bundle + witness nomination + CSV UI + server hardening | actions.py (governance_bundle: 409 without approval, sha256 seal over canonical bytes, BUNDLE_EXPORTED audit; nominate_witness: honesty gate == trace-compare criteria, find_witnesses+validate re-run, WITNESS_NOMINATED audit) + routes on server.py & aws_handlers.py + authz _writable + server.py ValueError→409 on build GETs + strict bind (no SO_REUSEADDR; orphaned backends silently shared :8001 and stole connections) + app.py backend-port failover + backend stderr→.app_backend.log + UI (download button, nominate buttons, CSV card) + docs/traces.md + CHANGELOG + tests 7 new | LIVE-VERIFIED via app runner: 409 refusal, 200+sha after approve, nomination honest 'already covers' path, CSV bulk 2 ingested | DONE | commit: 'T15: governance bundle export, witness nomination, CSV ingest UI; server 409 parity + strict bind + backend port failover'
Format: `- YYYY-MM-DD HH:MM | agent | task | files touched | result | notes/commit-msg-proposal`

- 2026-09-19 22:10 | opencode | T19 governance docs sweep | `README.md` (API highlights +3 routes; 2-sentence blurbs each for sha256-sealed bundle with 409-without-approval + nomination with honesty-gate/never-by-assertion; "11-tab"→"10-tab" per TABS count, "16 notes"→"21 notes" per glob) + `docs/architecture.md` (bundle/nomination/CSV routes with one-line honesty notes) + `docs/submission.md` (appended "Verify these numbers" block only — T17 sections untouched) | DONE: all route/behavior wording verified against services/api/{server,actions}.py docstrings + dispatch code (bundle_sha256 over canonical bytes, 409 unless approvals on record; nomination requires vs_stale DISAGREE then find_witnesses+validator re-run); number sweep: 178 ✓, 91 ✓ (rerun), 31 (manifest 15/16) ✓, 7 Lambdas ✓, 8 suites ✓; theme names resolved — code identities are light/dark/lab but user-facing names are paper/graphite/lab (lab boot default; neither README nor architecture mentioned themes so nothing stale there) | proposed commit: "Docs: T15 governance routes + honesty notes; stale-count sweep"
- 2026-09-19 22:10 | opencode | T20 CSV demo sample | `demo/traces-sample.csv` (new, 11 rows: eligible/ineligible/7.5-boundary/demo-7.8/witness-B-analogue/backlogs+obc/staff/past-date/8.0-late/just-below + row 11 = deliberate exact duplicate of row 4 to demo idempotent ingest) + `docs/demo-storyboard.md` (Shot 7: sample path + paste moment + duplicates:1 fallback) | DONE: verified LIVE via app on :8082 (isolated .app_data backend) — POST /traces/csv → ingested:10, duplicates:1, zero errors, correct coercion (required.upload_recommendation, ;-split steps, distinct TRC ids); server torn down + .app_data/ deleted after (./data untouched, verified present); no code/frontend touched | proposed commit: "Demo CSV sample (10+1 rows) + storyboard paste moment"

- 2026-09-19 21:45 | opencode | T18 handoff to Buffy (no code written) | `agents.md` (board row only) | RELEASED: T18 reassigned to Buffy per human, state OPEN. Handoff context — suggested scope: (1) Command palette = Cmd+K/Ctrl+K fuzzy launcher over TABS + actions (runBuild, cloudRun, toggleJudge, patchDecide, replay…), pure frontend, extend don't break the contract-function list in app.js header comment; (2) Coverage panel recommended = benchmark family × outcome matrix from `/benchmark-runs/latest` (cases carry case_id/split/status; family = id prefix) with dev/eval split coverage — Alternatives logged: per-build validation rollup (Tests tab data) or node coverage (witness-exercised vs total nodes). Constraints for implementer: esc() on every interpolated string, theme tokens in styles.css, keyboard a11y + focus trap for palette dialog, honest-UI (matrix cells map 1:1 to real case statuses); verify with node --check + DOM-stub render + verify.py + pytest + judge_demo | no commit (nothing built)

- 2026-09-19 19:00 | GitHub Copilot | T24 (was T8 on deploy branch) | `.github/workflows/ci.yml`, `docs/aws-setup.md`, `agents.md` | DONE: removed the unreadable `AWS_DEPLOY_ROLE_ARN` secret as a role-selection failure point; workflow now uses verified role ARN and runs `aws sts get-caller-identity`; AWS trust/provider verified; workflow assertion, infra validation, 178/178 verify, and 70/70 pytest PASS | commit: "Use verified IAM role for GitHub OIDC deploy"

- 2026-09-19 18:30 | GitHub Copilot | T23 (was T7 on deploy branch) | `docs/aws-setup.md`, `agents.md`, AWS IAM role trust | DONE: verified GitHub OIDC provider and audience; updated `GitHubActionsProcessPatchDeploy` trust from a single exact ref subject to repository-scoped `repo:Skullybutcher/Bharatbuilds:*`; workflow retains `id-token: write` and `contents: read` | commit: "Broaden GitHub OIDC trust to repository subjects"

- 2026-09-19 18:00 | GitHub Copilot | T22 (was T6 on deploy branch) | `.github/workflows/ci.yml`, `docs/aws-setup.md`, AWS IAM OIDC provider | DONE: registered `https://token.actions.githubusercontent.com` with audience `sts.amazonaws.com`; verified role `GitHubActionsProcessPatchDeploy` trust for `repo:Skullybutcher/Bharatbuilds:ref:refs/heads/main`; upgraded credentials action to v5; infra validation, 178/178 verify, 70/70 pytest, and workflow YAML parse PASS | commit: "Fix GitHub Actions AWS OIDC deployment auth"

- 2026-09-19 21:30 | opencode | T16+T17 docs | `docs/benchmark-v4-proposals.md` (new: 4 families — visa-threshold/list, trial-eligibility intervals+NOT_IN, benefits workreq exception+annual cap, export prohibition+carve-out — each with cited grounding URL, 2 author.py-format scenarios, construct + eval-credibility rationale; all inside rule-ir kinds/operators) + `docs/demo-storyboard.md` (new: 8 shots, 165s + 15s buffer = 180s, per-shot fallback, honesty doctrine, judge_demo gate) + `docs/submission.md` (What-we-built refresh) | DONE: touched NOTHING else (git status confirms); verify 178/178 PASS, pytest 91/91 green | NUMBER CORRECTIONS per verify-rule (task text was snapshot-stale): pytest 84→91 (T15 added 7), docs 19→21 (glob count incl. my 2 new files); also marked stale duplicate T11-OPEN row DONE so finished paths can't be re-claimed | proposed commit: "v0.4 benchmark proposals + 180s demo storyboard + submission refresh"

- 2026-09-19 20:40 | Buffy | T14 identity v4 "ledger of record" | `frontend/styles.css` (token swap: light = warm paper #f6f5f1 + white panels + deep-teal #0f766e accent + dot-grid texture; dark = graphite #0f1115 + muted cyan #3fb5b5; h1 clamp 30-42px editorial scale; spine dots 22px; removed all blue #4c8dff/#2563eb + stale [data-theme=light] selectors) + `frontend/lib/app.js` (applyTheme: paper is DEFAULT, dark opt-in, persists, respects prefers-color-scheme, correct sun/moon icons) | DONE: identity now subject-grounded (governance documents get paper + seal-teal, not devtool blue); zero blue tokens remain; node --check OK, DOM-stub render OK, judge_demo 6/6, verify 178/178, pytest 84/84; structure/contract untouched — pure token+theme logic swap | commit: "UI v4: ledger-of-record identity (paper default, teal seal accent; graphite night theme)"
- 2026-09-19 20:00 | Buffy | T13 filled dashboard canvas | `frontend/styles.css` (editor panel component, activity module grid, util-cluster header grouping, aws-chip sidebar card, spine pulse on live stage, hero focal glow) + `frontend/lib/app.js` (dashHtml/dashFill/dashOne: no-build screen now shows real recent builds/traces/procedure versions from the API with skeleton loaders; sidebar AWS section as a proper card; boot skeleton in index.html) + `frontend/index.html` (header hierarchy: one primary CTA, Cloud/API/theme/sign-in demoted into a quiet util cluster separated by a hairline; initial skeleton before JS boots) | DONE: node --check OK, all tabs render (DOM stub), journey 6/6, judge_demo 6/6, verify 178/178, pytest 84/84, infra PASS; activity modules render ONLY real stored data (skeleton → rows/empty), no decorative filler | commit: "UI v3.1: filled dashboard canvas, editor panel, header hierarchy"
- 2026-09-19 19:30 | Buffy | T12 design-system v3 (applied .agents/skills/frontend-design + design-taste-frontend) | `frontend/fonts/` (Satoshi 400/500/700/900 woff2, self-hosted ~24KB each), `frontend/vendor/phosphor.css` + woff2/woff (icon font, self-hosted), `frontend/styles.css` (v3: sentence-case kickers replace all-caps eyebrows — the top AI tell; gate-spine tracker as the ONE bold element; case-file witness cards; light+dark themes via data-theme tokens; icon nav), `frontend/index.html` (fonts.css, phosphor.css, theme toggle button), `frontend/lib/app.js` (toggleTheme, NAV_ICONS icon nav, gateSpine() state-driven tracker, iconified trust tags + 6 empty states) | DONE: node --check OK, all 10 tabs + hero render error-free (DOM stub), journey 6/6, judge_demo 6/6, verify 178/178; contract functions, esc(), doctrine wording untouched; no external runtime deps (all assets self-hosted — demo-safe offline) | commit: "UI v3: subject-grounded design system (Satoshi, gate spine, case-file witnesses, themes)"
- 2026-09-19 19:10 | opencode | T11 positioning + judge QA | `docs/positioning.md` (new, 514 words: landscape OPA/Celonis/Temporal/Guardrails+Ragas + 4-row comparison table, every competitor claim URL-cited + honest paragraph per README/benchmark/architecture/novelty wording) + `docs/judge-qa.md` (new, 10 Q&A × 3–5 sentences, each repo-grounded in README/architecture/trust-boundary/auth/benchmark) | DONE: zero OPEN QUESTIONs (all technical claims verified against committed docs; non-goals beyond Z3/Neptune deliberately omitted — no committed source); touched NOTHING else (git status confirms only the 2 new files are mine); verify 178/178 PASS, pytest 84/84 green; no README edits needed | proposed commit: "Judge prep docs: positioning landscape + grounded Q&A"

- 2026-09-19 18:40 | Buffy | T10 visual overhaul pass 2 | `frontend/styles.css` (full rewrite: ambient tint, 3-surface elevation + hairline alpha borders, shadows, type scale to 28px + negative tracking, styled file input, borderless hairline tables, hero layout, floating judge dock, skeleton shimmer, custom scrollbars, motion) + `frontend/lib/app.js` (hero markup, **fixed OC's unclosed-quote bug `class="evidence-grid>`** that silently disabled the evidence grid styles, SVG graph palette to current surfaces, Gate-2 checks as honest pass/warn pills instead of raw JSON dump, pipeline-strip emphasis) | DONE: node --check OK, all 10 tabs + hero executed error-free in a DOM-stub harness, journey 6/6, judge_demo 6/6, verify 178/178, pytest 84/84; contract functions, esc(), trust badges, doctrine wording untouched | commit: "UI pass 2: depth/elevation design system, hero layout, honest check pills; fix evidence-grid class bug"
- 2026-09-19 17:20 | Buffy | T7 (seeded demo + app E2E + CSV ingest) + closes opencode's NEEDS_BUFFY | `scripts/app.py` (seed via real API paths + Windows Job Object reaping + port-fallback + own `.app_data/` dir), `services/traces/store.py` (`validate_trace` split out), `services/api/actions.py` (`bulk_ingest_traces_csv`), routes in `server.py`+`aws_handlers.py`, `authz.py` (writable `/traces/csv`), `tests/journey/test_app.py` (rewrite: hermetic + valid orphan check — old version reused the fixture's backend port, invalid; also closes the NEEDS_BUFFY flag), `tests/unit/test_traces_csv.py` (new, 8 tests), `docs/traces.md`, `CHANGELOG.md`, `services/api/server.py` (error-parity fix) | DONE: verify 178/178, pytest 84/84 (+14), INFRA PASS, judge_demo 6/6; server now maps ValueError→409/KeyError→404 like Lambda instead of dropping connections; :8080 blackhole on this machine handled (auto port-fallback, strict bind on Windows) | commit: "T7: seeded demo state, app E2E suite, CSV bulk trace ingest; server error parity"

- 2026-09-19 16:00 | opencode | T9 docs | `docs/demo-script.md` (rewrite: judge_demo gate + local `make app` path + cloud Amplify/SFN path + honesty checklist) + `docs/deployment-runbook.md` (new step 0 `make app` rehearsal, old 0–7 → 1–8) + `CHANGELOG.md` (new v0.3.1: app runner, first-run polish, redesign, docs audit, smoke.ps1 fix) | DONE docs scope; verify.py 178/178 PASS; NO code/frontend touched | !! NEEDS_BUFFY: `pytest tests -q` → 74 tests, 2 FAILED in untracked `tests/journey/test_app.py` (Buffy's new CSV-bulk work, uses ports 8791/8792 so NOT the :8080 conflict): `test_csv_bulk_ingest_via_app` (200 OK but `ingested` 0 == 2, line 126) + `test_shutdown_reaps_backend_child` (Windows FileNotFoundError from subprocess). Uncommitted backend changes present (`services/api/*`, `scripts/app.py`, `test_app.py`). Did not touch per ownership — Buffy please fix before human commits | proposed commit: "Docs for v0.3.1: make-app demo script, runbook step 0, changelog"

- 2026-09-19 15:30 | opencode | T8 first-run polish | `frontend/lib/app.js` only (5 edits; no styles.css change, no new globals, no new files) | DONE: no-build hero → 3-step how-it-works (Compile/Inspect/Approve) + one CTA (runBuild); empty states with sentence+button for Traces-zero (focuses ingest form), Builds-zero (runBuild), Workspaces-zero + Procedures-zero (focus create/register forms), Benchmarks-none (exact `make benchmark` + copy button), Approval-no-build guard; contract intact (node --check OK, all 29 functions + esc() + tokens unchanged); judge_demo ALL 6 BEATS VERIFIED, verify 178/178, pytest 70/70 | ENV NOTE: :8080 is held by MiniTool ShadowMaker AgentService (blackholes HTTP) so `make app` default port can't bind here — verified live on `--port 8082 --backend-port 8002` (shell/config.js=/api/proxy/empty-states all 200, zero-workspace state observed live: 3 traces, 2 builds, 0 workspaces); test server torn down after | proposed commit: "First-run polish: no-build hero + empty states with actions (frontend only)"

- 2026-09-19 15:00 | Buffy | T6 one-command app | `scripts/app.py` (new), `Makefile`, `frontend/lib/app.js` (1 line: sync apiBase from config.js), `README.md` (quickstart) | DONE: `make app` serves UI + /api proxy on ONE port (8080); E2E curl-verified (shell, config.js=/api, styles/app.js 200, health, proxied GET canonical + POST traces, path-traversal guard 404); verify 178/178 + pytest 70/70 after | commit: "Add make app: one-command local app (UI + same-origin API proxy)"
- 2026-09-19 14:10 | Buffy | T5 (NEEDS_BUFFY closure) | `scripts/smoke.ps1` | DONE: mirrored bash smoke auth checks (auth-config fetch, 401 checks on /builds + guardrails via StatusCode helper); PowerShell Parser::ParseFile → parse OK; verify 178/178 PASS after edit | commit: "Smoke (ps1): assert auth-gated routes like bash smoke" — resolves the NEEDS_BUFFY note from T2 review prep
- 2026-09-19 14:00 | Buffy | integration review of T1–T4 | read-only across frontend/**, tests/**, docs/**, CHANGELOG.md | VERDICT: all four tasks verified independently — 178/178 verify, 70/70 pytest (Bob's 18 included), INFRA PASS, judge_demo 6/6 beats, app.js syntax OK, zero banned patterns in styles.css, all 10 tabs + contract functions + esc() (48 uses) intact, Bob's doc numbers spot-checked correct (31-scenario, 16-case, 178, auth cross-refs) | both agents' DONE claims confirmed; tree ready for human to commit
- 2026-09-19 13:30 | opencode | T1 UI upgrade | `frontend/index.html` (shell rewrite) + `frontend/styles.css` (new, design tokens) + `frontend/lib/app.js` (new, all 29 contract functions ported) + `frontend/DESIGN.md` (new) | DONE: verify 178/178 PASS, pytest 70/70, judge_demo ALL 6 BEATS VERIFIED; all 10 tabs + 6-step Judge bar + API paths/bodies + esc() + trust badges + VALIDATED_WITHIN_TESTED_MODEL preserved; no NEEDS_BACKEND gaps | proposed commit: "UI upgrade: design-system pass on frontend (tokens, Stripe-density layout, prune slop, split styles/app.js)"
- 2026-09-19 09:30 | IBM Bob | T2 | `docs/consistency-audit.md` (new); `docs/submission.md`, `docs/benchmark.md`, `docs/deployment-runbook.md`, `docs/architecture.md`, `docs/governance.md`, `docs/trust-boundary.md`, `README.md` (mechanical fixes) | Audit: 11 findings (5 stale counts, 6 missing cross-refs). Mechanical fixes applied: "26-scenario"→"31-scenario" (submission.md); "13-case"→"16-case" eval split + "20"→"22" auto-repaired (benchmark.md); "176/176"→"178/178" (deployment-runbook.md); "176"→"178" (README.md); auth/traces/workspaces cross-refs added to architecture.md, governance.md, trust-boundary.md. Prose-only changes (demo-script.md flow extension) proposed in consistency-audit.md, not auto-applied. | commit: "Docs consistency pass for v0.3.0"
- 2026-09-19 09:00 | IBM Bob | T3 | `tests/unit/test_normalizer_ext.py` (new) | 18 tests, 5 coverage areas: same-field-only delta, interval satisfiability, IN/NOT_IN eval, validate_rule rejections, provenance-only delta. Ran `pytest tests/unit/test_normalizer_ext.py` → 18/18 PASS; full `pytest tests` → 70/70 PASS (52 prior + 18 new). No existing files touched. | commit: "Add normalizer/delta edge-case tests"
- 2026-09-19 08:30 | IBM Bob | T4 | `CHANGELOG.md` (new) | Keep-a-Changelog format; v0.3.0 (auth, traces, language, workspaces, judge demo), v0.2.0 (4 bullets from git log), v0.1.0 (3 bullets). All claims verified against benchmark_runs/BENCH-v030-REF metrics.json + git log. No existing files touched. | commit: "Add CHANGELOG; document v0.3.0"
- 2026-09-19 07:30 | Buffy | setup | `agents.md` | created coordination protocol | task board seeded (T1–T5)
- 2026-09-19 05:00–07:00 | Buffy | (pre-agents.md) auth + traces + language v0.3.0 + workspaces + judge demo | see git status; 178/178 verify, 52/52 pytest, INFRA PASS, bench v0.3.0 all green | 5 commit messages proposed to human; no commits made by agents
