"""Workflow interpreter: executes a procedure DAG against a case (deterministic).

Node implementation shapes (all optional keys):
  {"kind":"threshold_gate","field","operator","value"}   AND into eligible
  {"kind":"deadline_gate","field","operator","value"}    AND into on_time
  {"form_field": str, "action": str, "required": bool, "required_condition": cond}
  {"approver": token}            approval step
  {"action":"submit"}            submission step
  {"role": token}                generic role tag used for ordering matching
"""
from __future__ import annotations
from services.workflow.expr import eval_condition


def _ordered_nodes(workflow: dict) -> list[dict]:
    nodes = {n["node_id"]: n for n in workflow.get("nodes", [])}
    edges = workflow.get("edges", [])
    indeg = {nid: 0 for nid in nodes}
    adj = {nid: [] for nid in nodes}
    for e in edges:
        f, t = e.get("from"), e.get("to")
        if f in nodes and t in nodes:
            adj[f].append(t)
            indeg[t] += 1
    queue = [nid for nid, d in indeg.items() if d == 0]
    order = []
    while queue:
        nid = queue.pop(0)
        order.append(nodes[nid])
        for m in adj[nid]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    return order if len(order) == len(nodes) else list(workflow.get("nodes", []))


def _norm(t: str) -> str:
    return str(t).lower().replace("_", " ").replace("-", " ").strip()


def _node_tokens(node: dict) -> set:
    impl = node.get("implementation", {}) or {}
    toks = {node["node_id"], node.get("label", "")}
    for k in ("approver", "role", "action", "form_field"):
        if impl.get(k):
            toks.add(str(impl[k]))
    out = set()
    for t in toks:
        out.add(t)
        out.add(_norm(t))
    return out


def _find_node(order: list[dict], token: str | None):
    if not token:
        return None
    tl = _norm(token)
    for n in order:
        toks = _node_tokens(n)
        if tl in toks or any(tl in t or t in tl for t in toks if t):
            return n
    return None


def configured_requirements(workflow: dict, case: dict) -> dict:
    """Static required[action] from workflow config (independent of reachability)."""
    out: dict = {}
    for node in workflow.get("nodes", []):
        impl = node.get("implementation", {}) or {}
        if "form_field" in impl or "action" in impl and impl.get("action") not in (None, "submit"):
            action = impl.get("action") or str(impl.get("form_field", "")).replace("_file", "")
            if impl.get("action") == "submit":
                continue
            req = bool(impl.get("required", False))
            rc = impl.get("required_condition")
            if rc:
                req = req and eval_condition(rc, case)
            if action:
                out[action] = req
    return out


def execute(workflow: dict, case: dict, ordering: list | None = None) -> dict:
    order = _ordered_nodes(workflow)
    trace, path = [], []
    eligible, on_time = True, True
    for node in order:
        nid = node["node_id"]
        impl = node.get("implementation", {}) or {}
        path.append(nid)
        if impl.get("kind") == "threshold_gate" and impl.get("field"):
            cond = {"field": impl["field"], "operator": impl.get("operator", ">="), "value": impl.get("value")}
            ok = eval_condition(cond, case)
            trace.append(f"{nid}: gate {cond} -> {'PASS' if ok else 'REJECT'}")
            if not ok:
                eligible = False
            continue
        if impl.get("kind") == "deadline_gate" and impl.get("field"):
            cond = {"field": impl["field"], "operator": impl.get("operator", "<="), "value": impl.get("value")}
            ok = eval_condition(cond, case)
            trace.append(f"{nid}: deadline {cond} -> {'ON_TIME' if ok else 'LATE'}")
            if not ok:
                on_time = False
            continue
        trace.append(f"{nid}: visit ({node.get('label')})")

    required = configured_requirements(workflow, case)

    order_ok = True
    for o in (ordering or []):
        a = _find_node(order, o.get("before"))
        b = _find_node(order, o.get("after"))
        if a and b:
            ids = [n["node_id"] for n in order]
            if ids.index(a["node_id"]) > ids.index(b["node_id"]):
                order_ok = False
                trace.append(f"ORDER VIOLATION: {o.get('before')} after {o.get('after')}")
        elif b and not a:
            order_ok = False
            trace.append(f"ORDER VIOLATION: missing prerequisite {o.get('before')}")

    return {"eligible": eligible, "required": required, "order_ok": order_ok,
            "on_time": on_time, "trace": trace, "path": path}
