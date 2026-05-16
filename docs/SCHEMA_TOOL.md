# SQL Schema Creation Tool

Generates a **runnable** `CREATE TABLE` script for all `public` tables from the live ASTRAPE database (local Supabase or remote).

Supabase Studio’s “copy schema” export is for reference only — table order and inline constraints are not safe to run as-is. This tool introspects PostgreSQL and emits DDL in foreign-key order.

## Quick start

From the repo root (uses `SUPABASE_DB_URL` in `backend/.env`):

```bash
backend/.venv/Scripts/pip install "psycopg[binary]"
backend/.venv/Scripts/python docs/tools/generate_schema.py
```

Output: [`schema/astrape_public_schema.sql`](schema/astrape_public_schema.sql)

## Options

| Flag | Description |
|------|-------------|
| `--database-url URL` | Override connection string |
| `--output PATH` | Custom output file |
| `--no-indexes` | Tables and constraints only (no secondary indexes) |
| `--stdout` | Print to terminal instead of writing a file |

## Apply to a fresh database

Prerequisites: Supabase project (or Postgres with `auth.users` for `athletes.user_id`).

```bash
psql "$SUPABASE_DB_URL" -f docs/schema/astrape_public_schema.sql
```

Then apply RLS policies, triggers, and any objects not in `public` tables via `supabase/migrations/` (this generator covers **table DDL + indexes** only).

## When to regenerate

After merging migrations that change columns, constraints, or indexes:

```bash
backend/.venv/Scripts/python docs/tools/generate_schema.py
```

Commit the updated `docs/schema/astrape_public_schema.sql` if you keep docs in sync with the DB.

## Tables included

`athletes`, `workouts`, `biometrics`, `tss_history`, `training_plans`, `oauth_tokens`, `coach_conversations`, `coach_messages`, `athlete_analyses`, `sleep_periods`, `activity_streams`, `activity_laps`

## Related docs

- [DATA_MODELS.md](DATA_MODELS.md) — field semantics and RLS patterns  
- [SETUP.md](SETUP.md) — local Supabase  
- `supabase/migrations/` — authoritative migration history  
