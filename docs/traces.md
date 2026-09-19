# Runtime trace ingestion — real-world evidence, read-only

First step of the "what comes next" roadmap (runtime traces): the pipeline can
now ingest **executed decisions** from deployed systems and compare them with
what the deterministic engine says *should* happen.

## Doctrine (unchanged, extended)

Traces are **evidence, never truth**. A trace is one recorded execution of a
procedure for one case: the case fields, what the deployed system actually did
(`outcome`), and optionally which steps were performed. Ingestion validates and
stores; **comparison is read-only**. No trace ever becomes a verified witness
by itself — disagreement only nominates *candidate witnesses*, which acquire
witness status exclusively through the normal verified pipeline
(`find_witnesses` → patch → `validate`). This preserves the core rule:
**no red node without a verified witness**.

## Contract (`shared/schemas/trace.json`)

```json
POST /traces
{
  "case": {"cgpa": 7.8, "year": 3, "backlogs": 0, "category": "general",
            "submission_date": "2026-09-28"},
  "outcome": {"eligible": true, "on_time": true,
               "required": {"rec_file": false},
               "completed_actions": ["submit_form"]},
  "steps_done": ["NODE-FORM", "NODE-STEP"],
  "workflow_id": "WF-RESEARCH-GRANT",
  "procedure_version_id": "WF-V1",
  "source": "runtime-log | incident-export | manual",
  "source_ref": "opaque pointer into the source system",
  "occurred_at": "2026-09-18T10:00:00Z"
}
```

- `case` values must be scalars (the engine replays them literally).
- `outcome` booleans are coercion-tolerant at the edge (`"ELIGIBLE"`,
  `"late"`, `"blocked"`, `1/0` → boolean) but **reject** anything ambiguous —
  fail-closed, like every other boundary.
- `trace_id` is content-derived (`TRC-<hash>`): re-ingesting the same
  case/outcome is idempotent.

## Comparison

`GET /builds/{id}/trace-compare` replays each matching trace's case through
`services.workflow.interpreter.execute` against **both** the build's stale
procedure and the patched preview, then reports per-dimension agreement:

| dimension | trace field | engine field |
|---|---|---|
| eligibility | `outcome.eligible` | `execute(...).eligible` |
| timeliness | `outcome.on_time` | `execute(...).on_time` |
| prohibition | `outcome.prohibited` | `execute(...).prohibited` |
| required steps | `outcome.required{action}` | `execute(...).required{action}` |
| unmodeled actions | `outcome.completed_actions` | actions absent from the graph |

Verdicts per trace: `AGREE` / `DISAGREE` vs each graph, plus a note when a
trace **matches the patched preview but disagrees with the stale procedure**
— the strongest possible candidate-witness signal, because real-world evidence
and the deterministic model independently agree on what the fix should be.
Traces whose cases disagree with *both* graphs indicate model/context drift and
are flagged for human review, never silently dropped. Invalid workflows are
reported as `SKIPPED` with the reason (fail-closed, never swallowed).

## API surface

| Route | Purpose |
|---|---|
| `POST /traces` | ingest one trace (validated, idempotent) |
| `GET /traces[?workflow_id=…]` | list stored traces |
| `GET /traces/{trace_id}` | fetch one |
| `GET /builds/{id}/trace-compare` | read-only comparison for a build |

The UI's **Traces** tab shows the comparison summary, per-trace verdicts, an
inline ingestion form, and the stored list. Auth: ingesting requires
`pp-reviewers` (it is a write); reads require any signed-in identity.

## Storage

Same abstraction as everything else: `traces.json` locally, the DynamoDB
single table on Lambda (via `services.storage`). No new infrastructure.
