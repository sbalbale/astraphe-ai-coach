#!/usr/bin/env python3
"""
Generate a runnable PostgreSQL schema for ASTRAPHE public tables from a live database.

Reads SUPABASE_DB_URL from the environment or backend/.env, introspects public.*,
topologically sorts tables by foreign-key dependencies, and writes SQL suitable for
fresh installs (local Supabase, CI, or documentation).

Usage (from repo root):
  backend/.venv/Scripts/python docs/tools/generate_schema.py
  backend/.venv/Scripts/python docs/tools/generate_schema.py --output docs/schema/astraphe_public_schema.sql
  backend/.venv/Scripts/python docs/tools/generate_schema.py --database-url "$SUPABASE_DB_URL"

Requires: psycopg[binary]  (pip install "psycopg[binary]")
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import psycopg
except ImportError:
    print(
        "Missing dependency: psycopg. Install with:\n"
        '  pip install "psycopg[binary]"',
        file=sys.stderr,
    )
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "schema" / "astraphe_public_schema.sql"
ENV_CANDIDATES = (
    REPO_ROOT / "backend" / ".env",
    REPO_ROOT / ".env",
)

HEADER = """\
-- ASTRAPHE AI Coach — public schema (generated)
-- Source: live PostgreSQL introspection via docs/tools/generate_schema.py
-- Generated: {generated_at}
--
-- Prerequisites:
--   - Supabase local or hosted project with auth schema
--   - CREATE EXTENSION IF NOT EXISTS pgcrypto;
--
-- This file is ordered for execution (parents before children).
-- Re-run the generator after migrations to refresh: see docs/SCHEMA_TOOL.md
"""


@dataclass(frozen=True)
class ForeignKey:
    name: str
    definition: str
    ref_schema: str
    ref_table: str


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        key = key.strip()
        val = raw.strip().strip('"').strip("'")
        values[key] = val
    return values


def resolve_database_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url
    for key in ("SUPABASE_DB_URL", "DATABASE_URL"):
        if os.environ.get(key):
            return os.environ[key]
    for env_path in ENV_CANDIDATES:
        env = load_dotenv(env_path)
        if env.get("SUPABASE_DB_URL"):
            return env["SUPABASE_DB_URL"]
    raise SystemExit(
        "No database URL. Set SUPABASE_DB_URL, pass --database-url, "
        f"or add SUPABASE_DB_URL to {ENV_CANDIDATES[0]}."
    )


def fetch_tables(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
            ORDER BY c.relname
            """
        )
        return [row[0] for row in cur.fetchall()]


def fetch_foreign_keys(conn: psycopg.Connection) -> dict[str, list[ForeignKey]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              rel.relname AS table_name,
              con.conname,
              pg_get_constraintdef(con.oid, true) AS definition,
              ref_ns.nspname AS ref_schema,
              ref_rel.relname AS ref_table
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            JOIN pg_class ref_rel ON ref_rel.oid = con.confrelid
            JOIN pg_namespace ref_ns ON ref_ns.oid = ref_rel.relnamespace
            WHERE nsp.nspname = 'public'
              AND con.contype = 'f'
            ORDER BY rel.relname, con.conname
            """
        )
        by_table: dict[str, list[ForeignKey]] = defaultdict(list)
        for table_name, name, definition, ref_schema, ref_table in cur.fetchall():
            by_table[table_name].append(
                ForeignKey(
                    name=name,
                    definition=definition,
                    ref_schema=ref_schema,
                    ref_table=ref_table,
                )
            )
        return dict(by_table)


def topological_sort(tables: list[str], fks: dict[str, list[ForeignKey]]) -> list[str]:
    """Order tables so referenced public tables are created first."""
    table_set = set(tables)
    deps: dict[str, set[str]] = {t: set() for t in tables}
    for table in tables:
        for fk in fks.get(table, []):
            if fk.ref_schema == "public" and fk.ref_table in table_set and fk.ref_table != table:
                deps[table].add(fk.ref_table)

    in_degree = {t: len(deps[t]) for t in tables}
    queue = deque(sorted(t for t in tables if in_degree[t] == 0))
    ordered: list[str] = []

    while queue:
        node = queue.popleft()
        ordered.append(node)
        for other in tables:
            if node in deps[other]:
                in_degree[other] -= 1
                if in_degree[other] == 0:
                    queue.append(other)

    if len(ordered) != len(tables):
        remaining = sorted(set(tables) - set(ordered))
        ordered.extend(remaining)
    return ordered


def fetch_columns(conn: psycopg.Connection, table: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              a.attname,
              pg_catalog.format_type(a.atttypid, a.atttypmod),
              NOT a.attnotnull AS nullable,
              pg_get_expr(ad.adbin, ad.adrelid) AS default_expr,
              a.attgenerated,
              a.attidentity
            FROM pg_attribute a
            JOIN pg_class t ON a.attrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
            WHERE n.nspname = 'public'
              AND t.relname = %s
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            (table,),
        )
        rows = []
        for name, col_type, nullable, default_expr, attgenerated, attidentity in cur.fetchall():
            rows.append(
                {
                    "name": name,
                    "type": col_type,
                    "nullable": nullable,
                    "default": default_expr,
                    "generated": attgenerated,
                    "identity": attidentity,
                }
            )
        return rows


def fetch_primary_key(conn: psycopg.Connection, table: str) -> tuple[str, ...] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT array_agg(a.attname ORDER BY array_position(i.indkey::smallint[], a.attnum::smallint))
            FROM pg_index i
            JOIN pg_class t ON t.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey)
            WHERE n.nspname = 'public'
              AND t.relname = %s
              AND i.indisprimary
            GROUP BY i.indrelid
            """,
            (table,),
        )
        row = cur.fetchone()
        return tuple(row[0]) if row and row[0] else None


def fetch_check_constraints(conn: psycopg.Connection, table: str) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT con.conname, pg_get_constraintdef(con.oid, true)
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = 'public'
              AND rel.relname = %s
              AND con.contype = 'c'
            ORDER BY con.conname
            """,
            (table,),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def fetch_unique_constraints(conn: psycopg.Connection, table: str) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT con.conname, pg_get_constraintdef(con.oid, true)
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = 'public'
              AND rel.relname = %s
              AND con.contype = 'u'
            ORDER BY con.conname
            """,
            (table,),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def fetch_indexes(conn: psycopg.Connection, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = %s
              AND indexname NOT IN (
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                WHERE nsp.nspname = 'public'
                  AND rel.relname = %s
                  AND con.contype IN ('p', 'u')
              )
            ORDER BY indexname
            """,
            (table, table),
        )
        return [row[0] + ";" for row in cur.fetchall()]


def format_column(col: dict) -> str:
    parts = [f"  {col['name']} {col['type']}"]
    gen = col["generated"]
    if gen == "s":
        parts.append(f"GENERATED ALWAYS AS ({col['default']}) STORED")
    elif gen == "v":
        parts.append(f"GENERATED ALWAYS AS ({col['default']}) VIRTUAL")
    else:
        if col["identity"]:
            parts.append(col["identity"].upper() if col["identity"] else "")
            if col["identity"] == "a":
                parts[-1] = "GENERATED ALWAYS AS IDENTITY"
            elif col["identity"] == "d":
                parts[-1] = "GENERATED BY DEFAULT AS IDENTITY"
        elif col["default"] is not None:
            parts.append(f"DEFAULT {col['default']}")
        if not col["nullable"]:
            parts.append("NOT NULL")
    return " ".join(p for p in parts if p)


def render_table(
    conn: psycopg.Connection,
    table: str,
    fks: list[ForeignKey],
) -> str:
    columns = fetch_columns(conn, table)
    pk = fetch_primary_key(conn, table)
    checks = fetch_check_constraints(conn, table)
    uniques = fetch_unique_constraints(conn, table)

    fk_names = {fk.name for fk in fks}
    checks = [(n, d) for n, d in checks if n not in fk_names]
    uniques = [(n, d) for n, d in uniques if n not in fk_names]

    body: list[str] = [format_column(c) for c in columns]

    if pk:
        pk_cols = ", ".join(pk)
        body.append(f"  CONSTRAINT {table}_pkey PRIMARY KEY ({pk_cols})")

    for name, definition in uniques:
        body.append(f"  CONSTRAINT {name} {definition}")

    for name, definition in checks:
        body.append(f"  CONSTRAINT {name} {definition}")

    for fk in fks:
        if fk.ref_schema in ("public", "auth"):
            body.append(f"  CONSTRAINT {fk.name} {fk.definition}")

    return f"CREATE TABLE public.{table} (\n" + ",\n".join(body) + "\n);\n"


def render_schema(conn: psycopg.Connection, include_indexes: bool) -> str:
    tables = fetch_tables(conn)
    fks_by_table = fetch_foreign_keys(conn)
    ordered = topological_sort(tables, fks_by_table)

    chunks: list[str] = [
        HEADER.format(generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")),
        "CREATE EXTENSION IF NOT EXISTS pgcrypto;\n",
    ]

    for table in ordered:
        chunks.append(render_table(conn, table, fks_by_table.get(table, [])))
        chunks.append("\n")

    if include_indexes:
        chunks.append("-- Indexes\n")
        for table in ordered:
            for index_sql in fetch_indexes(conn, table):
                chunks.append(index_sql + "\n")

    return "\n".join(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        help="PostgreSQL connection URL (default: SUPABASE_DB_URL from env or backend/.env)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output SQL file (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--no-indexes",
        action="store_true",
        help="Omit secondary indexes from the output",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print SQL to stdout instead of writing a file",
    )
    args = parser.parse_args()

    db_url = resolve_database_url(args.database_url)
    with psycopg.connect(db_url) as conn:
        sql_text = render_schema(conn, include_indexes=not args.no_indexes)

    if args.stdout:
        sys.stdout.write(sql_text)
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(sql_text, encoding="utf-8")
    table_count = len(re.findall(r"^CREATE TABLE public\.", sql_text, re.MULTILINE))
    print(f"Wrote {args.output} ({table_count} tables)")


if __name__ == "__main__":
    main()
