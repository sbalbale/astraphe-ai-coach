# Mobile

## Overview

The `mobile/` app is a Svelte 5 + SvelteKit 2 single-page app. It is built statically with `adapter-static`, disables SSR, registers a Vite PWA service worker, and includes a Capacitor iOS scaffold.

Android is not currently scaffolded in this repository.

## Runtime

Current package versions are pinned in `mobile/package.json`:

- `svelte@5.55.5`
- `@sveltejs/kit@2.58.0`
- `vite@8.0.10`
- `typescript@6.0.3`
- `tailwindcss@3.4.19`
- `@capacitor/core@8.3.1`
- `@capacitor/ios@8.3.1`
- `@supabase/supabase-js@2.105.0`
- `layerchart@1.0.13`
- `d3@7.9.0`
- `maplibre-gl@5.24.0`

The package requires pnpm:

```bash
cd mobile
pnpm install
pnpm run dev
```

## SvelteKit Mode

`mobile/src/routes/+layout.ts` sets:

```ts
export const prerender = true;
export const ssr = false;
```

This means the app behaves as an SPA and relies on client-side Supabase auth/API calls.

## Routes

Current page routes include:

- `/`
- `/dashboard`
- `/training`
- `/zones`
- `/recovery`
- `/sleep`
- `/strain`
- `/plan`
- `/chat`
- `/onboarding`
- `/profile`
- `/profile/personal-info`
- `/profile/training-settings`
- `/profile/connections`
- `/profile/notifications`
- `/profile/privacy`
- `/auth/signin`
- `/auth/signup`
- `/auth/forgot-password`
- `/auth/reset-password`
- `/auth/callback`

The root layout owns auth redirects, onboarding redirects, desktop/mobile navigation, deep-link handling, and push initialization.

## API Client

The app uses browser `fetch` rather than a Capacitor-native HTTP wrapper.

Key files:

- `mobile/src/lib/api.ts`: route-specific API helpers plus generic `get()`/`post()`.
- `mobile/src/lib/apiAuth.ts`: Supabase session token headers.
- `mobile/src/lib/supabase.ts`: Supabase client setup.

Default backend URL:

```ts
const API_URL = VITE_API_URL || 'http://localhost:8000';
```

Coach chat currently calls `POST /v1/coach/message` and expects a JSON response. The backend also supports `/v1/coach/stream` for SSE, but the current client chat flow is non-streaming.

## State Management

State uses Svelte 5 runes and small store modules. There is no external state library.

Current stores:

- `mobile/src/lib/stores/authStore.svelte.ts`
- `mobile/src/lib/stores/athleteStore.svelte.ts`
- `mobile/src/lib/stores/trainingStore.svelte.ts`
- `mobile/src/lib/stores/workoutDetailCache.ts`
- `mobile/src/lib/stores/analysisNavEpoch.svelte.ts`

Chat state lives in `mobile/src/routes/chat/+page.svelte`; there is no standalone conversation store module.

## Capacitor

`mobile/capacitor.config.ts` is intentionally minimal:

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

Health integration is scaffolded in `mobile/src/lib/integrations/health.ts`.

Current behavior:

- Web returns simulated success for permission requests.
- Native uses `@interval-health/capacitor-health` permission request scaffolding.
- `syncRecentData()` currently posts an empty/mock payload to `/v1/biometrics/sync`.

The backend does not currently document `/v1/biometrics/sync` as a production ingestion route; full HealthKit ingestion still needs wiring.

## Push Notifications

Relevant files:

- `mobile/src/lib/services/pushNotifications.ts`
- `mobile/src/service-worker.ts`
- `mobile/src/routes/+layout.svelte`
- `mobile/src/routes/profile/notifications/+page.svelte`

Web push uses the Vite PWA service worker at `mobile/src/service-worker.ts`. The layout initializes push after auth/profile loading. Web push is limited to installed standalone PWA mode.

Native iOS push uses the Capacitor push notification plugin scaffold. Android setup should wait until an Android project is added.

## PWA And Firebase Hosting

The app uses Vite PWA/Workbox and Firebase Hosting.

`mobile/firebase.json` serves `build/`, configures no-cache headers for service-worker/workbox assets, immutable caching for `_app/immutable/**`, and rewrites all routes to `/index.html`.

GitHub Actions workflows:

- `.github/workflows/firebase-hosting-merge.yml`: live deploy on `main`.
- `.github/workflows/firebase-hosting-pull-request.yml`: preview deploy for same-repo PRs.

Both workflows install with pnpm and pass Vite env vars from GitHub secrets.

## Offline Behavior

The app has PWA precaching and a few in-memory/client-side caches, especially for workout detail and store state. Do not assume full offline queueing of HealthKit payloads or complete local persistence for every screen unless it is implemented in the relevant route/store.

## Design System

The UI uses Tailwind tokens from `mobile/tailwind.config.js` and CSS variables from `mobile/src/app.css`. New Svelte code should use Svelte 5 runes, tokenized colors, and `font-mono` for numeric metrics.
