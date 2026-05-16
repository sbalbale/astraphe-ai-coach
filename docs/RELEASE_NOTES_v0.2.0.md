# ASTRAPE AI Coach — Release Notes (v0.2.0)

**Tag:** `v0.2.0`  
**Base:** Builds on [v0.1.0](https://github.com/sbalbale/ASTRAPE-AI-Coach/releases/tag/v0.1.0) MVP.

---

## Highlights

### Strava integration (shipped)

- OAuth connect flow, token expiry handling, and webhook ingestion
- Activity backfill, stream hydration/persistence, duplicate handling and canonical workout deduplication
- Rate limiting, sport normalization, and dedicated `activity_detail` API routes
- Mobile: connect UX, OAuth success page, workout detail zones and GPS trace (MapLibre)

### HR zones & wearables

- Athlete HR zone endpoints and mapper; `hr_zone_method` support with recalculation
- Unified Z1–Z5 labels across WHOOP and UI; WHOOP zone backfill script
- Rowing splits and HR zone utilities

### Mobile & tooling

- Package manager migration to **pnpm** with install guards
- Vite pre-bundle for `@iconify/svelte`; Leaflet replaced with **MapLibre** for GPS traces
- Getting Started guide in docs

### Backend & data

- Schema generator and checked-in public schema (`docs/schema/`)
- Default Gemini model updated to `gemma-4-31b-it`
- Processing fix: preserve zero values when stripping `None` from payloads

---

## Upgrade notes

- Run new Supabase migrations before deploying backend/mobile against production.
- Strava requires configured OAuth app credentials and webhook subscription (see integration docs).
- Mobile developers should use **pnpm** (`corepack enable` / `pnpm install` in `mobile/`).

---

## Full commit list

```text
git log v0.1.0..v0.2.0 --oneline
```
