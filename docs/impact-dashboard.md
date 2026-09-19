# Impact Dashboard (57A)

Answers: what changed, where it propagated, who is affected. Computed ONLY from
build artifacts — never `LLM_estimate(...)`.

## Data contract

`impact_summary` per build: semantic_changes + breakdown; artifacts
(workflows/nodes/forms/fields affected, unaffected); behavioral counts by
witness kind (verified only); test_cohort (label MUST say generated/synthetic,
plus newly_eligible/ineligible, shorter/longer journeys, unchanged);
verification (tests before/after, by suite, witnesses_verified,
provenance_coverage); approval (machine/human status).

## Metric provenance (examples)

- Wrong rejections = count(witnesses where kind == wrong_rejection and verified)
- Nodes affected = union(localizer affected_nodes)
- Workflows affected = 1 + registered workflows with provenance links to affected rules
- Newly eligible = cohort cases ineligible under old model, eligible under new

## UI

Cards (Semantic Change, Blast Radius, Human Impact, Regression State, Trust
State); every behavioral count drills to witnesses; every witness drills to
persona, traces, governing rule, source clause, node, patch op, replay.
Before/after table is shown only after validation. Multi-workflow propagation
follows typed IMPLEMENTS_RULE edges, not generic graph connectivity.
