"""Model fallback for rule extraction (honest hybrid design).

Fast path: deterministic parser (services.extractor.extractor.extract).
Fallback: Bedrock Converse (MODEL_ID) ONLY when the parser yields nothing
usable AND PROCESSPATCH_MODEL_FALLBACK=1. Model output is schema-validated;
anything invalid becomes NEEDS_REVIEW — never silently accepted, never
auto-compiled (it still passes Gate-1 review like every other candidate).

Without credentials/boto3, or on any model error, returns
EXTRACTION_UNAVAILABLE instead of raising or fabricating rules.
"""
from __future__ import annotations
import json
import os

PROMPT = """You convert a short policy excerpt into typed operational Rule IR.
Return ONLY a JSON list. Each item: {"kind": one of threshold, obligation, conditional_obligation, prohibition, prerequisite, exception, deadline,
"subject": string, "action": snake_case verb phrase,
"condition": null or {"field": string, "operator": one of >=,<=,>,<,==,IN,NOT_IN, "value": number|string|list} or {"and":[...]} or {"not":...} or {"prerequisite": string, "target": string, "relation": "BEFORE"},
"section": string, "source_text": exact quote from the excerpt}.
If a clause is vague, contradictory, or outside these kinds, return [] and note it in "unresolved" items {"unresolved": reason}.
Supported fields include cgpa, score, amount, income, year, backlogs, category, submission_date.
Excerpt:
"""


def model_extract(policy_text: str, policy_version_id: str = "POLICY-VX",
                  effective_from: str = "2026-09-18") -> dict:
    model_id = os.environ.get("MODEL_ID", "amazon.nova-micro-v1:0")
    try:
        import boto3  # lazy: Lambda only
        client = boto3.client("bedrock-runtime")
        resp = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": PROMPT + policy_text[:4000]}]}],
            inferenceConfig={"maxTokens": 1500, "temperature": 0})
        text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    except Exception as e:  # noqa: BLE001 — no creds/model must never break extraction
        return {"rules": [], "needs_review": [], "conflicts": [],
                "status": "EXTRACTION_UNAVAILABLE", "backend": f"bedrock:{model_id}",
                "error": f"{type(e).__name__}: {e}"[:300]}

    from services.normalizer.normalizer import validate_rule
    import hashlib
    rules, needs_review = [], []
    try:
        items = json.loads(text[text.index("["):text.rindex("]") + 1])
    except (ValueError, IndexError):
        return {"rules": [], "needs_review": [{"code": "UNCOMPILABLE / NEEDS_REVIEW",
                                               "reason": "model returned non-JSON output"}],
                "conflicts": [], "status": "NEEDS_REVIEW", "backend": f"bedrock:{model_id}"}
    for i, it in enumerate(items):
        if "unresolved" in it:
            needs_review.append({"code": "UNCOMPILABLE / NEEDS_REVIEW",
                                 "reason": str(it["unresolved"])[:300]})
            continue
        r = {"rule_id": f"RULE-M-{i + 1:03d}", "kind": it.get("kind"),
             "subject": it.get("subject", "applicant"), "action": it.get("action"),
             "condition": it.get("condition"),
             "normalized_expression": json.dumps(it.get("condition"), default=str),
             "effective_from": effective_from, "effective_to": None, "status": "active",
             "supersedes": None,
             "provenance": {"policy_version_id": policy_version_id,
                            "document_sha256": hashlib.sha256(policy_text.encode()).hexdigest()[:16],
                            "page": 2, "section": str(it.get("section", "?")),
                            "source_text": str(it.get("source_text", ""))[:500]},
             "extraction": {"model": f"bedrock:{model_id}", "confidence": 0.0,
                            "review_state": "pending_review"}}
        errs = validate_rule(r)
        if errs:
            needs_review.append({"code": "UNCOMPILABLE / NEEDS_REVIEW",
                                 "reason": f"model rule failed schema: {errs}"})
        else:
            rules.append(r)
    status = "NEEDS_REVIEW" if needs_review else ("EXTRACTED" if rules else "NEEDS_REVIEW")
    return {"rules": rules, "needs_review": needs_review, "conflicts": [],
            "status": status, "backend": f"bedrock:{model_id}"}


def extract_with_fallback(policy_text: str, policy_version_id: str = "POLICY-VX",
                          effective_from: str = "2026-09-18") -> dict:
    """Parser first; model only when the parser yields nothing usable and the
    fallback flag is enabled. Model candidates always enter Gate-1 review."""
    from services.extractor.extractor import extract
    base = extract(policy_text, policy_version_id, effective_from)
    base["backend"] = "deterministic-parser/0.1.0"
    usable = [r for r in base["rules"]]
    if usable or os.environ.get("PROCESSPATCH_MODEL_FALLBACK", "0") != "1":
        return base
    fb = model_extract(policy_text, policy_version_id, effective_from)
    if fb["status"] == "EXTRACTION_UNAVAILABLE":
        base["model_fallback"] = fb
        return base
    merged = {**base, "rules": fb["rules"],
              "needs_review": base["needs_review"] + fb["needs_review"],
              "status": fb["status"], "backend": fb["backend"],
              "model_fallback_used": True}
    return merged
