# Performance notes

## Self-hosted stack

Production: GitHub Actions → GHCR → Proxmox (`astraphe-api`, self-hosted Supabase, `astraphe-redis`). See [DEPLOYMENT.md](./DEPLOYMENT.md) and [REDIS.md](./REDIS.md).

## Activity streams (full fidelity)

- **Combined endpoint:** `GET /v1/activities/{workout_id}/detail` — one `time_series` read, laps, intervals, zones.
- **Background hydrate:** After Strava ingest, missing `activity_streams` rows are filled via `hydrate_workout_streams` in a background task.
- **Redis:** Stream and detail responses cached (`streams:`, `detail:` keys).

### Phase 2 (optional): Supabase Storage for stream blobs

Large 1 Hz stream data can move out of Postgres JSONB without downsampling.

**How-to:** [STREAM_STORAGE_MIGRATION.md](./STREAM_STORAGE_MIGRATION.md)

Summary:

1. ~~Store gzip-compressed full `time_series` JSON in bucket `activity-streams`~~ **Done (phase 2)** — see [`STREAM_STORAGE_MIGRATION.md`](./STREAM_STORAGE_MIGRATION.md).
2. Keep `storage_path` + metadata in Postgres; upload with `upsert: true` for hydrate/refetch.
3. **API proxy (Option A):** FastAPI gunzips and returns the same `/detail` JSON shape; Redis `detail:` cache unchanged.
4. Raw `.fit` is a future **Garmin artifact** only (`fit_file_url`), not the canonical stream format.

Optional optimization; use when `activity_streams` row size remains slow after combined endpoint + Redis.

## Coach latency

- Parallel context assembly + optional RAG skip for short messages.
- Conversation title generation runs in `BackgroundTasks`.
- Mobile should prefer `POST /v1/coach/stream` for incremental UI.

## Benchmarks

```bash
cd backend
python scripts/benchmark_workouts_list.py
```
