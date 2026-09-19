"""Patch synthesizer: constrained, localized candidate patches (no full rewrite).

Supported: threshold/deadline CHANGE_CONDITION; required<->conditional
CHANGE_REQUIRED_FLAG + ADD_GATE; exception carve-outs; ADD_PREREQUISITE /
MOVE_NODE reordering; ADD_NODE for genuinely missing steps.
"""
from __future__ import annotations
import copy

W1, W2, W3, W4 = 3.0, 1.0, 2.0, 1.0


def _cost(ops: list[dict]) -> float:
    n = sum(1 for o in ops if o.get("op") in ("ADD_NODE", "REMOVE_NODE", "MOVE_NODE"))
    e = sum(1 for o in ops if o.get("op") in ("ADD_EDGE", "REMOVE_EDGE"))
    c = sum(1 for o in ops if o.get("op") in ("CHANGE_CONDITION", "ADD_GATE", "ADD_PREREQUISITE", "REMOVE_PREREQUISITE"))
    f = sum(1 for o in ops if o.get("op") in ("CHANGE_REQUIRED_FLAG",))
    return W1 * n + W2 * e + W3 * c + W4 * f


def required_for_action(model, oblig: dict, action: str) -> bool:
    """Could this obligation ever require the action (for some case)?"""
    from services.compiler.compiler import required_for
    if oblig.get("mode") == "always_true":
        return True
    if oblig.get("mode") == "conditional":
        probe: dict = {}
        from services.workflow.expr import iter_comparisons
        for leaf in iter_comparisons(oblig.get("condition")):
            f, op, v = leaf.get("field"), leaf.get("operator"), leaf.get("value")
            if op in (">=", ">"):
                probe[f] = v
            elif op in ("<=", "<"):
                probe[f] = v if op == "<=" else (v - 0.01 if isinstance(v, (int, float)) else v)
            elif op == "==":
                probe[f] = v
        probe.setdefault("cgpa", 7.0)
        probe.setdefault("amount", 40000)
        return bool(required_for(oblig, model.exceptions, action, probe))
    return False


def _splice_before(patched: dict, ops: list, anchor: str | None, new_id: str, target_role: str = "submit"):
    """Insert new_id immediately before the first node matching target_role
    (default: submit): preds(target) -> new -> target. Mandatory steps must
    never dangle after the terminal node."""
    from services.workflow.interpreter import _ordered_nodes, _find_node
    order = _ordered_nodes(patched)
    target = _find_node(order, target_role)
    node_ids = {n["node_id"] for n in patched.get("nodes", [])}
    if anchor is not None and anchor not in node_ids:
        # anchor is a conventional name; fall back to an actual start node —
        # never the new node itself (that would be a self-loop).
        indeg = {nid: 0 for nid in node_ids}
        for e in patched.get("edges", []):
            if e.get("to") in indeg:
                indeg[e["to"]] += 1
        starts = sorted(nid for nid, d in indeg.items() if d == 0 and nid != new_id)
        anchor = starts[0] if starts else None
    if target is None:
        if anchor:
            ops.append({"op": "ADD_EDGE", "from": anchor, "to": new_id})
            patched["edges"].append({"from": anchor, "to": new_id, "type": "NEXT", "condition": None})
        return
    tid = target["node_id"]
    preds = [e["from"] for e in patched.get("edges", []) if e["to"] == tid and e["from"] != new_id]
    patched["edges"] = [e for e in patched.get("edges", [])
                        if not (e["from"] in preds and e["to"] == tid)]
    for p in preds:
        patched["edges"].append({"from": p, "to": new_id, "type": "NEXT", "condition": None})
        ops.append({"op": "ADD_EDGE", "from": p, "to": new_id})
        ops.append({"op": "REMOVE_EDGE", "from": p, "to": tid})
    patched["edges"].append({"from": new_id, "to": tid, "type": "NEXT", "condition": None})
    ops.append({"op": "ADD_EDGE", "from": new_id, "to": tid})


def _retarget_links(node: dict, rule_id: str | None):
    if not rule_id:
        return
    links = [L for L in node.get("provenance_links", []) if L.get("type") != "IMPLEMENTS_RULE"]
    links.append({"type": "IMPLEMENTS_RULE", "target": rule_id})
    node["provenance_links"] = links


def propose(model, workflow: dict, faults: list[dict]) -> dict:
    ops: list[dict] = []
    patched = copy.deepcopy(workflow)
    nodes = {n["node_id"]: n for n in patched.get("nodes", [])}
    kinds = {f.get("kind") for f in faults}

    # 1. eligibility/deadline gates: align to model
    if kinds & {"wrong_rejection", "wrong_acceptance", "deadline_mismatch"}:
        targets = {}
        for c in model.eligibility:
            if c.get("field"):
                targets[c["field"]] = {"operator": c["operator"], "value": c["value"], "rule": c.get("_rule")}
        for d in model.deadlines:
            targets[d["field"]] = {"operator": d["operator"], "value": d["value"], "rule": d["rule_id"]}
        for n in patched.get("nodes", []):
            impl = n.get("implementation", {}) or {}
            if impl.get("kind") in ("threshold_gate", "deadline_gate") and impl.get("field") in targets:
                t = targets[impl["field"]]
                if impl.get("operator") != t["operator"] or impl.get("value") != t["value"]:
                    ops.append({"op": "CHANGE_CONDITION", "node_id": n["node_id"],
                                "old": {"operator": impl.get("operator"), "value": impl.get("value")},
                                "new": {"operator": t["operator"], "value": t["value"]}})
                    impl["operator"], impl["value"] = t["operator"], t["value"]
                    _retarget_links(n, t.get("rule"))

    # 2. step requirements: align each workflow action to the obligation model
    if kinds & {"unnecessary_burden", "missing_safeguard"}:
        for n in patched.get("nodes", []):
            impl = n.get("implementation", {}) or {}
            action = impl.get("action") or (str(impl.get("form_field", "")).replace("_file", "") if "form_field" in impl else None)
            if not action or impl.get("action") == "submit":
                continue
            oblig = (model.obligations or {}).get(action)
            if oblig is None:
                continue
            # fold exceptions into the required condition: waived when ANY
            # exception holds -> required iff base AND NOT(e1 OR e2 ...).
            excs = [e["condition"] for e in model.exceptions if e.get("action") in (action, "*", None) and e.get("condition")]
            if oblig["mode"] == "always_true" and not excs:
                new_req, new_cond = True, None
            elif oblig["mode"] == "always_false" and not excs:
                new_req, new_cond = False, None
            else:
                base = oblig.get("condition") if oblig.get("mode") == "conditional" else None
                exc_or = excs[0] if len(excs) == 1 else {"or": excs}
                if oblig["mode"] == "always_true":
                    base = {"not": exc_or}
                elif excs:
                    base = {"and": ([base] if base else []) + [{"not": exc_or}]}
                new_req, new_cond = True, base
            if impl.get("required") != new_req or impl.get("required_condition") != new_cond:
                ops.append({"op": "CHANGE_REQUIRED_FLAG", "node_id": n["node_id"],
                            "field": impl.get("form_field", action),
                            "old": {"required": impl.get("required"), "required_condition": impl.get("required_condition")},
                            "new": {"required": new_req, "required_condition": new_cond},
                            "rationale": f"IMPLEMENTS_RULE {oblig.get('rule_id')}"})
                impl["required"] = new_req
                impl["required_condition"] = new_cond
                _retarget_links(n, oblig.get("rule_id"))
                if new_cond:
                    ops.append({"op": "ADD_GATE", "node_id": n["node_id"], "condition": new_cond})

    # 2c. removed obligations: workflow still requires an action the model
    # no longer obligates anywhere -> relax to not required.
    if kinds & {"unnecessary_burden"}:
        required_actions = set()
        for n in patched.get("nodes", []):
            impl = n.get("implementation", {}) or {}
            act = impl.get("action") or (str(impl.get("form_field", "")).replace("_file", "") if "form_field" in impl else None)
            if act and act != "submit":
                required_actions.add(act)
        for action in sorted(required_actions - set((model.obligations or {}))):
            if not any(f.get("kind") == "unnecessary_burden" and f.get("key") == action for f in faults):
                continue
            for n in patched.get("nodes", []):
                impl = n.get("implementation", {}) or {}
                act = impl.get("action") or (str(impl.get("form_field", "")).replace("_file", "") if "form_field" in impl else None)
                if act == action and impl.get("required"):
                    ops.append({"op": "CHANGE_REQUIRED_FLAG", "node_id": n["node_id"],
                                "field": impl.get("form_field", action),
                                "old": {"required": True, "required_condition": impl.get("required_condition")},
                                "new": {"required": False, "required_condition": None},
                                "rationale": "obligation removed in active rules"})
                    impl["required"] = False
                    impl["required_condition"] = None
    # 2b. genuinely missing steps: obligation with no workflow node at all
    if kinds & {"missing_safeguard"}:
        have_actions = set()
        for n in patched.get("nodes", []):
            impl = n.get("implementation", {}) or {}
            act = impl.get("action") or (str(impl.get("form_field", "")).replace("_file", "") if "form_field" in impl else None)
            if act:
                have_actions.add(act)
        for action, oblig in (model.obligations or {}).items():
            if action in have_actions:
                continue
            if not required_for_action(model, oblig, action):
                continue
            nid = "NODE-" + action.upper().replace(" ", "-")
            ops.append({"op": "ADD_NODE", "node_id": nid, "label": action.replace("_", " ").title(),
                        "implementation": {"form_field": action + "_file", "action": action,
                                           "required": True, "required_condition": oblig.get("condition")},
                        "rationale": f"IMPLEMENTS_RULE {oblig.get('rule_id')}"})
            patched["nodes"].append({"node_id": nid, "workflow_id": patched.get("workflow_id"),
                                     "type": "action", "label": action.replace("_", " ").title(),
                                     "preconditions": [], "postconditions": [f"{action} = true"],
                                     "implementation": {"form_field": action + "_file", "action": action,
                                                        "required": True, "required_condition": oblig.get("condition")},
                                     "provenance_links": [{"type": "IMPLEMENTS_RULE", "target": oblig.get("rule_id")}]})
            # Structural placement: mandatory steps go BEFORE submit, never after.
            _splice_before(patched, ops, anchor=None, new_id=nid, target_role="submit")

    # 3. ordering: move prerequisite before target; add node if prerequisite missing
    if "wrong_journey" in kinds:
        from services.workflow.interpreter import _ordered_nodes, _find_node
        order = _ordered_nodes(patched)
        ids = [n["node_id"] for n in order]
        for o in model.ordering:
            a = _find_node(order, o.get("before"))
            b = _find_node(order, o.get("after"))
            if a and b and ids.index(a["node_id"]) > ids.index(b["node_id"]):
                ops.append({"op": "MOVE_NODE", "node_id": a["node_id"], "anchor": {"before": b["node_id"]},
                            "rationale": f"IMPLEMENTS_RULE {o.get('rule_id')}"})
                ids.remove(a["node_id"])
                ids.insert(ids.index(b["node_id"]), a["node_id"])
                ops.append({"op": "ADD_PREREQUISITE", "prerequisite": o["before"], "target": o["after"],
                            "rationale": f"IMPLEMENTS_RULE {o.get('rule_id')}"})
                # Physically splice a before b so re-execution observes the order.
                edges = patched.get("edges", [])
                preds_b = [e["from"] for e in edges if e["to"] == b["node_id"] and e["from"] != a["node_id"]]
                succs_a = [e["to"] for e in edges if e["from"] == a["node_id"] and e["to"] != b["node_id"]]
                edges = [e for e in edges
                         if not (e["from"] in preds_b and e["to"] == b["node_id"])
                         and not (e["from"] == a["node_id"] and e["to"] in succs_a)
                         and not ({e["from"], e["to"]} == {a["node_id"], b["node_id"]})]
                if any(e["from"] == b["node_id"] and e["to"] == a["node_id"] for e in patched.get("edges", [])):
                    ops.append({"op": "REMOVE_EDGE", "from": b["node_id"], "to": a["node_id"]})
                for p in preds_b:
                    edges.append({"from": p, "to": a["node_id"], "type": "NEXT", "condition": None})
                    ops.append({"op": "ADD_EDGE", "from": p, "to": a["node_id"]})
                    ops.append({"op": "REMOVE_EDGE", "from": p, "to": b["node_id"]})
                edges.append({"from": a["node_id"], "to": b["node_id"], "type": "NEXT", "condition": None})
                ops.append({"op": "ADD_EDGE", "from": a["node_id"], "to": b["node_id"]})
                for s in succs_a:
                    edges.append({"from": b["node_id"], "to": s, "type": "NEXT", "condition": None})
                    ops.append({"op": "ADD_EDGE", "from": b["node_id"], "to": s})
                    ops.append({"op": "REMOVE_EDGE", "from": a["node_id"], "to": s})
                patched["edges"] = edges
            elif b and not a:
                nid = "NODE-" + str(o.get("before", "step")).upper().replace(" ", "-")
                ops.append({"op": "ADD_NODE", "node_id": nid, "label": str(o.get("before")),
                            "implementation": {"approver": o.get("before")},
                            "rationale": f"IMPLEMENTS_RULE {o.get('rule_id')}"})
                patched["nodes"].append({"node_id": nid, "workflow_id": patched.get("workflow_id"),
                                         "type": "approval", "label": str(o.get("before")),
                                         "preconditions": [], "postconditions": [],
                                         "implementation": {"approver": o.get("before")},
                                         "provenance_links": [{"type": "IMPLEMENTS_RULE", "target": o.get("rule_id")}]})
                _splice_before(patched, ops, anchor=None, new_id=nid,
                               target_role=o.get("after", "submit"))
                ops.append({"op": "ADD_PREREQUISITE", "prerequisite": o["before"], "target": o["after"]})

    # 4. deadlines: add a deadline gate when the workflow has none for the field
    have_dl = {n.get("implementation", {}).get("field") for n in patched.get("nodes", [])
               if (n.get("implementation", {}) or {}).get("kind") == "deadline_gate"}
    for d in model.deadlines:
        if d["field"] not in have_dl and any(f.get("kind") == "deadline_mismatch" for f in faults):
            nid = "NODE-DEADLINE-GATE"
            ops.append({"op": "ADD_NODE", "node_id": nid, "label": "Check Submission Deadline",
                        "implementation": {"kind": "deadline_gate", "field": d["field"],
                                           "operator": d["operator"], "value": d["value"]},
                        "rationale": f"IMPLEMENTS_RULE {d['rule_id']}"})
            patched["nodes"].append({"node_id": nid, "workflow_id": patched.get("workflow_id"),
                                     "type": "gate", "label": "Check Submission Deadline",
                                     "preconditions": [], "postconditions": ["deadline_checked = true"],
                                     "implementation": {"kind": "deadline_gate", "field": d["field"],
                                                        "operator": d["operator"], "value": d["value"]},
                                     "provenance_links": [{"type": "IMPLEMENTS_RULE", "target": d["rule_id"]}]})
            _splice_before(patched, ops, anchor="NODE-START", new_id=nid, target_role="submit")

    # 5. prohibitions: add an enforcement gate that BLOCKS (not rejects) when
    # the forbidden condition holds. Never touches eligibility semantics.
    breached = [f for f in faults if f.get("kind") == "prohibition_breach"]
    if breached:
        from services.workflow.expr import iter_comparisons
        have_pg = {(n.get("implementation", {}) or {}).get("field")
                   for n in patched.get("nodes", [])
                   if (n.get("implementation", {}) or {}).get("kind") == "prohibition_gate"}
        for p in model.prohibitions:
            leaves = list(iter_comparisons(p.get("condition")))
            if len(leaves) != 1:
                continue  # compound prohibitions need human design
            leaf = leaves[0]
            if leaf.get("field") in have_pg:
                continue
            nid = f"NODE-PROHIBIT-{str(leaf.get('field')).upper()}"
            ops.append({"op": "ADD_NODE", "node_id": nid, "label": f"Enforce {p['rule_id']}",
                        "implementation": {"kind": "prohibition_gate", "field": leaf.get("field"),
                                           "operator": leaf.get("operator"), "value": leaf.get("value"),
                                           "rule": p["rule_id"]},
                        "rationale": f"IMPLEMENTS_RULE {p['rule_id']}"})
            patched["nodes"].append({"node_id": nid, "workflow_id": patched.get("workflow_id"),
                                     "type": "gate", "label": f"Enforce {p['rule_id']}",
                                     "preconditions": [], "postconditions": ["prohibition_checked = true"],
                                     "implementation": {"kind": "prohibition_gate", "field": leaf.get("field"),
                                                        "operator": leaf.get("operator"), "value": leaf.get("value"),
                                                        "rule": p["rule_id"]},
                                     "provenance_links": [{"type": "IMPLEMENTS_RULE", "target": p["rule_id"]}]})
            _splice_before(patched, ops, anchor="NODE-START", new_id=nid, target_role="submit")

    patched["procedure_version_id"] = (patched.get("procedure_version_id", "WF") or "WF") + "-PATCHED"
    return {"patch_id": "PATCH-0001", "operations": ops, "cost": _cost(ops),
            "cost_breakdown": "w1*nodes + w2*edges + w3*conds + w4*fields",
            "patched_workflow": patched,
            "strategy": "smallest validated candidate found (localized; not claimed globally minimal)"}


def apply_patch(workflow: dict, patch: dict) -> dict:
    return patch.get("patched_workflow", workflow)
