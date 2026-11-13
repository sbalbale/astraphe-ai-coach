# ASTRAPHE app

The ASTRAPHE frontend: a Svelte 5 + SvelteKit app built as a static site (`@sveltejs/adapter-static`, output in `build/`, SPA fallback `index.html`). It is served as a PWA on Firebase Hosting and wrapped for iOS with Capacitor. There is no Android project yet.

Use **pnpm** (10+, Node 20+). A preinstall check blocks npm and yarn.

## Setup

```sh
cp .env.example .env   # VITE_SUPABASE_URL, VITE_SUPABASE_KEY, VITE_API_URL, VITE_VAPID_PUBLIC_KEY
pnpm install
pnpm run dev           # http://localhost:5173
```

The app talks to the FastAPI backend at `VITE_API_URL` and to Supabase Auth directly. See [docs/SETUP.md](../docs/SETUP.md) for running the backend and local Supabase.

## Scripts

| Command | Purpose |
|---|---|
| `pnpm run dev` | Vite dev server |
| `pnpm run build` | Static production build into `build/` (then removes every HTML file except `index.html`, so Firebase serves a single SPA shell) |
| `pnpm run preview` | Preview the production build |
| `pnpm run check` | `svelte-check` type checking |
| `pnpm run test` | Vitest |
| `pnpm run test:coverage` | Vitest with coverage thresholds (80% lines, 75% branches), as CI runs it |
| `pnpm run icons` | Regenerate PWA icons |

## iOS

```sh
pnpm run build
npx cap sync ios
npx cap open ios
```

## Deployment

Merges to `main` deploy `build/` to Firebase Hosting through `scripts/deploy-firebase-hosting-rest.mjs`; pull requests get a preview channel. See [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md). More on the app's structure is in [docs/MOBILE.md](../docs/MOBILE.md).
