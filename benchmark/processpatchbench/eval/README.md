# Eval split

Held-out-style cases are marked `"split": "eval"` in each case's meta.json
(13 of 26). Do not tune repair heuristics against them and then report them
as independent evidence (57C.15). Run eval only via
`python scripts/benchmark.py --split eval`.
