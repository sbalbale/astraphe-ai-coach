# Mobile

## Overview

The `mobile/` app is a Svelte 5 + SvelteKit 2 single-page app. It is built statically with `adapter-static`, disables SSR, ships a PWA manifest and a push-only service worker (via `@vite-pwa/sveltekit`), and includes a Capacitor iOS project.

Android is not scaffolded in this repository.

## Runtime

Versions pinned in `mobile/package.json` (main ones):

- `svelte@5.55.5`
- `@sveltejs/kit@2.58.0`
- `vite@8.0.10`
- `typescript@6.0.3`
- `tailwindcss@3.4.19`
- `@capacitor/core@8.3.1`, `@capacitor/ios@8.3.1`
- `@capacitor/push-notifications@8.1.0`
- `@supabase/supabase-js@2.105.0`
- `layerchart@1.0.13`
- `d3@7.9.0`
- `maplibre-gl@5.24.0`
- `vitest@3.2.4`

The package requires pnpm (a `preinstall` check rejects npm):

```bash
cd mobile
pnpm install
pnpm run dev       # Vite on port 5173
pnpm test          # vitest
pnpm run check     # svelte-check
```

`pnpm run build` runs `vite build` and then `scripts/prune-spa-html.mjs`.

## SvelteKit Mode

`mobile/src/routes/+layout.ts` sets:

```ts
export const prerender = true;
export const ssr = false;
```

The app behaves as an SPA and relies on client-side Supabase auth and API calls.

## Navigation

Primary navigation is defined in `mobile/src/lib/navTabs.ts`: five tabs, each owning a group of routes. Profile ("Me") is reached from the header avatar, not a tab.

| Tab | Routes | Sub-tabs |
|---|---|---|
| Today | `/`, `/dashboard`, `/readiness` | none |
| Training | `/training`, `/trends`, `/zones` | Log / Trends / Zones |
| Body | `/recovery`, `/sleep`, `/strain`, `/heart-rate`, `/weight` | Recovery / Sleep / Strain / Heart rate / Weight |
| Plan | `/plan` | none |
| Coach | `/chat` | none |

On wide screens (`viewport.wide`, at least 768 px) the layout shows a sidebar instead of the bottom tab bar. Its model is `mobile/src/lib/wideNav.ts`: the same five sections with `1`-`5` keyboard shortcuts and sidebar sub-items:

- Training: Log (`/training`), Trends & zones (`/trends`, `/zones`)
- Body: Overview (`/recovery`, `/sleep`, `/strain`), Heart rate (`/heart-rate`), Weight (`/weight`)

`wideNav.ts` also defines the static rows of the command palette (`CommandPalette.svelte`, opened with Cmd/Ctrl+K).

## Routes

Page routes:

- `/`, `/dashboard`, `/readiness`
- `/training`, `/trends`, `/zones`
- `/recovery`, `/sleep`, `/strain`, `/heart-rate`, `/weight`
- `/plan`
- `/chat`
- `/onboarding`
- `/profile`, `/profile/personal-info`, `/profile/training-settings`, `/profile/connections`, `/profile/notifications`, `/profile/privacy`
- `/auth/signin`, `/auth/signup`, `/auth/forgot-password`, `/auth/reset-password`, `/auth/callback`
- `/oauth/consent`: consent screen for the Supabase OAuth server used by the MCP server (see [MCP_SERVER.md](./MCP_SERVER.md))

The root layout owns auth redirects, onboarding redirects, narrow/wide navigation, deep-link handling, and push initialization.

## Body Tab

- Recovery, Sleep and Strain share the selected day through `lib/stores/bodyDate.svelte.ts` (`null` means today).
- The Strain breakdown comes from `dayStrain()` in `lib/utils/bodyWide.ts`. Strain saturates, so workout scores are not added. Each part's raw load is recovered from its score, the day's score is the stored day strain or the workouts' combined load (whichever is higher), and the score is split in proportion to load into per-workout shares plus all-day activity.
- `/heart-rate` renders `lib/components/body/HeartDay.svelte` (model and helpers in `lib/utils/heartDay.ts`). On the chart, a mouse hovers to read; on touch, tap reads a point, a sideways drag scrubs, and a two-finger pinch zooms around the fingers' midpoint. Zoom chips are also available.
- `/weight` renders `lib/components/body/WeightView.svelte` (helpers in `lib/utils/weightView.ts`).
- Heart rate days and the weight payload are kept in an in-memory stale-while-revalidate cache, `lib/stores/bodyCache.ts`: a page renders from the last response and refreshes in the background. Up to 30 heart-rate days are kept; past days count as fresh for 10 minutes and today for 1 minute. Concurrent fetches of the same day share one request. `api.clearUserCaches()` empties it on sign-out or user switch.

## API Client

The app uses browser `fetch` rather than a Capacitor-native HTTP wrapper.

Key files:

- `mobile/src/lib/api.ts`: route-specific API helpers plus generic `get()`/`post()`.
- `mobile/src/lib/apiAuth.ts`: Supabase session token headers.
- `mobile/src/lib/supabase.ts`: Supabase client setup.

Default backend URL:

```ts
const API_URL = VITE_API_URL && VITE_API_URL !== 'undefined' ? VITE_API_URL : 'http://localhost:8000';
```

Coach chat submits with `POST /v1/coach/message/async`, which returns immediately. The chat page then polls the conversation's messages and `/v1/coach/conversations/{id}/progress` until the reply lands; a push notification is sent if the athlete has left the thread. `api.streamCoachMessage()` (SSE via `/v1/coach/stream`) still exists in `api.ts`, but the chat page uses the async flow.

## State Management

State uses Svelte 5 runes and small store modules. There is no external state library.

Stores in `mobile/src/lib/stores/`:

- `authStore.svelte.ts`
- `athleteStore.svelte.ts` (profile, metrics, biometrics, workouts; persists the current user's snapshot to `localStorage`)
- `trainingStore.svelte.ts`
- `workoutDetailCache.ts`
- `bodyCache.ts` (see Body Tab)
- `bodyDate.svelte.ts`
- `pageHeader.svelte.ts` (page title/eyebrow claimed by each route)
- `viewport.svelte.ts` (`wide` at 768 px, `landscape` at 1200 px)
- `commandPalette.svelte.ts`
- `userSession.ts` (`clearUserScopedState()` clears stores and user caches when the signed-in user changes)

`mobile/src/lib/analysisNavEpoch.svelte.ts` lives directly in `lib/`, not in `stores/`.

Chat state lives in `mobile/src/routes/chat/+page.svelte`; there is no standalone conversation store.

## Capacitor

`mobile/capacitor.config.ts` is minimal:

```ts
const config: CapacitorConfig = {
  appId: 'com.astraphe.coach',
  appName: 'astraphe',
  webDir: 'build'
};
```

Common iOS commands:

```bash
cd mobile
pnpm run build
npx cap sync ios
npx cap open ios
```

## Health Integration

Health integration is a scaffold in `mobile/src/lib/integrations/health.ts`, called from Profile -> Connections.

- Web returns simulated success for permission requests.
- Native requests read access (sleep, heart rate, workouts) through `@interval-health/capacitor-health`.
- `syncRecentData()` posts a mock payload (empty `data` array) to `/v1/biometrics/sync`.

The backend has no `/v1/biometrics/sync` route, so that call fails. HealthKit ingestion is not implemented.

## Push Notifications

Relevant files:

- `mobile/src/lib/services/pushNotifications.ts`
- `mobile/src/service-worker.ts`
- `mobile/src/routes/+layout.svelte`
- `mobile/src/routes/profile/notifications/+page.svelte`

The layout initializes push once per session after the profile has loaded. See [PUSH_NOTIFICATIONS.md](./PUSH_NOTIFICATIONS.md) for the full flow, including the web-push rules (iPhone/iPad: installed Home Screen app only) and the state of native iOS push.

## PWA And Firebase Hosting

The app uses `@vite-pwa/sveltekit` in `injectManifest` mode with `src/service-worker.ts`. The service worker is push-only: it caches nothing, and on activate it deletes any precache an older worker left behind. The web app manifest (`start_url: /dashboard`, `display: standalone`) is generated from `vite.config.ts`.

`mobile/firebase.json` serves `build/`, sets security headers (`X-Frame-Options: DENY`, a `frame-ancestors 'none'` CSP, `nosniff`, referrer policy), no-cache headers for the service worker, workbox files and manifest, immutable caching for `_app/immutable/**`, and rewrites all routes to `/index.html`.

GitHub Actions workflows:

- `.github/workflows/firebase-hosting-merge.yml`: live deploy on `main`.
- `.github/workflows/firebase-hosting-pull-request.yml`: preview deploy for same-repo PRs.

Both install with pnpm, build with `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_KEY` and `VITE_VAPID_PUBLIC_KEY` from GitHub secrets, and deploy with `mobile/scripts/deploy-firebase-hosting-rest.mjs`.

## Offline Behavior

There is no offline precaching. Client-side caching is limited to in-memory caches (workout detail, Body payloads) and the athlete store's `localStorage` snapshot. Do not assume offline queueing or complete local persistence for any screen unless it is implemented in the relevant route or store.

## Design System

The UI uses Tailwind tokens from `mobile/tailwind.config.js` and CSS variables from `mobile/src/app.css`. See [DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md).
