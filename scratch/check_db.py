import os
from dotenv import load_dotenv
from supabase import create_client, Client
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH  = REPO_ROOT / "backend" / ".env"

load_dotenv(ENV_PATH)
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    exit(1)

db: Client = create_client(url, key)

res = db.table("athletes").select("id, user_id, display_name").execute()
print("Athletes in database:")
for row in res.data:
    print(f"ID: {row['id']}, User ID: {row['user_id']}, Name: {row['display_name']}")

res_users = db.auth.admin.list_users()
print("\nUsers in Auth:")
for user in res_users:
    print(f"ID: {user.id}, Email: {user.email}")
