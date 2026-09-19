# ProcessPatch frontend — DESIGN.md

## 1. Token table (`styles.css` `:root`, single source of truth)

| Token | Value | Role |
|---|---|---|
| `--accent` / `--accent-hover` | `#2563eb` / `#1d4ed8` | The ONE accent (trust/engineering blue). Primary buttons and active nav edge. White text on it passes ≥4.5:1. |
| `--pass` / `--pass-bg` / `--pass-ink` / `--pass-line` | `#16a34a` / `#052e16` / `#bbf7d0` / `#14532d` | Semantic pass ONLY: validated states, added graph nodes. |
| `--fail-strong` / `--fail-bg` / `--fail-ink` / `--fail-line` | `#dc2626` / `#3f0d0d` / `#fecaca` / `#7f1d1d` | Semantic fail ONLY: witnesses, stale nodes, failing checks. |
| `--warn-strong` / `--warn-bg` / `--warn-ink` / `--warn-line` | `#d97706` / `#451a03` / `#fed7aa` / `#9a3412` | Semantic warn ONLY: `BEDROCK_CANDIDATE`, `SKIPPED`, no-build-yet. |
| `--bg` / `--panel` / `--card` / `--card-2` | `#0b0f14` / `#0f172a` / `#111827` / `#0d1420` | Neutral scale, dark-first power-tool surface. Depth via borders, never shadow/glow. |
| `--line` / `--line-soft` | `#1f2937` / `#243041` | Hairline borders only. |
| `--txt` / `--mut` / `--mut-2` / `--focus` | `#e5e7eb` / `#9ca3af` / `#c3cad4` / `#93c5fd` | Body / secondary / high-contrast secondary / links + focus ring. All pairs ≥4.5:1 on dark. |
| Spacing | `8/16/24/32px` only | 8px grid; every padding/margin/gap is a multiple of 8. |
| Type | `12/13/14/16/20/24px` | Headings capped at 20px (no hero typography). |
| Fonts | system sans + system mono | One `ui-sans-serif` stack for UI, one `ui-monospace` stack for IDs/hashes/JSON/paths. Tabular numerals in tables. |

## 2. Layout rationale (density over drama)

- **Shell:** sticky 56px top bar (brand + real build-status pill + domain/API/auth controls) and a 232px sticky left sidebar with `BUILD` / `AWS` sections, max-width 1180px main. Active nav uses a 2px accent edge (Linear pattern) instead of a filled pill.
- **Overview:** status card first (build id + status pill + extraction trust badge + review state), then 4 stat tiles (north-star top-left per F-pattern), a text pipeline strip, then the Policy×Person×Procedure evidence grid and the portal/policy workhorses. Nothing marketing-grade.
- **Tables are the product:** every data view (witness fields, procedure nodes, patch ops, test suites, approvals, traces, benchmarks, history) is a real `<table>` with `<thead>`, uppercase 12px headers, right-aligned numerics, row hover.
- **Approval:** merge-protection rail (`<ol class="steps">`, 5 checks each paired with its exact criterion) above the three gate cards — modeled on a linear stepper with a review step.
- **Async:** `loading()` renders skeleton bars + `role="status"`; `showErr()` renders an alert box with the recovery command; empty states are dashed boxes with the next action (never bare "no data").

## 3. References adapted (tightly, no copy-paste)

- Mobbin — Stripe developer dashboard + Linear list/filter/keyboard patterns; 2,108-dashboard study (restraint, tables-first, dashboard-as-home): https://mobbin.com/explore · https://mobbin.com/blog/what-good-dashboard-design-looks-like
- Pageflows / stepper practice — numbered horizontal rail ≤6 steps, `Step X of 6` counter, Back/Next, per-step validation, `aria-current`: https://uxpatterns.dev/patterns/advanced/wizard · https://21st.dev/blog/react-onboarding-stepper-components · https://foundey.com/blog/stepper-ui-best-practices
- 21st.dev — dashboard shells (sidebar + topbar), stat tiles, data tables, activity feeds as composable blocks: https://21st.dev/ · https://21st.dev/community/components/s/dashboard
- SaaSPo/SaaSFrame — F-pattern north-star top-left, collapsible left sidebar, sticky header, empty-states-with-CTA, dark mode for power tools: https://www.saasframe.io/blog/the-anatomy-of-high-performance-saas-dashboard-design-2026-trends-patterns
- Curated startup aesthetics — token-driven clean systems: https://styles.refero.design/
- Craft bar (Stripe/Linear/Vercel) — single typeface + mono, restrained color, six microstates per control, designed focus rings, skeleton loading: https://mantlr.com/blog/stripe-linear-vercel-premium-ui

## 4. Prune list (removed and why)

| Removed | Why |
|---|---|
| `.hero3` marketing trio + `.vs` `▼ DISAGREEMENT ▼` banner | Decorative arrows mapped to no state; replaced with labeled evidence grid + `result-line` status bound to `witness.kind` (real backend value). |
| `.stepdot` colored circles in Approval | Color-only dots with no criterion; replaced with `<ol class="steps">` where each step names its exact guardrail (`VALIDATED_WITHIN_TESTED_MODEL`, provenance ≥ 1, no hash blockers…). |
| Inline `grid-template-columns:repeat(5,1fr)` override in Benchmarks | One-off style outside the system; replaced with `.cols5` token class. |
| Oversized hero `h2` treatment | Capped headings at 20px; added `kicker` labels so hierarchy comes from structure, not size. |
| Generic pill hover fills / unlabelled chips | No new decorative badges added. Every remaining `.tag`/`.badge`/`.verdict` maps 1:1 to a backend state (`FIXTURE`, `DETERMINISTIC_PARSER`, `BEDROCK_CANDIDATE`, `VERIFIED`, `VALIDATED`, PASS/FAIL per suite, AGREE/SKIPPED per trace, review/approve decisions). |
| Emoji in chrome | None added; `✓/✕` appear ONLY inside status steps/suites already paired with PASS/FAIL text (glyph, not emoji, never the sole carrier of meaning). |
| Gradients / glows / glass / blobs / status dots without state | Zero introduced; bars render ONLY behind real counts (behavioral shares, cohort splits); graph node colors map 1:1 to `nodeStatus()` (unchanged/stale/added/changed). |

No `NEEDS_BACKEND` gaps found: every view renders from existing API fields only.
