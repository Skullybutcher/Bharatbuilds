# Demo script (3 min)

Record only after `python scripts/judge_demo.py` prints ALL 6 BEATS VERIFIED —
the demo below is those beats, performed live.

Person-first spine: a real applicant (CGPA 7.80) is ELIGIBLE under Policy V2,
but the deployed portal calls them INELIGIBLE — enforcing yesterday's rule.
Everything after that answers: which procedure steps are wrong now, and who
says the fix is safe?

## Local path (default): one command

`make app` → http://localhost:8080 — UI + API on one port, no deploy, no
keys, no sign-in (local dev runs with auth off). Zero-risk rehearsal before
any cloud step. (If :8080 is taken on your machine:
`python scripts/app.py --port 8082 --backend-port 8002 --no-open`.)

0:00 Overview hero → COMPILE AMENDMENT (deterministic pipeline).
0:15 Portal check CGPA 7.80 → DISAGREEMENT — PROCEDURAL DRIFT CONFIRMED.
0:30 BUILD: COMPOUND change, 2 witnesses, localized patch, 16/16 validation.
0:43 Witness A (7.80 PASS vs FAIL) + Replay witness. Witness B (8.20 SKIP vs
REQUIRE) + Boundary explorer.
1:05 Procedure tab: red = stale node; click it — provenance drawer (Policy V2
p3 §4.2), witnesses touching it, patch ops.
1:20 Patch tab: the localized diff. Tests tab: 16/16,
VALIDATED_WITHIN_TESTED_MODEL — never "compliance guaranteed".
1:35 Impact tab: blast radius (2 nodes), synthetic cohort (n=100) — counts are
representative witnesses, never headcounts.
1:50 Traces tab: one ingested real execution DISAGREEs with stale, AGREEs with
patched. Traces are evidence only — never witnesses.
2:00 Approval tab: 5 merge-protection checks green → APPROVE (Gate 2) →
activate (Gate 3) → new procedure version. Patch certificate.
2:30 Judge Mode replays this exact arc in 6 guided steps for evaluators.
2:50 Close: "AI extracts; deterministic code verifies; humans approve."
"Software bugs get regression tests. Procedural bugs should too."

## Cloud path (same beats, real orchestration)

Amplify URL (Outputs.AmplifyAppId → branch URL); set the UI's API field to
the ApiUrl; SIGN IN (hosted UI — reviewer/admin groups gate the actions).
Run Cloud Execution instead of Compile Amendment: DRAFT registration → Step
Functions execution (task-token human gates) → poll the execution ARN → same
witnesses / patch / tests / approval flow, decided via /resume with
hash-verified activation. Screenshot the CloudWatch dashboard (name in
Outputs) for the write-up.

## Honesty checklist (say these, or cut the take)

- Name the extraction badge on screen (FIXTURE / DETERMINISTIC_PARSER /
  BEDROCK_CANDIDATE).
- Cohort and benchmark numbers are authored/synthetic — never population or
  prevalence claims.
- No witness without the verified pipeline; no "COMPLIANCE GUARANTEED".
