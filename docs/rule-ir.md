# Rule IR

Typed, provenance-linked machine rule. Every rule carries
`provenance {policy_version_id, document_sha256, page, section, source_text}`
and `extraction {model, confidence, review_state}`. Schema: `shared/schemas/rule_ir.json`.

Supported MVP kinds: threshold, obligation, conditional_obligation, prohibition,
prerequisite/ordering, exception, deadline. Example: RULE-REC-014
conditional_obligation `IF cgpa < 8.0 THEN upload_recommendation`.

Fail-closed: ambiguous → UNCOMPILABLE/NEEDS_REVIEW; contradictory active rules
without precedence → CONFLICT/COMPILATION BLOCKED. Gate-1 review (ACCEPT/EDIT/
REJECT/ESCALATE) happens before compilation; EDIT preserves the machine value
alongside the human correction.
