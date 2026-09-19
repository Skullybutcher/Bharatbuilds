# Trust boundary

Extraction is hybrid: a deterministic parser is the fast path for the bounded
language; a Bedrock fallback (`services/extractor/model_fallback.py`) engages
only when the parser yields nothing usable, and its output is schema-validated
and Gate-1 reviewed — model candidates are never auto-accepted. Without
credentials the fallback reports EXTRACTION_UNAVAILABLE instead of guessing.

Model MAY: propose candidates, classify rule types, extract spans, flag ambiguity.
Model MAY NOT: declare compliance, decide pass/fail, validate patches, deploy,
choose precedence, hide uncertainty.

Deterministic code owns: constraints, witness search, localization, regression,
impact aggregation, certificates. Human owns: rule acceptance, patch approval,
activation. UI labels every result AI-EXTRACTED vs VERIFIED vs VALIDATED vs
HUMAN-APPROVED — never merged into one confidence number.

API auth boundary: HttpApi Cognito JWT authorizer rejects unverified tokens
before Lambda; `services/api/authz.py` re-checks claims and stamps verified
identity into every gate action (docs/auth.md).
