# Demo script — presenter runbook, 4 minutes, Judge Mode order

Pre-flight (before the clock, not counted): `python scripts/verify.py` →
PASS; `python scripts/judge_demo.py` → ALL 6 BEATS VERIFIED. If either
fails, fix before recording — the demo is never rehearsed live. Present on
local `make app` (http://localhost:8080); keep a second tab on the same URL
as the hot fallback. Total on-clock: 225s + 15s buffer = 240s.

## Beat 1 · 0:00–0:25 — the person, the stale portal (Overview)

- Clicks: enter CGPA 7.80 → Check (current portal). Hold on DISAGREEMENT.
- SAY: "A policy changed. This applicant scores 7.80 — eligible under the
  new rules, but the portal still enforces yesterday's. That disagreement is
  the whole product."
- Wrong/fallback: if the portal call hangs, cut to pre-fetched judge output
  (expected True, actual False) and keep talking; never narrate a spinner.

## Beat 2 · 0:25–0:55 — compile (Overview)

- Clicks: COMPILE AMENDMENT → scroll the build status card and stat tiles.
- SAY: "One click compiles the amendment: status PATCH_VALIDATED, two
  witnesses, sixteen passing checks — validated within the tested model,
  nothing more. Note the extraction badge: deterministic parser, no model
  call on this policy."
- Wrong/fallback: if compile is slow, hard-cut to the loaded build (same
  build_id the judge script verifies) and continue.

## Beat 3 · 0:55–1:25 — meet the witness (Witnesses)

- Clicks: expand W-001 → Replay witness → Boundary explorer.
- SAY: "This isn't a metric, it's a person: the exact case that proves the
  bug, with expected versus actual paths side by side — replayable after the
  patch, with the knife-edge at 7.5."
- Wrong/fallback: if replay lags, the static paths already tell the story —
  skip the click, don't wait on camera.

## Beat 4 · 1:25–1:45 — the repair site (Procedure)

- Clicks: red stale node → provenance drawer.
- SAY: "The fault localizes to this gate: why it exists, Policy V2 section
  4.2, witnesses touching it, patch operations. Red is stale, green is
  added — every color maps to a real state."
- Wrong/fallback: if the drawer misfires, the node table below the graph
  carries the same config and provenance — scroll instead.

## Beat 5 · 1:45–2:10 — regression (Tests)

- Clicks: expand one suite (Witness replay), pan the suite list.
- SAY: "Sixteen of sixteen: witness replay, boundaries, preservation,
  integrity, ordering, metamorphic, provenance. The suite proves the patch
  fixes the witnesses without breaking anything else."
- Wrong/fallback: none needed — read the counts on screen, never quote
  memorized figures.

## Beat 6 · 2:10–2:40 — merge protection (Approval)

- Clicks: walk the 5 checks → Approve candidate (reviewer) → certificate.
- SAY: "Five merge-protection checks, all green. A reviewer approves the
  exact candidate hash — activation stays a separate human's job. The
  certificate reads VALIDATED_WITHIN_TESTED_MODEL, never compliance
  guaranteed."
- Wrong/fallback: if approval needs auth here, show the disabled Approve
  with its merge-protection reason instead of signing in live.

## Beat 7 · 2:40–3:05 — bundle download (Approval)

- Clicks: Download governance bundle → show the file (reviews, approvals,
  guardrails, witnesses, patch, certificate, audit + bundle_sha256).
- SAY: "One sealed evidence pack over canonical bytes — and this endpoint
  refuses unapproved builds with a 409, so a candidate can never masquerade
  as a governed artifact."
- Wrong/fallback: if the download stalls, open the pre-saved bundle JSON
  and point at bundle_sha256; if it 409s, say so — refusal without approval
  is the governance working, not a bug.

## Beat 8 · 3:05–3:30 — nomination (Traces)

- Clicks: paste `demo/traces-sample.csv` into the CSV card (expect ingested:
  10, duplicates: 1) → Nominate witness on a DISAGREE trace.
- SAY: "Ten real executions ingested, one duplicate caught by content hashing.
  A disagreeing trace nominates a candidate — but only the verified pipeline
  can promote it. Either a new witness or 'already covers': both are honest
  answers."
- Wrong/fallback: duplicates: 1 is idempotent ingest working, not an error.
  If the table is empty, ingest the scripted 7.80 case; if that fails, cut.

## Close · 3:30–3:45, buffer to 4:00

- SAY: "AI extracts; deterministic code verifies; humans approve. Software
  gets regression tests when code changes — real-world procedures should get
  them when rules change."
- 15s buffer for transitions and breath. End on the certificate wording.
