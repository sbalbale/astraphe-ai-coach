# Activity stream storage

Full-resolution activity streams (heart rate, power, pace, GPS and so on, usually 1 Hz) are stored in Supabase Storage as **gzip-compressed JSON**, not in Postgres. Nothing is downsampled. This replaced the original design, where every stream lived in the `activity_streams.time_series` JSONB column.

## Layout

| Where | What |
|---|---|
| Storage bucket `activity-streams` (private) | One object per workout at `{athlete_id}/{workout_id}.json.gz`: the `time_series` dict (`{"time": [...], "heartrate": [...], ...}`) as gzip JSON. |
| Postgres `activity_streams` row | `storage_path`, `byte_size`, `content_encoding = 'gzip'`, `resolution_seconds`. `time_series` is nullable and only holds data for legacy rows that were never moved. |

Set up by migration `supabase/migrations/20260528100000_activity_streams_gzip_storage.sql` (bucket, columns, athlete-scoped RLS on `storage.objects`).

## Code

`backend/app/services/stream_storage.py` holds the helpers:

- `upload_time_series_gzip()` compresses and uploads with the service-role client, overwriting any existing object, so re-fetching a workout's streams is safe. Strava (`strava.py`), Garmin (`garmin.py`, from parsed FIT files) and intervals.icu (`intervals_icu.py`) all write through it.
- `resolve_time_series()` reads a row: the Storage object first, falling back to the legacy JSONB column. It always downloads from the path derived from the row's own athlete and workout IDs, never from the stored `storage_path` value, because users can write that column on their own rows and the download runs with the service role.
- Decompression is capped at 64 MB to guard against gzip bombs.

`backend/app/routers/activity_detail.py` serves the same `time_series` shape as before, so the app did not change. Parsed responses are cached in Redis under `streams:{athlete_id}:{workout_id}` and `detail:{athlete_id}:v{version}:{workout_id}`. If a row has a `storage_path` but the object cannot be read, the API treats the streams as missing and schedules a background re-fetch from the provider.

## Backfill

`backend/scripts/migrate_streams_to_storage.py` moves legacy rows (JSONB present, no `storage_path`) into Storage. Flags: `--dry-run`, `--limit`, `--athlete-id`, `--batch-size`. Run it by hand; it is not part of deploys.

## Not done yet

- The legacy `time_series` JSONB column has not been dropped. Drop it in a follow-up migration once production rows are confirmed migrated.
- `workouts.fit_file_url` is reserved for keeping raw Garmin `.fit` files as artifacts; nothing writes it today. Garmin FIT files are parsed into the same JSON format and stored as above.

## Related docs

- [PERFORMANCE.md](./PERFORMANCE.md)
- [REDIS.md](./REDIS.md)
- [DATA_MODELS.md](./DATA_MODELS.md)
