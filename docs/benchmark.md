# ProcessPatchBench (57C) — v0.1.0, 26 scenarios (13 dev / 13 eval)

Families: threshold relax/tighten, requirement add/remove, conditional,
exception add/remove, ordering, prerequisite, deadline extend/tighten,
paraphrase/renumber/irrelevant no-ops, ambiguity, contradiction, compound.

## Validity bar per case

Real V1/V2 policy texts, hand-authored gold Rule IR, a stale (or correct)
procedure, gold delta / witness-domain / localization / repair files,
fail-closed expectations for ambiguity/conflict.

## Evaluation

`make benchmark` (or `python scripts/benchmark.py`) runs extraction scoring
(per-field), delta confusion, witness validity + domain completeness,
localization recall/precision, repair effect + forbidden-op + cost checks,
preservation, then classifies each case: AUTO_REPAIRED | CORRECTLY_NO_OP |
CORRECTLY_ESCALATED | UNSUPPORTED | FAILED_*. Artifacts:
`benchmark_runs/<id>/{manifest,results,metrics,report}.json|md` + failures/.

Reference: 19 auto-repaired, 3 correct no-ops, 4 correct escalations;
extraction/delta/witness/localization/repair/preservation all 1.0 (see
benchmark_runs reference run). Do not tune on eval and report it as
independent; benchmark version is pinned in BENCHMARK_VERSION (never silently
edit cases after reporting).
