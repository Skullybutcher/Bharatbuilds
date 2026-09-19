"""Workflow interpreter: executes a procedure DAG against a case (deterministic).

Real path execution (not visit-everything):
  START -> follow enabled edges -> gate reject/STOP is terminal ->
  conditional action skipped when not required -> SUBMIT terminal.
BRANCH edges carry a condition (dict, "field op value" string, or null=True).
Cycles, dangling refs, and duplicate edges are INVALID_WORKFLOW (never
silently tolerated via file-order fallback).

Node implementation shapes (all optional keys):
  {"kind":"threshold_gate","field","operator","value"}   fail -> STOP, eligible False
  {"kind":"deadline_gate","field","operator","value"}    fail -> STOP, on_time False
  {"kind":"prohibition_gate","field","operator","value","rule"}  holds -> STOP, prohibited True
  {"form_field": str, "action": str, "required": bool, "required_condition": cond}
  {"approver": token}            approval step
  {"action":"submit"}            submission step (terminal)
  {"role": token}                generic role tag used for ordering matching
"""
from __future__ import annotations
from services.workflow.expr import eval_condition


def _ordered_nodes(workflow: dict) -> list[dict]:
    """Topological order (used for analysis, NOT execution). Raises on cycles."""
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
    if len(order) != len(nodes):
        left = sorted(set(nodes) - {n["node_id"] for n in order})
        raise ValueError(f"INVALID_WORKFLOW: cycle detected involving {left}")
    return order


def validate_dag(workflow: dict) -> dict:
    """Graph integrity contract. Raises ValueError(INVALID_WORKFLOW) on any
    violation; returns stats otherwise."""
    nodes = {n["node_id"]: n for n in workflow.get("nodes", [])}
    edges = workflow.get("edges", [])
    for e in edges:
        if e.get("from") not in nodes:
            raise ValueError(f"INVALID_WORKFLOW: edge from unknown node {e.get('from')}")
        if e.get("to") not in nodes:
            raise ValueError(f"INVALID_WORKFLOW: edge to unknown node {e.get('to')}")
    seen = set()
    for e in edges:
        key = (e.get("from"), e.get("to"), str(e.get("condition")))
        if key in seen:
            raise ValueError(f"INVALID_WORKFLOW: duplicate edge {key}")
        seen.add(key)
    order = _ordered_nodes(workflow)  # raises on cycle
    starts = [n["node_id"] for n in workflow.get("nodes", [])
              if not any(e.get("to") == n["node_id"] for e in edges)]
    if len(starts) != 1:
        raise ValueError(f"INVALID_WORKFLOW: expected exactly 1 start node, found {len(starts)} {starts}")
    # reachability from starts
    adj = {}
    for e in edges:
        adj.setdefault(e["from"], []).append(e["to"])
    seen_nodes, stack = set(), list(starts)
    while stack:
        nid = stack.pop()
        if nid in seen_nodes:
            continue
        seen_nodes.add(nid)
        stack.extend(adj.get(nid, []))
    orphans = sorted(set(nodes) - seen_nodes)
    if orphans:
        raise ValueError(f"INVALID_WORKFLOW: unreachable nodes {orphans}")
    return {"nodes": len(nodes), "edges": len(edges), "starts": starts}


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
        if tl in toks:
            return n
        # word-level fallback (never raw substring: "submit" must not match
        # "Check Submission Deadline")
        for t in toks:
            if not t:
                continue
            wt = t.split()
            if tl in wt or (len(wt) == 1 and wt[0] in tl.split()):
                return n
    return None


def _parse_edge_cond(cond) -> dict | None:
    if cond is None:
        return None
    if isinstance(cond, dict):
        return cond
    if isinstance(cond, str):
        import re
        m = re.match(r"\s*([A-Za-z_][\w]*)\s*(>=|<=|>|<|==|!=)\s*(.+?)\s*$", cond)
        if m:
            return {"field": m.group(1), "operator": m.group(2), "value": _lit(m.group(3))}
    return None


def _lit(s: str):
    s = s.strip().strip("'\"")
    try:
        return float(s) if "." in s else int(s.replace(",", ""))
    except ValueError:
        return s


def _edge_enabled(edge: dict, case: dict) -> bool:
    if edge.get("type") == "BRANCH":
        cond = _parse_edge_cond(edge.get("condition"))
        return True if cond is None else bool(eval_condition(cond, case))
    return True


def configured_requirements(workflow: dict, case: dict) -> dict:
    """Static required[action] from workflow config (independent of reachability)."""
    out: dict = {}
    for node in workflow.get("nodes", []):
        impl = node.get("implementation", {}) or {}
        if "form_field" in impl or ("action" in impl and impl.get("action") not in (None, "submit")):
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
    validate_dag(workflow)
    nodes = {n["node_id"]: n for n in workflow.get("nodes", [])}
    out_edges: dict[str, list] = {}
    indeg = {nid: 0 for nid in nodes}
    for e in workflow.get("edges", []):
        out_edges.setdefault(e["from"], []).append(e)
        indeg[e["to"]] += 1
    starts = [nid for nid, d in indeg.items() if d == 0]

    trace, path = [], []
    eligible, on_time, prohibited = True, True, False
    required: dict = {}
    visited: set = set()
    # BFS over enabled edges (supports diamond branches + joins).
    frontier = list(starts)
    stopped_early = False
    while frontier:
        nid = frontier.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        node = nodes[nid]
        impl = node.get("implementation", {}) or {}

        if impl.get("kind") == "threshold_gate" and impl.get("field"):
            cond = {"field": impl["field"], "operator": impl.get("operator", ">="), "value": impl.get("value")}
            ok = eval_condition(cond, case)
            trace.append(f"{nid}: gate {cond} -> {'PASS' if ok else 'REJECT STOP'}")
            path.append(nid)
            if not ok:
                eligible = False
                stopped_early = True
                continue  # terminal: do not follow outgoing edges
            frontier.extend(e["to"] for e in out_edges.get(nid, []) if _edge_enabled(e, case))
            continue
        if impl.get("kind") == "deadline_gate" and impl.get("field"):
            cond = {"field": impl["field"], "operator": impl.get("operator", "<="), "value": impl.get("value")}
            ok = eval_condition(cond, case)
            trace.append(f"{nid}: deadline {cond} -> {'ON_TIME' if ok else 'LATE STOP'}")
            path.append(nid)
            if not ok:
                on_time = False
                stopped_early = True
                continue
            frontier.extend(e["to"] for e in out_edges.get(nid, []) if _edge_enabled(e, case))
            continue
        if impl.get("kind") == "prohibition_gate" and impl.get("field"):
            cond = {"field": impl["field"], "operator": impl.get("operator", ">"), "value": impl.get("value")}
            holds = eval_condition(cond, case)
            trace.append(f"{nid}: prohibition {cond} -> {'BLOCKED STOP' if holds else 'clear'}")
            path.append(nid)
            if holds:
                prohibited = True
                stopped_early = True
                continue
            frontier.extend(e["to"] for e in out_edges.get(nid, []) if _edge_enabled(e, case))
            continue
        if "form_field" in impl:
            action = impl.get("action") or str(impl.get("form_field", "")).replace("_file", "")
            req = bool(impl.get("required", False))
            rc = impl.get("required_condition")
            if rc:
                req = req and eval_condition(rc, case)
            if not req and rc is not None:
                trace.append(f"{nid}: skip {action} (condition false)")
                if action:
                    required[action] = False
                # Skipped steps are not part of the journey, but traversal continues.
                frontier.extend(e["to"] for e in out_edges.get(nid, []) if _edge_enabled(e, case))
                continue
            trace.append(f"{nid}: do {action} (required={req})")
            path.append(nid)
            if action:
                required[action] = req
            frontier.extend(e["to"] for e in out_edges.get(nid, []) if _edge_enabled(e, case))
            continue
        trace.append(f"{nid}: visit ({node.get('label')})")
        path.append(nid)
        if impl.get("action") == "submit":
            continue  # terminal
        frontier.extend(e["to"] for e in out_edges.get(nid, []) if _edge_enabled(e, case))

    order = _ordered_nodes(workflow)
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
        # runtime check: submit reached without the prerequisite visited
        if b and b["node_id"] in path and (not a or a["node_id"] not in path):
            order_ok = False
            trace.append(f"ORDER VIOLATION (runtime): {o.get('before')} not visited before submit")

    return {"eligible": eligible, "required": required, "order_ok": order_ok,
            "on_time": on_time, "prohibited": prohibited, "trace": trace, "path": path,
            "stopped_early": stopped_early}
