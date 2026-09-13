# Stephen Tasks

Personal task view. Source of truth is PLAN.md (task numbers match). Legend: [ ] not started · [-] in progress · [x] done · [!] blocked

Deadline: **7:00 PM ET submission**, confirmation verified by 6:55 ET.

---

## Lane ownership (edit only these)

- `web/**`
- `docs/**` except `docs/contracts/api.md` (co-owned, PR only)
- `README.md`, `STEPHEN_TASKS.md`
- `.github/workflows/web.yml`, `.github/workflows/deployed-smoke.yml`
- `.gitignore`, `.env.example`

## Phase 0

- [x] **0.1** Repo, invites (Tylin, Khadim), planning files
- [x] **0.9** Vercel project `pricequorum-web`, linked from `web/` only, framework declared in `web/vercel.json`. Check `.vercel/project.json` before every `--prod`.
- [x] **0.10** Reference site study: stills + motion video
- [x] **0.11** Textures (paper grain, marbled endpaper, ruled ledger, olive ribbon, stamp ink, dark deckled paper) + painterly ledger-desk scene, webp

## Phase 1

- [x] **1.9** Next.js 16 App Router + Tailwind 4 + fonts (Archivo extended display and UI, JetBrains Mono for hashes) + tokens
- [x] **1.10** `web.yml`: contract drift check, `tsc --noEmit`, `eslint`, `vitest run`, `next build`. Green on `cbef0a5`
- [-] **1.11** API client, run reducer, replay-safe SSE hook and unit tests done. Generated types wait on `shared/openapi.json`
- [x] **1.12** Preloader (ribbons 82 px, squares 48 x 82 gap 42, rotations 2 and -3 deg, expo.inOut 0.45 / 0.55 stagger 0.04, leave yPercent -100 in 0.62 s, min 2 s, waits for fonts, images and `/api/health`)
- [x] **1.13** Ticket ("one price / THREE SYSTEMS / agree", reveal stagger 0.14, masked word slide yPercent 110, tearing stub, pointer parallax, idle drift, request form)
- [-] **1.14** Motion primitives + reduced motion (in components; shared hooks later)
- [x] **1.15** Live at https://pricequorum-web.vercel.app, served-page checks pass

## Phase 2

- [-] **2.12** Chapter 01 Resolve built: identifier cards, confidence, NEEDS_HUMAN remedy branch. Unverified until real events arrive
- [-] **2.13** Chapter 02 Approve built: mirrored approval card, approver name, TTL countdown, labels for operator or sandbox approvals. Unverified until real events arrive
- [-] **2.14** Chapter 03 Migrate built: ruled ledger sheet, fault banner with the injected label, read-back recovery text. Unverified until real events arrive
- [-] **2.15** Chapter 04 Verify built: three read-back columns in minor units, invariant bar. Unverified until real events arrive
- [-] **2.16** Receipt and `/runs/[id]` permalink built and live: outcome stamp, truncated hashes with copy, signature, public key. Unverified until real events arrive
- [ ] **2.17** WebGL paper shader with static fallback

## Phase 3

- [-] **3.13** `/verify` live: RFC 8785 + WebCrypto SHA-256 chain recompute, `@noble/ed25519` head check, local tamper test, golden vectors matching Python. Waits on a real `/api/ledger/export`
- [-] **3.14** `/evals` board live (pass count, Wilson interval, per-outcome counts, named failures, per-scenario table). Waits on `/api/proof` and `/api/evals/latest`
- [ ] **3.15** `/break` judge panel: timeout after commit, prompt injection, locked record, chain tamper, concurrent runs, drift. Each streams live chapters.
- [ ] **3.16** Live drift strip from `/api/monitor/events`
- [x] **3.17** `/judges` three-minute tour with deep links and curl commands, backend stops gated on a live health check
- [ ] **3.18** Sound (stamp, paper, chain) muted by default + subtitles toggle
- [x] **3.19** axe WCAG 2.1 AA 10/10 on production, mobile stills reviewed, Lighthouse accessibility, best practices and SEO 100 (performance not measured)
- [-] **3.20** `deployed-smoke.yml` live and green. Add `/api/health` and a real run once the backend is deployed

## Phase 4 (submission, all yours)

- [ ] **4.1** Whole-repo fresh-eyes pass + second-model adversarial review
- [ ] **4.2** `docs/fact-sheet.md` from `/api/proof` and eval output
- [ ] **4.3** Reliability brief (one page) + PDF
- [ ] **4.4** README final
- [ ] **4.5** Stills of every judge screen from the deployed origin
- [ ] **4.6** Video: 2:00, real captures, captions, loudness -14 to -16 LUFS, frames checked at every beat
- [ ] **4.7** Sweeps: em-dash, AI tone, claims vs code, env vars vs code
- [ ] **4.8** Full-history gitleaks scan on the final SHA (repo already public)
- [ ] **4.11** Submit, reload the confirmation

## Contracts you consume

`docs/contracts/api.md` via generated `web/lib/api/types.ts`. Never hand-write an API type. Fixtures in tests are typed from the generated types and never render in the shipped app.

## Hard rules

1. No em-dashes anywhere, including UI copy and the video script.
2. Every animated beat is triggered by a real event from the backend.
3. Stage named paths only. Bare CI gates. Verify the SHA's check-runs after each push.
4. Numbers in the video, README and brief come only from `docs/fact-sheet.md`.
5. After every deploy, confirm the served bundle contains the change.
