Supabase dump set
Project ref: rsbrectarojhvclwvuwy
Project name: ASTRAPHE AI Coach
Region: us-east-2
Dumped at: 2026-05-26 18:08-18:09 local time
Tooling: pg_dump/pg_dumpall PostgreSQL 17.10
Connection endpoint used: aws-1-us-east-2.pooler.supabase.com:5432

Files:
- roles.sql: Role definitions and memberships, excluding role password hashes.
- globals.sql: Global objects, excluding role password hashes.
- schema.sql: Schema-only dump of database postgres.
- data.sql: Data-only dump of database postgres.
- database_full.sql: Combined schema + data dump with CREATE DATABASE / clean restore statements.

Notes:
- The direct Supabase database hostname resolved only to IPv6 from this machine, so dumps were created through the Supabase session pooler.
- Role password hashes were intentionally excluded for safety. If you need an exact cluster-level role password dump, rerun pg_dumpall without --no-role-passwords and store the output securely.
