# Multi-procedure workspaces — compile amendments against ANY procedure

The registry always supported workspaces and immutable procedure versions;
they were only reachable through the two demo domains. They are now a first-
class API/UI surface, so ProcessPatch works for **any** procedure graph, not
just the demos.

## API

| Route | Purpose |
|---|---|
| `GET /workspaces` | list workspaces |
| `POST /workspaces` `{name}` | create one |
| `GET /procedures[?workflow_id=…]` | list registered procedure versions |
| `POST /procedures` `{procedure: {…graph…}}` | register a graph as an immutable **active** version |
| `POST /builds` `{procedure_version_id, old_rules, new_rules, …}` | compile an amendment against that version |

## Rules

- **Fail-closed registration**: `POST /procedures` runs the full DAG
  integrity check (`validate_dag`) — cycles, dangling edges, duplicate edges,
  multiple/unreachable start nodes are rejected with `INVALID_WORKFLOW` (409).
  An unparseable or inconsistent graph can never become a compile target.
- **Immutability preserved**: registering an existing
  `procedure_version_id` is rejected (versions are append-only); patched
  versions minted by the pipeline keep their `-PATCH-<hash>` ids.
- **Explicit targeting wins**: in `POST /builds`, an explicit
  `procedure_version_id` is resolved from the registry; `procedure` (inline
  graph) and demo `domain` remain supported for compatibility, in that
  precedence order.
- Same storage abstraction as everything else (`workspaces.json` /
  `procedure_versions.json` locally, the DynamoDB single table on Lambda).
- Auth: creating workspaces / registering procedures / starting builds are
  writes (require `pp-reviewers`+); reads require any signed-in identity.

## UI

The **Builds** tab now shows registered procedure versions (with one-click
"Compile amendment"), a JSON registration form, and workspace creation. The
Overview tab is unchanged for the demo domains.

## Example

```bash
curl -X POST $API/procedures -H 'Content-Type: application/json' -d '{
  "procedure": {
    "workflow_id": "WF-MY", "procedure_version_id": "WF-MY-V1",
    "nodes": [
      {"node_id": "NODE-START", "type": "start", "label": "Start", "implementation": {}},
      {"node_id": "NODE-GATE",  "type": "gate",  "label": "Check cgpa",
       "implementation": {"kind": "threshold_gate", "field": "cgpa", "operator": ">=", "value": 8.0}},
      {"node_id": "NODE-SUBMIT","type": "action","label": "Submit", "implementation": {"action": "submit"}}
    ],
    "edges": [
      {"from": "NODE-START", "to": "NODE-GATE", "type": "NEXT", "condition": null},
      {"from": "NODE-GATE",  "to": "NODE-SUBMIT","type": "NEXT", "condition": null}
    ]
  }
}'
curl -X POST $API/builds -H 'Content-Type: application/json' \
  -d '{"procedure_version_id": "WF-MY-V1", "old_rules": [...], "new_rules": [...]}'
```

Witnesses, impact, patch, certificate, and the three human gates work
identically for custom procedures — the pipeline is domain-agnostic by design.
