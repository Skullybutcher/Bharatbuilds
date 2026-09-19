# Positioning

**ProcessPatch is an operational rule compiler — CI for real-world procedures.**
When a policy is amended, it compiles the amendment into a verified,
human-approved patch to the deployed procedure, with concrete counterexamples
(witnesses) as regression tests. It sits in the gap between policy-as-code
(which *evaluates* rules) and workflow engines (which *execute* procedures):
the compile-and-repair step neither covers.

## Adjacent landscape

- **Policy-as-code (Open Policy Agent).** OPA is a general-purpose policy
  engine: Rego policies evaluated over JSON inputs to allow/deny decisions at
  enforcement points (Kubernetes admission, CI/CD, API gateways), with audit
  trails and decision replay.
- **Process mining (Celonis).** Ingests event logs and reconstructs how
  processes actually run (digital twin, variants, deviations), including
  conformance checking of mined processes against modeled ones.
- **Durable execution (Temporal).** Workflows that run to completion despite
  failures, including a human-in-the-loop approval pattern: signals carrying
  approver identity, reason, and timestamp, with full audit history.
- **LLM guardrails and evals (Guardrails AI, Ragas + LangSmith).** Validators
  over model inputs/outputs (detect, quantify, mitigate risk) and metrics such
  as faithfulness and answer relevancy for QA pipelines.

## Comparison

| Tool | What it does | What it doesn't do that ProcessPatch does |
|---|---|---|
| OPA | Evaluates hand-written Rego to allow/deny at enforcement points; audit + replay. | Extract rules from natural-language amendments; prove a deployed procedure stale with named witnesses; synthesize the repaired procedure; bind activation to human approval of exact hashes. |
| Celonis | Reconstructs how processes run from event logs; conformance vs. the modeled process. | Start from a policy amendment instead of logs — it finds deviations but doesn't compile the fix. |
| Temporal | Durable execution with HITL approval signals and audit history. | Derive what the procedure should *become* after a rule change (semantic diff, witnesses, localized patch). Engines are complement: ProcessPatch itself orchestrates on Step Functions. |
| Guardrails / Ragas | Validate LLM text output (validators, faithfulness metrics). | Touch operational procedures at all — and their verdicts come from models, while ProcessPatch verdicts are deterministic code with the model strictly proposing. |

## Honest positioning

ProcessPatch owns the compile-and-repair gap and nothing else. It does **not**
guarantee compliance: patches are `VALIDATED_WITHIN_TESTED_MODEL`
(`README.md`). Its benchmark is 31 hand-authored scenarios with a 16-case
frozen held-out split scored on gold Rule IR downstream (`docs/benchmark.md`)
— evidence of repair mechanics, not real-world generality. Witness search is
deterministic sampling, not SMT solving (`docs/architecture.md`). No step
auto-accepts model output: ambiguity → `NEEDS_REVIEW`, contradiction →
`COMPILATION BLOCKED`, and three human gates bind exact hashes (`README.md`,
`docs/trust-boundary.md`). Per `docs/novelty.md`, no single technique is
claimed novel — the experiment is the witness-first repair loop with
hash-bound governance.

## Sources

- OPA engine, audit trails, decision replay: https://openpolicyagent.org/
- Admission control (intercept before persistence; validating/mutating):
  https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/
- Process mining (event logs → digital twin; deviations):
  https://www.celonis.com/insights/topics/how-does-process-mining-work
- Conformance (mined vs. modeled; deviations, root causes):
  https://www.celonis.com/platform/process-analysis
- Temporal durable execution: https://docs.temporal.io/workflow-execution
- Temporal approval pattern (signals, approver identity, audit history):
  https://docs.temporal.io/design-patterns/approval
- Guardrails (input/output guards, validators, on-fail actions):
  https://github.com/guardrails-ai/guardrails
- Ragas + LangSmith (faithfulness / relevancy metrics for QA pipelines):
  https://langchain-blog.ghost.io/evaluating-rag-pipelines-with-ragas-langsmith/
