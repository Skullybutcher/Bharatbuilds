# Benchmark v0.4 proposals — new case families

Status: **proposal only — no code changed**. The implementer authors these in
`benchmark/processpatchbench/author.py` (helpers `R`, `GATE`, `STEP`, `APPR`,
`WF`, `linear`), regenerates cases, bumps `BENCHMARK_VERSION`, and freezes a
new reference run. Recommend all new cases land in the **eval** split: every
family below uses a domain unseen in dev, which is exactly what makes a
held-out split credible.

Language constraint (from `docs/rule-ir.md` + `author.py`): rule kinds
threshold / obligation / conditional_obligation / exception / prerequisite /
deadline / prohibition; condition operators `>= <= > < == != IN NOT_IN`;
sampler covers numeric/date/enum fragments. Every proposal below stays inside
that envelope. Where a family needs witness variables beyond `cgpa`/`amount`
(currently hardcoded in `meta.json`), it is flagged for the implementer.

## Family 1 — `visa_threshold` (immigration salary rules)

Real-world grounding: the UK raised the Skilled Worker general salary
threshold from £26,200 to £38,700 on 4 April 2024 and replaced the Shortage
Occupation List with a new Immigration Salary List carrying a 20% discount
(HC 590 explanatory memorandum:
https://assets.publishing.service.gov.uk/media/65f18e90133c22b8eecd3893/E03091226_-__HC_590__-_EXPLANATORY_MEMORANDUM__Web_Accessible_.pdf ;
list itself:
https://www.gov.uk/government/publications/skilled-worker-visa-immigration-salary-list/skilled-worker-visa-immigration-salary-list).
Thresholds move by statute; list membership moves by committee review — both
frequently, both with real refusals at stake.

Exercises: **threshold** + **IN-list exception**. Needs `salary` (integer) and
`occupation` (enum) witness variables.

Scenario A — `VISA-THRESH-001` (threshold tightened → `wrong_acceptance`).
Old: `R("R-SAL-V1", "threshold", "eligible",
{"field": "salary", "operator": ">=", "value": 26200}, ...)`.
New: `R("R-SAL-V2", "threshold", "eligible",
{"field": "salary", "operator": ">=", "value": 38700}, ..., sup="R-SAL-V1")`.
Stale procedure gates on 26200. Gold witness: `{"kinds": ["wrong_acceptance"],
"domains": {"wrong_acceptance": [{"field": "salary", "operator": ">=",
"value": 38700}, ...]}}` — wait, direction: stale accepts at 26200 what V2
rejects below 38700, so the domain is salary in [26200, 38700):
`[{"field": "salary", "operator": ">=", "value": 26200},
{"field": "salary", "operator": "<", "value": 38700}]`.
Gold repair: `{"required_effect": {"gate": {"field": "salary", "operator":
">=", "value": 38700}}, ...}`.

Scenario B — `VISA-LIST-001` (occupation leaves the discount list →
`wrong_acceptance`). Old: exception `upload nothing extra IF occupation IN
[LIST]` granting the 20% discount threshold, e.g.
`R("R-ISL-V1", "exception", "discount_rate", {"field": "occupation",
"operator": "IN", "value": ["CARE", "NURSE"], "datatype": "enum"}, ...)`.
New: list shrinks to `["NURSE"]`. Stale procedure still discounts CARE
applicants. Gold witness: `{"kinds": ["wrong_acceptance"], "domains":
{"wrong_acceptance": [{"field": "occupation", "operator": "==", "value":
"CARE"}]}}`. Gold repair: `required_effect` with the narrowed `IN` gate.

Credibility: first income-threshold domain outside reimbursement, plus the
first threshold×list interaction — both unseen in dev.

## Family 2 — `trial_eligibility` (clinical-trial inclusion criteria)

Real-world grounding: Tufts CSDD (2022 follow-up, 950 protocols, 2,188
amendments) found amendment prevalence at 57–76%, a mean of 3.3 amendments
per protocol, sites operating 215 days on mismatched protocol versions — with
modifying volunteer eligibility criteria the top reason for amending:
https://doi.org/10.21203/rs.3.rs-3168679/v1
A stale screening procedure here wrongly turns away real patients.

Exercises: **interval threshold** + **NOT_IN exclusion**. Needs `age`
(integer 0–120) and `condition` (enum) witness variables.

Scenario A — `TRIAL-AGE-001` (interval widened → `wrong_rejection`). Old:
threshold `age >= 18` plus implicit cap via second gate `age <= 65`
(author as two threshold rules, matching how the compiler conjoins
eligibility AND-gates). New: cap moves to 75. Stale procedure rejects a
70-year-old the amended protocol accepts. Gold witness: `{"kinds":
["wrong_rejection"], "domains": {"wrong_rejection": [{"field": "age",
"operator": ">", "value": 65}, {"field": "age", "operator": "<=",
"value": 75}]}}`. Gold repair: second gate to `<= 75`.

Scenario B — `TRIAL-EXCL-001` (new exclusion → `wrong_acceptance`). Old: no
comorbidity rule. New: `R("R-CX-V2", "threshold", "eligible",
{"field": "condition", "operator": "NOT_IN", "value": ["DIABETES",
"RENAL"], "datatype": "enum"}, "condition NOT_IN [...]", ...)`. Stale
procedure enrolls a diabetic volunteer the amendment excludes. Gold witness:
`{"kinds": ["wrong_acceptance"], "domains": {"wrong_acceptance":
[{"field": "condition", "operator": "==", "value": "DIABETES"}]}}`. Gold
repair: `{"required_effect": {"exclusion_gate": {"field": "condition",
"operator": "NOT_IN", "value": [...]}}}` (same shape as `ENUM-EXCL-001`).

Credibility: first interval-valued eligibility domain and first medical
stakes; exclusion lists generalize the v0.3 enum work beyond toy categories.

## Family 3 — `benefits_workreq` (SNAP-style work requirements)

Real-world grounding: SNAP income/resource limits are updated **annually**
(USDA-FNS eligibility tables, e.g. FY2026 gross/net tables:
http://www.fns.usda.gov/snap/recipient/eligibility), and the Fiscal
Responsibility Act of 2023 rewrote ABAWD time-limit exceptions — raising the
age-based exception 50 → 55 and adding homelessness, veteran, and
foster-care-youth exceptions, all sunsetting 2030 (FNS final rule
FNS-2023-0058: https://public-inspection.federalregister.gov/2024-29072.pdf).
Annual numeric churn plus statutory exception churn in one program.

Exercises: **exception** (age-gated waiver) + **threshold** (annual cap).
Reuses `age`/`income`-shaped integer variables.

Scenario A — `SNAP-AGE-001` (exception widened → `unnecessary_burden`). Old:
work requirement applies to all adults (obligation `register_work`). New:
`R("R-EX-V2", "exception", "register_work", {"field": "age", "operator":
">=", "value": 55}, "waive work IF age >= 55", ...)`. Stale procedure burdens
a 56-year-old the amendment exempts. Gold witness: `{"kinds":
["unnecessary_burden"], "domains": {"unnecessary_burden": [{"field": "age",
"operator": ">=", "value": 55}]}}`. Gold repair: `required_probe` on
`register_work` (`case_true`: age 40, `case_false`: age 60).

Scenario B — `SNAP-CAP-001` (annual income-cap refresh → `wrong_rejection`).
Old: gross-income gate `income <= 2680` (illustrative). New: `<= 2888`
(annual inflation adjustment). Stale procedure rejects a household the new
tables accept. Gold witness: income in (2680, 2888]. Gold repair: gate to
`<= 2888`. Recommend authoring this one as a **no-op-shaped near miss** on
alternate years (cap unchanged → `SEMANTICS_UNCHANGED`) to test the
"annual churn that changes nothing" case.

Credibility: first exception whose condition is numeric rather than
categorical, and first calendar-driven (annual) amendment rhythm — both
absent from v0.3.0.

## Family 4 — `export_list` (export-control listings)

Real-world grounding: BIS adds entities to the Entity List by Federal Register
rule (e.g. 140 additions plus 14 modifications, Dec 2024:
https://www.bis.gov/press-release/commerce-strengthens-export-controls-restrict-chinas-capability-produce-advanced-semiconductors-military ;
32 more entities Sept 2025:
https://www.govinfo.gov/content/pkg/FR-2025-09-16/html/2025-17893.htm),
while per-entry license-exception eligibility (e.g. GOV under §740.11(b))
carves back narrow permissions (Entity List FAQs:
https://www.bis.gov/media/documents/entity-list-faqs-11.10.25-readded).
Listings are frequent, high-stakes, and bidirectional (additions +
carve-outs).

Exercises: **prohibition** + **exception carve-out**. Needs `counterparty`
(enum) and `item_class` (enum) witness variables.

Scenario A — `EXPORT-ADD-001` (listing → `prohibition_breach`). Old: no
restriction on `approve_export` for `counterparty`. New: `R("R-PB-V2",
"prohibition", "approve_export", {"field": "counterparty", "operator": "==",
"value": "ENT-140"}, "FORBID approve_export WHEN counterparty == ENT-140",
...)`. Stale procedure approves a listed-entity shipment. Gold witness:
`{"kinds": ["prohibition_breach"], "domains": {"prohibition_breach":
[{"field": "counterparty", "operator": "==", "value": "ENT-140"}]}}`. Gold
repair: `{"required_effect": {"prohibition_gate": {"field": "counterparty",
"operator": "==", "value": "ENT-140"}}}` (same shape as `PROH-001`).

Scenario B — `EXPORT-CARVE-001` (license exception → `unnecessary_burden`).
Old: blanket prohibition on `approve_export` for `item_class == HBM` (modeled
as prohibition, stale procedure blocks everything). New: exception
`approve_export IF item_class == HBM AND license == GOV`. Stale procedure
blocks a GOV-authorized shipment the carve-out permits. Gold witness:
`{"kinds": ["unnecessary_burden"], ...}` over the conjunction domain. Gold
repair: exception carve-out on the prohibition gate. Flag: conjunction-in-
exception is the hardest construct here — if the normalizer cannot express
it, scope scenario B down to a single-field carve-out (`license == GOV`).

Credibility: first prohibition domain outside reimbursement and first
bidirectional family (listing one quarter, carve-out the next) — the closest
v0.4 gets to adversarial, real-world amendment cadence.
