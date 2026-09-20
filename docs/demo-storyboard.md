# Demo storyboard, 3-minute recording (180s, 15s buffer → 165s of shots)

Pre-flight (before the clock starts, not counted): `python scripts/verify.py`
→ PASS; `python scripts/judge_demo.py` → ALL 6 BEATS VERIFIED. If either
fails, fix before recording, the demo is never rehearsed live
(`demo/judge_script.md`). Record the local `make app` path
(http://localhost:8080); keep a second terminal tab open on the same URL as
the hot fallback.

## Shot 1 · 0:00–0:12 (12s), the person

- Screen/tab: Overview hero (no-build state).
- Action: none, frame the hero and the CGPA 7.80 portal inputs.
- Highlight: one applicant, one number, one question on screen.
- Spoken: "A policy changed. This applicant has a CGPA of 7.80, eligible
  under the new rules, but the portal still enforces yesterday's."
- Fallback: if the hero doesn't load, reload once; the static shell renders
  before any API call returns.

## Shot 2 · 0:12–0:30 (18s), Beat 1, the stale portal

- Screen/tab: Overview → Check (current portal).
- Action: enter CGPA 7.80, click Check; hold on DISAGREEMENT.
- Highlight: expected eligible=True vs actual False, procedural drift confirmed.
- Spoken: "The portal says ineligible. The policy says eligible. That
  disagreement is the whole product."
- Fallback: if the portal call hangs, cut to the pre-fetched judge_demo
  output showing expected=True actual=False and keep talking.

## Shot 3 · 0:30–0:55 (25s), Beat 2, compile

- Screen/tab: Overview → Compile Amendment → build status card.
- Action: one click; scroll the 4 stat tiles as they land.
- Highlight: status PATCH_VALIDATED, 2 witnesses, 16/16 checks, and the
  extraction badge (name it: deterministic parser, no model call).
- Spoken: "One click compiles the amendment: two witnesses, a localized
  patch, sixteen passing checks, validated within the tested model, nothing
  more."
- Fallback: if compile is slow, hard-cut to the loaded build (same build_id
  the judge script verifies) and continue; never narrate a spinner.

## Shot 4 · 0:55–1:20 (25s), Beat 3, meet the witness

- Screen/tab: Witnesses → W-001 card → Replay witness → Boundary explorer.
- Action: expand W-001, run replay, run the boundary explorer.
- Highlight: expected vs actual path side by side; the knife-edge at 7.5.
- Spoken: "This isn't a metric, it's a person: the exact case that proves the
  bug, replayable after the patch."
- Fallback: if replay lags, the static expected-vs-actual paths already tell
  the story, skip the click, don't wait on camera.

## Shot 5 · 1:20–1:40 (20s), Beat 4, impact from evidence

- Screen/tab: Impact.
- Action: pan blast radius → cohort panel.
- Highlight: 2 nodes affected; cohort labeled synthetic, n=100.
- Spoken: "Blast radius traced to verified witnesses over a synthetic cohort
  of one hundred, evidence, never headcount estimates."
- Fallback: none needed; this tab has no async actions. If numbers differ
  from rehearsal, read what's on screen, never quote memorized figures.

## Shot 6 · 1:40–2:10 (30s), Beat 5, merge protection

- Screen/tab: Approval → gates → Approve → certificate.
- Action: walk the 5 checks, approve as reviewer, show the certificate.
- Highlight: green checks bound to real guardrails; the words
  VALIDATED_WITHIN_TESTED_MODEL on the certificate.
- Spoken: "Five merge-protection checks, all green. A reviewer approves the
  exact candidate hash, activation stays a separate human's job."
- Fallback: if approval needs auth in this environment, show the disabled
  Approve with its merge-protection reason instead of signing in live.

## Shot 7 · 2:10–2:30 (20s), Beat 6, runtime evidence

- Screen/tab: Traces → CSV bulk-ingest card → comparison row.
- Sample: `demo/traces-sample.csv` (11 rows: 10 unique + row 11 deliberately duplicates row 4).
- Action: paste the sample live (expect ingested: 10, duplicates: 1), then point at the two verdicts.
- Highlight: vs stale DISAGREE, vs patched AGREE.
- Spoken: "A real execution trace disagrees with the stale procedure and
  agrees with the patch. Evidence only, traces never become witnesses."
- Fallback: response shows duplicates: 1, that's idempotent ingest working, not an error. If the table is empty instead, ingest the scripted 7.80 case live; if that fails, cut.

## Shot 8 · 2:30–2:45 (15s), close

- Screen/tab: certificate or hero.
- Action: hold the frame, end card.
- Highlight: the trust wording, nothing else.
- Spoken: "Software gets regression tests when code changes. Real-world
  procedures should get them when rules change."
- Fallback: none, this shot is pre-written and always safe.

Buffer: 15s unallocated (2:45–3:00) for transitions and breath. Total 165s +
15s = 180s.
