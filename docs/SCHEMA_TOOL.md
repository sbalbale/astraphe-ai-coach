# SQL Schema Creation Tool

`docs/tools/generate_schema.py` generates a runnable `CREATE TABLE` script for all `public` tables by introspecting a live Postgres/Supabase database.

The authoritative schema source remains `supabase/migrations/`. The generated SQL file is a convenience snapshot and can become stale if it is not regenerated after migrations.

## Requirements

The generator needs `psycopg`, which is not in `backend/requirements.txt`. Install it in the backend virtual environment:

```bash
backend/.venv/Scripts/pip install "psycopg[binary]"
```

On macOS/Linux:

```bash
backend/.venv/bin/pip install "psycopg[binary]"
```

## Database URL

The script resolves the database URL in this order:

1. `--database-url`
2. `SUPABASE_DB_URL` environment variable
3. `DATABASE_URL` environment variable
4. `SUPABASE_DB_URL` from `backend/.env`
5. `SUPABASE_DB_URL` from the repo-root `.env`

`SUPABASE_DB_URL` is read only by this tool; the API itself does not use it.

Local Supabase default:

```env
SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres
```

## Generate

From the repository root:

```bash
backend/.venv/Scripts/python docs/tools/generate_schema.py
```

On macOS/Linux:

```bash
backend/.venv/bin/python docs/tools/generate_schema.py
```

Default output:

```text
docs/schema/astraphe_public_schema.sql
```

## Options

| Flag | Description |
|---|---|
| `--database-url URL` | Override database connection string. |
| `--output PATH` | Write to a custom output file. |
| `--no-indexes` | Omit secondary indexes. |
| `--stdout` | Print SQL instead of writing a file. |

## What It Includes

The tool introspects all `public` base tables, sorts them by foreign-key dependencies, and emits:

- table columns
- primary keys
- unique constraints
- check constraints
- public/auth foreign keys
- secondary indexes unless `--no-indexes` is passed

It does not emit every database object needed for a full Supabase project, such as:

- RLS policy definitions
- triggers/functions outside table DDL
- storage bucket policies
- auth schema objects
- non-public schemas

Apply migrations for the full source-of-truth state.

## Keeping It Current

The snapshot is not regenerated automatically (CI does not run the tool). The `Generated:` timestamp in the file header shows when it was last run. After adding a migration, apply it locally (`npm run supabase:migrate`) and re-run the generator. If the snapshot is older than the latest file in `supabase/migrations/`, treat the migrations as authoritative.

## Related Docs

- `docs/DATA_MODELS.md`
- `docs/SETUP.md`
- `supabase/migrations/`
- `docs/schema/astraphe_public_schema.sql`
