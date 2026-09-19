"""Patch certificate: machine + human readable verification bundle (not a
compliance guarantee — evidence for the bounded model only)."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def build_certificate(*, build_id: str, policy_version: str, procedure_before: dict,
                      procedure_after: dict, changed_rules: list, sources: list,
                      semantic_delta: dict, witnesses: list, impact: dict,
                      tests_before: dict, tests_after: dict,
                      approvals: list | None = None,
                      policy_text: str | None = None,
                      accepted_rule_ir: list | None = None,
                      compiler_version: str = "0.1.0") -> dict:
    cert = {
        "certificate": "PATCH CERTIFICATE",
        "build": build_id,
        "policy": policy_version,
        # Explicit hash names: each says exactly what it covers.
        "source_document_sha256": sha(policy_text) if policy_text is not None else None,
        "accepted_rule_ir_sha256": sha(accepted_rule_ir) if accepted_rule_ir is not None else sha(sources),
        "source_clauses": sources,
        "procedure_before": procedure_before.get("procedure_version_id"),
        "procedure_before_sha256": sha(procedure_before),
        "procedure_after": (procedure_after or {}).get("procedure_version_id"),
        "procedure_after_sha256": sha(procedure_after) if procedure_after else None,
        "changed_rules": changed_rules,
        "sources": sources,
        "semantic_delta": semantic_delta,
        "witnesses": witnesses,
        "impact_summary_ref": (impact or {}).get("build_id", build_id),
        "tests_before": tests_before,
        "tests_after": tests_after,
        "approvals": approvals or [],
        "compiler": compiler_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "VALIDATED_WITHIN_TESTED_MODEL",
        "disclaimer": ("Evidence-backed verification for the bounded model ProcessPatch "
                       "supports; NOT a guarantee of full institutional compliance."),
    }
    cert["certificate_sha256"] = sha({k: v for k, v in cert.items() if k != "certificate_sha256"})
    return cert


def render_text(cert: dict) -> str:
    lines = ["PATCH CERTIFICATE", "------------------------------------",
             f"Build: {cert.get('build')}", f"Policy: {cert.get('policy')}",
             f"Source document SHA256: {cert.get('source_document_sha256')}",
             f"Accepted Rule IR SHA256: {cert.get('accepted_rule_ir_sha256')}",
             f"Procedure before: {cert.get('procedure_before')} SHA256: {cert.get('procedure_before_sha256')}",
             f"Procedure after: {cert.get('procedure_after')} SHA256: {cert.get('procedure_after_sha256')}"]
    for r in cert.get("changed_rules", []):
        lines.append(f"Changed rule: {r}")
    for s in cert.get("sources", []):
        lines.append(f"Source: Page {s.get('page')}, Sec.{s.get('section')} [{s.get('policy_version_id')}]")
    lines.append(f"Semantic delta: {(cert.get('semantic_delta') or {}).get('type')}")
    for w in cert.get("witnesses", [])[:4]:
        lines.append(f"Witness {w.get('witness_id')}: {w.get('case')} {w.get('kind')}")
    tb, ta = cert.get("tests_before", {}), cert.get("tests_after", {})
    lines.append(f"Tests before: {tb.get('failed', '?')} failed / {tb.get('total', '?')}")
    lines.append(f"Tests after: {ta.get('passed', '?')} passed / {ta.get('total', '?')}")
    lines.append(f"Compiler: {cert.get('compiler')}")
    lines.append(f"Status: {cert.get('status')}")
    return "\n".join(lines)
