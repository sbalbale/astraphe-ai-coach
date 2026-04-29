import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

# Add backend to path for imports
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(REPO_ROOT / "backend"))

def reprocess_biometric_dates():
    load_dotenv(REPO_ROOT / "backend" / ".env")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    
    if not url or not key:
        print("Missing Supabase credentials")
        return

    db: Client = create_client(url, key)
    
    # 1. Fetch all athletes to get their offsets
    athletes = db.table("athletes").select("id, timezone_offset_min, display_name").execute()
    
    for athlete in athletes.data:
        athlete_id = athlete["id"]
        offset = athlete.get("timezone_offset_min") or 0
        print(f"\n>>> Reprocessing Athlete: {athlete['display_name']} (Offset: {offset}m)")
        
        # 2. Fetch all biometrics with sleep_wakeup
        # We only reprocess if sleep_wakeup exists, as that's our source of truth
        bio_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).not_.is_("sleep_wakeup", "null").execute()
        
        if not bio_res.data:
            print("No biometric records with sleep_wakeup found.")
            continue
            
        print(f"Found {len(bio_res.data)} records to check...")
        
        for row in bio_res.data:
            current_date_str = row["date"]
            wakeup_str = row["sleep_wakeup"]
            
            try:
                # Parse wakeup and adjust for offset
                utc_wakeup = datetime.fromisoformat(wakeup_str.replace("Z", "+00:00"))
                local_wakeup = utc_wakeup + timedelta(minutes=offset)
                new_date_str = local_wakeup.date().isoformat()
                
                if new_date_str != current_date_str:
                    print(f"  [SHIFT] {current_date_str} -> {new_date_str} (Wakeup: {wakeup_str})")
                    
                    # We can't just update the date because it's part of the PK.
                    # We need to delete and re-insert, or upsert with the new date.
                    # But if we upsert, we leave the old orphaned record.
                    
                    # 1. Delete old record
                    db.table("biometrics").delete().eq("athlete_id", athlete_id).eq("date", current_date_str).execute()
                    
                    # 2. Insert with new date (row is the full data)
                    new_row = {**row}
                    new_row["date"] = new_date_str
                    db.table("biometrics").insert(new_row).execute()
                else:
                    # print(f"  [OK] {current_date_str}")
                    pass
            except Exception as e:
                print(f"  [ERROR] Failed to process {current_date_str}: {e}")

    print("\n[OK] Biometric date alignment complete.")

if __name__ == "__main__":
    reprocess_biometric_dates()
