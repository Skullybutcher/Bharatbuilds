# ProcessPatchBench v0.1.0 — 26 heterogeneous scenarios (13 dev / 13 eval)

Families: threshold relax/tighten, requirement add/remove, conditional,
exception add/remove, ordering, prerequisite, deadline extend/tighten,
paraphrase/renumber/irrelevant no-ops, ambiguity, contradiction, compound.

Each case dir: meta.json, policy_v1.md, policy_v2.md, rules_v1.json,
rules_v2.json (gold Rule IR), procedure.json, gold_delta.json,
gold_witness.json (domain constraints), gold_localization.json,
gold_repair.json.

Author: `python benchmark/processpatchbench/author.py` (deterministic).
Run: `make benchmark`. Dev/eval split lives in meta.json (`eval/` holds
split documentation). Reference run: `benchmark_runs/BENCH-v010-REF`.
