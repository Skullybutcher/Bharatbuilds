# ProcessPatchBench v0.1.0 — run BENCH-v010-REF
26 total scenarios

- 19 AUTO_REPAIRED
- 4 CORRECTLY_ESCALATED
- 3 CORRECTLY_NO_OP

## Metrics

- auto_repair_rate: 0.731
- correct_noop_rate: 1.0
- correct_escalation_rate: 1.0
- extraction_accuracy: {'kind': 1.0, 'operator': 1.0, 'value': 1.0, 'condition': 1.0, 'source_span': 1.0}
- delta_classification_accuracy: 1.0
- witness_validity: 1.0
- witness_completeness: 1.0
- localization_recall: 1.0
- repair_success: 1.0
- preservation_rate: 1.0
- median_patch_cost: 3.0
- median_latency_s: {'extraction': 0.0, 'delta': 0.0, 'witness': 0.0, 'localize': 0.0, 'repair': 0.0}
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

Honest summary: failures above are real gaps, not hidden. See 57C.11.