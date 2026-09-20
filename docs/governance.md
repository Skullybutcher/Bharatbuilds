# Human-in-the-loop governance (57B)

AI_EXTRACTED ≠ MACHINE_VERIFIED ≠ HUMAN_APPROVED.

## Gates

1. Rule review: ACCEPT | EDIT (keeps machine value) | REJECT | ESCALATE.
2. Patch review: APPROVE_CANDIDATE | REJECT_PATCH | REQUEST_REVISION, with
   Impact Dashboard, regression, provenance, locality, warnings visible.
3. Activation: FINAL_APPROVAL creates the new procedure version and flips the
   active pointer. Never mutates an external enterprise system.

## Guardrails (APPROVE disabled while any hold)

unresolved_rule_review > 0; unresolved_conflicts > 0; patch_validation ≠ PASS;
preservation ≠ PASS; provenance_coverage < 1.0; candidate_hash_changed_since_review.

## Records

Approval binds reviewer, role (POLICY_REVIEWER / PROCEDURE_OWNER /
FINAL_APPROVER), reason, timestamp, and artifact hashes (policy, before/after,
patch, certificate). Since v0.3.0, `reviewer` and `role` are stamped by the
Cognito-verified identity (`services/api/authz.py`), callers cannot supply or
spoof these fields (docs/auth.md). Activation re-verifies hashes server-side;
stale review → APPROVAL INVALIDATED. Rejections are retained (inactive
candidate + comment); revisions chain P-019 revised_by P-020. Full audit
timeline per build.

On AWS, Gates 1–3 are Step Functions task-token waits; the local server
implements the same transitions in application state.
