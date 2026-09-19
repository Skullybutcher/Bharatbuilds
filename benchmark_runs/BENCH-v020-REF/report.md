# ProcessPatchBench v0.2.0 — run BENCH-v020-REF
29 total scenarios

- 20 AUTO_REPAIRED
- 4 CORRECTLY_ESCALATED
- 3 CORRECTLY_NO_OP
- 2 UNSUPPORTED

## Metrics

- auto_repair_rate: 0.69
- correct_noop_rate: 1.0
- correct_escalation_rate: 1.0
- extraction_accuracy: {'kind': 0.966, 'operator': 0.966, 'value': 0.966, 'condition': 0.966, 'source_span': 0.966}
- delta_classification_accuracy: 1.0
- witness_validity: 1.0
- witness_completeness: 1.0
- localization_recall: 1.0
- repair_success: 1.0
- preservation_rate: 1.0
- median_patch_cost: 3.0
- median_latency_ms: {'extraction_ms': 0.07, 'delta_ms': 0.01, 'witness_ms': 0.11, 'localize_ms': 0.01, 'repair_ms': 0.36}
- provenance_coverage: 1.0

## Per-case results

- THRESH-RELAX-001 [threshold_relaxation/dev] AUTO_REPAIRED
- THRESH-TIGHTEN-001 [threshold_tightening/dev] AUTO_REPAIRED
- REQ-REMOVE-001 [requirement_removed/dev] AUTO_REPAIRED
- REQ-ADD-001 [requirement_added/dev] AUTO_REPAIRED
- COND-001 [conditional_requirement/dev] AUTO_REPAIRED
- EXC-ADD-001 [exception_added/dev] AUTO_REPAIRED
- ORDER-001 [ordering_change/dev] AUTO_REPAIRED
- PRE-ADD-001 [prerequisite_added/dev] AUTO_REPAIRED
- DL-EXT-001 [deadline_extended/dev] AUTO_REPAIRED
- NOOP-PARA-001 [semantic_paraphrase/dev] CORRECTLY_NO_OP
- NOOP-RENUM-001 [section_renumbering/dev] CORRECTLY_NO_OP
- AMBIG-001 [ambiguity/dev] CORRECTLY_ESCALATED
- CONFL-001 [contradiction/dev] CORRECTLY_ESCALATED
- THRESH-RELAX-002 [threshold_relaxation/eval] AUTO_REPAIRED
- THRESH-TIGHTEN-002 [threshold_tightening/eval] AUTO_REPAIRED
- REQ-REMOVE-002 [requirement_removed/eval] AUTO_REPAIRED
- REQ-ADD-002 [requirement_added/eval] AUTO_REPAIRED
- COND-002 [conditional_requirement/eval] AUTO_REPAIRED
- EXC-REMOVE-001 [exception_removed/eval] AUTO_REPAIRED
- ORDER-002 [ordering_change/eval] AUTO_REPAIRED
- DL-TIGHT-001 [deadline_tightened/eval] AUTO_REPAIRED
- NOOP-IRREL-001 [irrelevant_edit/eval] CORRECTLY_NO_OP
- AMBIG-002 [ambiguity/eval] CORRECTLY_ESCALATED
- CONFL-002 [contradiction/eval] CORRECTLY_ESCALATED
- COMPOUND-001 [compound_amendment/eval] AUTO_REPAIRED
- EXC-ADD-002 [exception_added/eval] AUTO_REPAIRED
- PROH-001 [prohibition_added/dev] AUTO_REPAIRED
- UNSUP-TEMP-001 [unsupported_temporal/dev] UNSUPPORTED —  None None None
- UNSUP-NEST-001 [unsupported_nested/eval] UNSUPPORTED —  None None None

Honest summary: failures above are real gaps, not hidden. See 57C.11.

Methodology: extraction is scored against POLICY TEXT; downstream
compiler/repair stages run on hand-authored GOLD RULE IR so extraction
errors do not contaminate repair metrics. Do not cite these numbers as
'raw-NL end-to-end repair'. Eval split is held-out authored, not
independent real-world data.