import os
from supabase import create_client, Client

url = "http://127.0.0.1:57321"
key = "sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz"
supabase: Client = create_client(url, key)

athlete_id = "52c00ba6-d91b-4eb3-b0ad-c533161da9bd"
date = "2026-04-23"

res = supabase.table("biometrics").select("*").eq("athlete_id", athlete_id).eq("date", date).execute()
print(res.data)
