# Judge Q&A

Short, repo-grounded answers to the hard questions. Sources in brackets;
every technical claim below is verifiable in the cited file.

## 1. Why isn't this just OPA?

OPA evaluates hand-written Rego to allow or deny a request at an enforcement
point. ProcessPatch starts where OPA stops: it extracts rules from a
natural-language amendment, proves the deployed procedure stale with named
witnesses, synthesizes the repaired procedure, and gates activation on human
approval of exact hashes. OPA answers "is this request allowed?"; ProcessPatch
answers "which steps are now wrong, what is the fix, and who approved it?"
(`README.md`, `docs/trust-boundary.md`).

## 2. What happens when extraction is wrong?

The deterministic parser is the fast path and emits candidates with source
spans; the Bedrock fallback engages only when the parser yields nothing
usable, and its output is schema-validated and Gate-1 reviewed like everything
else — model output is never auto-accepted, and without credentials the
fallback reports `EXTRACTION_UNAVAILABLE` instead of guessing. Ambiguity routes
to `NEEDS_REVIEW` and contradiction without precedence to `COMPILATION
BLOCKED`, so a bad extraction stalls the pipeline rather than corrupting it.
The UI labels every result `FIXTURE`, `DETERMINISTIC_PARSER`, or
`BEDROCK_CANDIDATE`, so provenance is always visible. (`docs/trust-boundary.md`,
`README.md`)

## 3. Why human approval — and why three gates?

Machines verify within a tested model; only a human can accept the residual
risk, which is why patches are `VALIDATED_WITHIN_TESTED_MODEL` and never
"compliance guaranteed". Gate 1 reviews rule interpretation ("did we read the
policy right?"), Gate 2 approves the candidate patch ("do tests and provenance
justify it?"), and Gate 3 activates the exact immutable candidate with a
hash-verified operation. Cognito groups enforce who may do what —
`pp-reviewers` for Gates 1–2, `pp-admins` for activation — with verified
identities stamped into the audit trail. (`README.md`, `docs/auth.md`,
`docs/workspaces.md`)

## 4. Why not let the LLM rewrite the procedure directly?

The trust boundary forbids it: the model may propose candidates, classify rule
types, extract spans, and flag ambiguity — but it may not declare compliance,
decide pass/fail, validate patches, deploy, choose precedence, or hide
uncertainty. Deterministic code owns constraints, witness search, regression,
impact aggregation, and certificates; humans own rule acceptance, patch
approval, and activation. Even the Bedrock fallback passes through Gate-1
review, so there is no path on which model text becomes procedure without a
human decision. (`docs/trust-boundary.md`)

## 5. How is a witness different from a test?

A witness is a verified counterexample produced by the pipeline: one
representative case per failure mode where expected and actual outcomes
disagree (e.g., CGPA 7.80, expected eligible, portal ineligible). Tests are
the regression suites that replay those witnesses and add boundary,
preservation, integrity, ordering, metamorphic, and provenance checks — 16/16
in the canonical demo. Witnesses are the failing cases; the suite proves the
patch fixes them without breaking anything else. (`README.md`)

## 6. What if the policy is ambiguous or contradictory?

Ambiguity resolves to `NEEDS_REVIEW`: a human settles the reading at Gate 1
before compilation proceeds. Contradiction without a stated precedence
resolves to `COMPILATION BLOCKED` — the pipeline refuses to guess, and a
`RESOLVE_AUTHORITY` stage handles precedence only where authority is actually
stated. Every fork fails closed: there is no witness without the verified
pipeline behind it. (`README.md`, `docs/architecture.md`)

## 7. Traces vs. witnesses — what's the difference?

Traces are ingested real-world executions and are evidence only: the engine
replays each case deterministically and reports agreement against the stale
and patched graphs through a read-only comparison. A disagreeing trace never
becomes a witness on its own — witnesses come exclusively from the verified
compile → diff → search pipeline. This is deliberate: production anecdotes
inform, but they must not auto-rewrite procedures. (`README.md`,
`docs/trust-boundary.md`, doctrine in `agents.md` §5)

## 8. What's the scale story?

Procedures here are tens of nodes (order of 20–100 per workflow), so
DynamoDB/JSON plus in-memory traversal beats a graph database on simplicity
and cost — Neptune waits for cross-workflow scale. The system is serverless
and bursty with no always-on compute: a 40-state Step Functions machine, seven
Lambdas, single-table DynamoDB, and versioned S3 evidence. The same Python
runs locally on files and on Lambda on DynamoDB via a storage switch, so scale
is a deployment setting, not a rewrite. (`docs/architecture.md`,
`docs/cost.md`, `docs/submission.md`)

## 9. What's not real yet?

Witness search is bounded deterministic sampling, not SMT solving — Z3
containerization is a documented future step, not a current claim. The
benchmark is 31 hand-authored scenarios with a 16-case frozen held-out split
scored on gold Rule IR downstream: evidence of repair mechanics, not
independent real-world generality. No production deployment is recorded in the
repo — infrastructure is validated statically without credentials and the
first deploy follows the runbook. (`docs/architecture.md`,
`docs/benchmark.md`, `README.md`, `docs/deployment-runbook.md`)

## 10. Why Step Functions — and why does local run identical code?

Step Functions provides the orchestration substrate: a 40-state build machine
whose `WAIT_FOR_*` states hold on task tokens for human decisions without
polling loops or schedulers. The local server and the Lambda `ApiFn` share one
implementation (`services/api/actions.py`), so both surfaces stay identical —
the `make app` demo exercises the exact logic that runs in the cloud, with
only the storage backend swapped. That is also why the cloud approval path
reuses the same gates via server-side resume instead of duplicating side
effects. (`docs/architecture.md`, `README.md`)
