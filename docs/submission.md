# Submission write-up

## Problem

Rules change; operational copies drift. A student can be rejected by a portal
enforcing yesterday's rule.

## Insight

Treat procedures like compiled artifacts: policies are source, procedures are
builds, amendments are commits, affected people are failing tests.

## What we built

NL rules → Rule IR → constraints → verified witnesses → localized patch →
regression + impact + certificate → hash-bound human approval → new procedure
version. 26-scenario heterogeneous benchmark; full AWS orchestration.

## Why it is trustworthy

AI extracts; deterministic logic verifies; humans approve exact hashes.
Ambiguity/conflict fail closed. Never "compliance guaranteed".

## AWS architecture

Step Functions state machine (visible, retryable, task-token gates); 7
single-purpose Lambdas; S3 immutable evidence; DynamoDB versioned state;
Bedrock extraction only; EventBridge decoupling; Amplify frontend; CloudWatch
observability. Each service exists for a pipeline reason (§39).

## What fought back

Paraphrase identity (solved via semantic signatures); single-graph strictness
(solved via constraints); LLM-as-judge unauditability (deterministic
validator); graph-DB temptation (DynamoDB+memory suffices); witness-fixing
patches breaking unrelated cases (preservation suite mandatory); spurious
obligation inference on pure approval nodes (pure vs obligation modeling).

## What we learned

Separate proposal from verdict; quantify impact only from traceable artifacts;
bind approvals to hashes; one representative witness per failure mode beats
cartesian dumps; honest benchmark categories beat fake 100%.

## What comes next

Runtime traces, decision/incident provenance, larger rule language, Neptune
only at cross-workflow scale.
