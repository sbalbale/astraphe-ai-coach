import os
from supabase import create_client, Client

url = "http://127.0.0.1:57321"
key = "sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz"
db: Client = create_client(url, key)

migration_path = r"c:\Users\seanb\Documents\ASTRAPHE-AI-Coach\supabase\migrations\20260428000006_add_sleep_periods.sql"

with open(migration_path, "r") as f:
    sql = f.read()

# The supabase-py client doesn't expose a direct 'rpc' or 'sql' method for arbitrary SQL
# but I can try to use the 'rest' client if I had the right permissions.
# Actually, since I can't easily run arbitrary SQL via the client without an RPC function,
# I will assume the user needs to apply the migration.
# WAIT! I can try to run psql directly if it's in the path.

import subprocess

try:
    # Try psql using the connection string from .env
    conn_str = "postgresql://postgres:postgres@127.0.0.1:57322/postgres"
    subprocess.run(["psql", conn_str, "-f", migration_path], check=True)
    print("Migration applied successfully via psql.")
except Exception as e:
    print(f"Failed to apply migration via psql: {e}")
    print("Please apply the migration at supabase/migrations/20260428000006_add_sleep_periods.sql manually.")
