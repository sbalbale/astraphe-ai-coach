# Performance notes

## Self-hosted stack

Production: GitHub Actions → GHCR → k3s (`astraphe-api`, two replicas, namespace `astraphe`), self-hosted Supabase in the same cluster, and Redis via `REDIS_URL`. See [DEPLOYMENT.md](./DEPLOYMENT.md) and [REDIS.md](./REDIS.md).

## Request path

Every authenticated request used to pay for an auth round trip and a fresh Supabase client. Now (`backend/app/dependencies.py`):

- **Local JWT verification:** user tokens are checked against Supabase Auth's JWKS (ES256/RS256, keys cached for an hour) instead of calling GoTrue (~50 ms saved). Anything that doesn't verify locally still goes to GoTrue.
- **Supabase clients:** one client per user token, kept in an LRU (256 tokens), all sharing one `httpx` connection pool. Building a client per request cost ~300 ms (CA bundle loads).
- **Athlete id:** the `user_id → athletes.id` lookup is cached in-process for 10 minutes.

## Response caches (Redis)

- **Body cache** (`core/body_cache.py`): first page of `GET /v1/biometrics` and `GET /v1/workouts`, `GET /v1/biometrics/heart-rate` (60 s today, 30 min past days), `GET /v1/weight` (10 min). Keys are `body:{athlete_id}:v{N}:{name}`; any write to the athlete's workouts, weigh-ins, heart rate series, or profile bumps `body_version:{athlete_id}`, retiring them all at once. Every payload key has a TTL.
- **Athlete:** `state:` (60 s), `profile:` and `zones:` (5 min) in `routers/athlete.py`.
- **Activity detail:** `streams:` and `detail:` (versioned by `zones_version:`, so a zone change retires every detail entry).

Without Redis every lookup is a miss and nothing fails.

## Activity streams (full fidelity)

- **Combined endpoint:** `GET /v1/activities/{workout_id}/detail` — one `time_series` read, laps, intervals, zones.
- **Background hydrate:** after Strava ingest, missing `activity_streams` rows are filled via `hydrate_workout_streams` (`services/strava.py`) in a background task.
- **Storage:** full `time_series` JSON is stored gzip-compressed in the Supabase Storage bucket `activity-streams` (`activity_streams.storage_path`); the API gunzips it and returns the same `/detail` shape. See [STREAM_STORAGE.md](./STREAM_STORAGE.md). Raw `.fit` (`workouts.fit_file_url`) is not the canonical stream format.
- Hot paths log timings and payload sizes through `core/perf_log.py` (`perf_span`).

## Coach latency

- Context assembly runs in parallel (`asyncio.gather`), and RAG memory lookup is skipped for short messages (`should_skip_rag_for_message`).
- Conversation title generation and memory extraction run in `BackgroundTasks`.
- The mobile chat uses `POST /v1/coach/message/async` and polls `GET /v1/coach/conversations/{id}/progress`, so no request is held open for a multi-hop model call. `POST /v1/coach/stream` (SSE) is still available.
- Model requests time out (`GEMINI_REQUEST_TIMEOUT_SEC`, default 45 s) and fail over to `GEMINI_FALLBACK_MODEL` instead of hanging.

## Benchmarks

```bash
cd backend
python scripts/benchmark_workouts_list.py
python scripts/benchmark_llm_providers.py
```
