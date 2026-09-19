"""Provenance: node -> rule -> policy-clause chains + coverage + evidence drawer."""
from __future__ import annotations


def evidence_drawer(node: dict, rules_by_id: dict) -> dict:
    out = {"node_id": node.get("node_id"), "label": node.get("label"), "chain": []}
    for link in node.get("provenance_links", []):
        rid = link.get("target")
        r = rules_by_id.get(rid, {}) or {}
        prov = r.get("provenance", {}) or {}
        out["chain"].append({"relation": link.get("type"), "rule_id": rid,
                             "rule_expr": r.get("normalized_expression"),
                             "policy_version": prov.get("policy_version_id"),
                             "page": prov.get("page"), "section": prov.get("section"),
                             "source_text": prov.get("source_text"),
                             "supersedes": r.get("supersedes"),
                             "review_state": (r.get("extraction", {}) or {}).get("review_state")})
    return out


def _is_structural(node: dict) -> bool:
    """Start/submit framing nodes carry no rule semantics of their own."""
    impl = node.get("implementation", {}) or {}
    if node.get("type") == "start":
        return True
    return set(impl) == {"action"} and impl.get("action") == "submit"


def coverage(nodes: list[dict]) -> dict:
    governed = [n for n in nodes if not _is_structural(n)]
    linked = sum(1 for n in governed if n.get("provenance_links"))
    total = len(governed)
    return {"nodes": len(nodes), "governed_nodes": total, "linked": linked,
            "coverage": (linked / total) if total else 1.0}
