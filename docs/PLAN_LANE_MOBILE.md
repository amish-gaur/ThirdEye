# Lane: Mobile + web UX (branch `lane/mobile-ux`)

> **You are on branch `lane/mobile-ux`.** Build only what's described here. Three sibling branches (`lane/live-query`, `lane/phone-infra`, `lane/connection-mesh`) are running in parallel — respect file boundaries below.
>
> Read `docs/PLAN_ADITYA.md` Lane 3 first. This file is the branch-scoped contract.

---

## Mission

The full client-facing surface — production-grade, beautiful, opinionated. Expo (React Native) mobile app + Next.js web app + a shared design system. This branch sets up the JS workspace because no one else will. Every screen renders against mocked APIs initially; swap to real backends as sibling lanes ship.

Goal: ships to TestFlight + Play internal track + Vercel preview by end of this lane.

---

## Files this branch OWNS

- **Workspace root (set up the monorepo):**
  - `pnpm-workspace.yaml`
  - `turbo.json`
  - `tsconfig.base.json`
  - root `package.json` (private, workspace orchestration only)
  - `.npmrc` (pnpm settings, hoisting tweaks for RN)
- **`apps/mobile/`** — Expo SDK app
  - Expo Router file-based routes
  - Clerk Expo for auth
  - NativeWind + Reanimated for motion
  - Zustand + TanStack Query
  - Expo Notifications wiring
  - All screens: onboarding, dashboard, timeline, event detail, live, ask, settings
- **`apps/web/`** — Next.js (App Router) app
  - Same screen set as mobile, web-optimized
  - Shares `packages/ui` via React Native Web
- **`packages/ui/`** — design system
  - Tokens (colors, type, spacing, motion)
  - Components: `<SeverityTile>`, `<ClipPlayer>`, `<ChatBubble>`, `<NodeBadge>`, `<EventRow>`, `<ActionPill>`, etc.
  - Built on `@shopify/restyle` for theming, RNW-compatible
- **`packages/api-types/`** — re-exports the TS types that backend lanes generate at `services/*/_generated/*.ts`. Pure TS, no runtime.
- **`packages/livekit-client/`** — thin wrapper around `@livekit/react-native` and `livekit-client`. Public API: `useStream(nodeId)`, `<NodeStream nodeId={...} />`. **Stub mode** for now (returns a fixture loop) until `lane/connection-mesh` provides the real token endpoint.
- **`apps/mobile/native/`** — Expo config plugins for `react-native-webrtc` and other native deps. Read `infra/livekit/EXPO_CONFIG.md` from `lane/connection-mesh` once it lands and merge those plugin entries into `app.json`.

## Files this branch DOES NOT TOUCH

- Any Python: `action_router/`, `vision_pipeline/`, `services/`, `tests/` for Python.
- `infra/`.
- `requirements.txt`.

## Stub strategy (because backend lanes are still building)

- Use **MSW (Mock Service Worker)** to intercept fetches in dev for both mobile and web. Mocks live in `apps/mobile/src/mocks/` and `apps/web/src/mocks/`.
- Mock data shapes match the documented pydantic schemas in `docs/PLAN_ADITYA.md`. When backend lanes ship `services/*/_generated/*.ts`, import them and the mocks get type-checked.
- Each mock file has a `// TODO(swap): point at real /endpoint` so the cutover is mechanical.
- Live video: `packages/livekit-client/` returns a fixture clip looped. Real LiveKit lands when `lane/connection-mesh` provides the signaling token endpoint.
- Auth: Clerk dev mode with seeded test users.

## Contracts this lane CONSUMES

When sibling lanes land their generated types, copy or symlink them into `packages/api-types/`:

- `services/query/_generated/query.ts` → query types (Lane: live-query)
- `services/events_store/_generated/events.ts` → event shape (Lane: live-query)
- `services/inbound_voice/_generated/voice.ts` → call state types (Lane: phone-infra)
- `services/pairing/_generated/pairing.ts` → pairing types (Lane: connection-mesh)
- `services/signaling/_generated/signaling.ts` → LiveKit token shape (Lane: connection-mesh)

## Contracts this lane PUBLISHES

- **Design tokens** at `packages/ui/src/tokens.ts` — colors, type scale, spacing, motion.
- **Component library** in `packages/ui/src/components/`. Documented via Storybook (web) so other lanes' contributors can preview.
- **`packages/livekit-client/`** public API — connection-mesh implements server-side; we own the client wrapper.

## Tricky coordination

- `apps/mobile/app.json` will eventually need `react-native-webrtc` config plugin entries. `lane/connection-mesh` writes a doc `infra/livekit/EXPO_CONFIG.md` with the exact entries to merge. Do NOT pre-add — wait for the doc, then merge in.
- Don't accept PRs from connection-mesh into `apps/mobile/app.json` directly — they go through this branch.

## Design system spec

- **Color:** graphite background `#0B0D10`, elevated surfaces `#16191E`, text `#E8ECEF` / `#9099A2` muted, accents — green `#3DDC84`, amber `#FFB020`, red `#FF4D4F`.
- **Type:** Inter (body), system display (headings), JetBrains Mono (timestamps/IDs).
- **Spacing:** 4pt base, scale 4/8/12/16/24/32/48/64.
- **Motion:** spring (stiffness 220, damping 22) on tile transitions; Lottie pulse on active tier-3 card; crossfade clip transitions.
- **Haptics:** light on tap, success on acknowledge, warning on tier-2 push, heavy on tier-3/4.

## Sequencing within this branch

1. Monorepo skeleton — pnpm workspaces, turbo, tsconfig, root scripts.
2. `packages/ui/` tokens + 5 base components, Storybook.
3. `apps/mobile/` Expo init + Clerk auth + Expo Router + NativeWind.
4. `apps/web/` Next.js init + Clerk + RNW config.
5. Mock layer (MSW) + fixture data matching pydantic schemas.
6. Onboarding flow.
7. Home dashboard.
8. Timeline + event detail.
9. Ask (chat) screen.
10. Live view screen (with `packages/livekit-client/` stub).
11. Settings.
12. Push notifications wiring (Expo Push).
13. Polish: motion, haptics, empty states, error states, accessibility pass.
14. EAS Build configs for TestFlight + Play.
15. Vercel deploy for web.

## Definition of done

- Builds for iOS + Android via EAS. Submitted to TestFlight + Play internal track.
- Web deployed to Vercel preview.
- Every screen renders end-to-end with mocks.
- Design system imported by both apps from `packages/ui`.
- Lighthouse > 90 on web; mobile holds 60fps on dashboard scroll on a 2-year-old phone.
- Storybook deploys with the component library.
- Auth gates everything; signed-out users land in onboarding.
- Push notifications fire on test events with correct deep links.

## Merge checklist

- [ ] No Python edits anywhere.
- [ ] No `infra/` edits.
- [ ] All UI lives under `apps/` or `packages/`.
- [ ] Workspace config at the root only — no random `package.json` files outside `apps/*` and `packages/*`.
- [ ] Mocks are clearly marked and easy to swap.
- [ ] CI green; both apps build cleanly.
