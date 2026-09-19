# ProcessPatchBench (57C) — v0.3.0, 31 scenarios (15 dev / 16 eval)

## Methodology (read before citing numbers)

ProcessPatchBench separately evaluates **policy extraction** and the
**deterministic repair pipeline**:

```text
POLICY TEXT → deterministic extractor → extraction score (per-field)
```

```text
GOLD RULE IR → compiler → witness → localizer → repair → regression
```

Downstream compiler/repair evaluation deliberately uses hand-authored gold Rule
IR so extraction errors do not contaminate repair metrics. Do NOT claim "raw
natural-language policies achieve 100% end-to-end repair" — that is not what
this benchmark demonstrates.

The 16-case eval split is a **held-out authored (frozen) evaluation split**,
authored by the same process as dev — not an independent external dataset of
unseen real-world policies. Later, external policies can become a stronger test.

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

Reference: 22 auto-repaired, 3 correct no-ops, 4 correct escalations,
2 correctly-flagged unsupported (temporal/nested language the bounded
grammar refuses);
extraction/delta/witness/localization/repair/preservation all 1.0 (see
benchmark_runs reference run). Do not tune on eval and report it as
independent; benchmark version is pinned in BENCHMARK_VERSION (never silently
edit cases after reporting).
