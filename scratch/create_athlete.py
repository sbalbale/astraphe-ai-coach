import os
from supabase import create_client, Client

url = "http://127.0.0.1:57321"
key = "sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz"
db: Client = create_client(url, key)

athlete_id = "52c00ba6-d91b-4eb3-b0ad-c533161da9bd"
user_id = "00000000-0000-0000-0000-000000000000" # Dummy user id

# First check if athlete exists
res = db.table("athletes").select("id").eq("id", athlete_id).execute()
if not res.data:
    # Need a user_id from auth.users. 
    # Since I can't easily insert into auth.users via the client,
    # I'll just use a real user if one exists or create one.
    # Actually, for local dev, we can just use the handle_new_user trigger 
    # but I'll try to just insert directly if I have service role.
    try:
        db.table("athletes").insert({
            "id": athlete_id,
            "user_id": athlete_id, # Hacky but might work if RLS is off or using service key
            "display_name": "Sean Balbale"
        }).execute()
        print("Athlete created.")
    except Exception as e:
        print(f"Failed to create athlete: {e}")
else:
    print("Athlete already exists.")
