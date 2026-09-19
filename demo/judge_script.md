# Judge demo — 4-minute scripted walkthrough

Every beat below is **verified programmatically** before you record:

```bash
python scripts/judge_demo.py   # must print: ALL 6 BEATS VERIFIED
```

If it fails, fix before recording — the demo is never rehearsed live.

## Pre-flight (5 minutes before)

1. `python scripts/verify.py` → `PASS` (178 assertions).
2. `python scripts/judge_demo.py` → `ALL 6 BEATS VERIFIED`.
3. Local API: `python -m services.api.server 8000` (auth off by default — no
   keys needed). Frontend: open `frontend/index.html`, set the API field to
   `http://localhost:8000`.
4. Cloud (optional, if the stack is deployed): `Run Cloud Execution` shows the
   Step Functions path; otherwise skip — the local pipeline is the same code.

## Script (timed)

**Beat 1 · 0:00 — The stale portal.** Overview tab. CGPA 7.80, check the
current portal: `INELIGIBLE`. Policy V2 says eligible. One real person,
wrongly rejected by yesterday's rules. *(Verdancy claim: expected=True,
actual=False.)*

**Beat 2 · 0:45 — Compile Amendment.** One click. Build appears: status
`PATCH_VALIDATED`, 2 witnesses, 16/16 regression checks. Deterministic parser
→ no model call needed on this policy. *(Verified: witnesses ≥ 1, tests all
green.)*

**Beat 3 · 1:15 — Witnesses tab.** W-001: a concrete applicant, expected vs
actual path side by side. Not a number — a person who proves the bug.
Boundary explorer shows the knife-edge at 7.5.

**Beat 4 · 1:50 — Impact tab.** Blast radius: 2 nodes affected, counts traced
to verified witnesses, synthetic cohort labeled as synthetic. "Impact from
evidence, never estimates."

**Beat 5 · 2:20 — Approval tab.** Merge protection stepper. Gate 1 rule
review, Gate 2 patch approval (reviewer), Gate 3 activation is a **separate**
human capability (pp-admins group when auth is on). Approvals bind exact
artifact hashes; any hash change invalidates them.

**Beat 6 · 2:50 — Traces tab.** Runtime evidence: a real execution trace of
the 7.80 applicant disagrees with the stale procedure and **agrees with the
patch**. Evidence, never auto-accepted truth.

**Close · 3:30.** "Software gets regression tests when code changes.
Real-world procedures should get them when rules change." Point at the
certificate: `VALIDATED_WITHIN_TESTED_MODEL` — never "compliance guaranteed".

## If asked hard questions

- "Where does the benchmark stand?" → 31 heterogeneous cases; extraction
  scored on policy text; downstream repair on gold Rule IR; held-out eval is
  authored, not real-world. Docs state this; keep stating it.
- "What can't it parse?" → Anything outside the bounded language fails closed
  to NEEDS_REVIEW (benchmark has 2 such UNSUPPORTED cases on purpose).
- "Who can activate?" → Only pp-admins (Cognito group), hash-verified, audited.
