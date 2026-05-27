# Performance notes

## Self-hosted stack

Production: GitHub Actions → GHCR → Proxmox (`astrape-api`, self-hosted Supabase, `astrape-redis`). See [DEPLOYMENT.md](./DEPLOYMENT.md) and [REDIS.md](./REDIS.md).

## Activity streams (full fidelity)

- **Combined endpoint:** `GET /v1/activities/{workout_id}/detail` — one `time_series` read, laps, intervals, zones.
- **Background hydrate:** After Strava ingest, missing `activity_streams` rows are filled via `hydrate_workout_streams` in a background task.
- **Redis:** Stream and detail responses cached (`streams:`, `detail:` keys).

### Phase 2 (optional): Supabase Storage for stream blobs

Large 1 Hz JSON can be moved out of Postgres JSONB without downsampling:

1. Store gzip-compressed full `time_series` JSON in Supabase Storage.
2. Keep `activity_streams.storage_path` + metadata in Postgres.
3. API serves bytes with `Content-Encoding: gzip` (or signed URL for direct client fetch).

Not implemented yet; use when `activity_streams` row size or list-adjacent queries remain slow after combined endpoint + Redis.

## Coach latency

- Parallel context assembly + optional RAG skip for short messages.
- Conversation title generation runs in `BackgroundTasks`.
- Mobile should prefer `POST /v1/coach/stream` for incremental UI.

## Benchmarks

```bash
cd backend
python scripts/benchmark_workouts_list.py
```
