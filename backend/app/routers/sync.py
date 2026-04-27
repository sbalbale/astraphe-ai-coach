import urllib.parse
import secrets
from fastapi import APIRouter, Request, Response, HTTPException, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse
from app.dependencies import get_current_athlete, get_db
from app.services import whoop
from app.config import settings
from datetime import datetime
from app.models.workout import WorkoutPayload
from app.models.biometrics import DailyBiometrics
from app.services.processing import process_and_save_workout, process_and_save_biometrics

router = APIRouter(prefix=f"{settings.API_PREFIX}/sync", tags=["Sync & Webhooks"])

def get_clean_redirect_url():
    """Helper to ensure the redirect URL is consistent across authorize and callback."""
    base = settings.APP_BASE_URL.strip().rstrip('/')
    return f"{base}{settings.API_PREFIX}/sync/oauth/whoop/callback"

@router.post("/garmin/webhook")
async def garmin_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_db)):
    """Webhook receiver for Garmin Connect push notifications."""
    signature = request.headers.get("X-Garmin-Signature")
    if not signature:
        # For local testing, we might want to skip this or use a mock
        pass
    
    payload = await request.json()
    
    if "activities" in payload:
        for activity in payload["activities"]:
            try:
                athlete_id = get_athlete_by_garmin_id(db, activity.get("userId"))
                if not athlete_id: continue
                
                workout_payload = WorkoutPayload(
                    source="garmin",
                    external_id=str(activity.get("activityId")),
                    workout_type=map_garmin_sport(activity.get("activityType")),
                    start_time=datetime.utcfromtimestamp(activity.get("startTimeInSeconds")),
                    duration_seconds=activity.get("durationInSeconds"),
                    tss=activity.get("trainingStressScore") # Garmin sometimes provides this
                )
                background_tasks.add_task(process_and_save_workout, workout_payload, athlete_id, db)
            except Exception as e:
                print(f"Failed to process Garmin activity: {e}")

    if "bodyComps" in payload:
        for comp in payload["bodyComps"]:
            try:
                athlete_id = get_athlete_by_garmin_id(db, comp.get("userId"))
                if not athlete_id: continue
                
                weight_in_grams = comp.get("weightInGrams")
                if weight_in_grams:
                    db.table("athletes").update({
                        "weight_kg": round(weight_in_grams / 1000, 2)
                    }).eq("id", athlete_id).execute()
            except Exception as e:
                print(f"Failed to process Garmin body comp: {e}")

    return Response(status_code=200)

@router.post("/whoop/webhook")
async def whoop_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_db)):
    """Webhook receiver for WHOOP data push events."""
    signature = request.headers.get("X-WHOOP-Signature")
    if not signature:
        # raise HTTPException(status_code=401, detail="Missing WHOOP signature")
        pass
        
    body = await request.body()
    # if not whoop.verify_webhook_signature(body, signature):
    #     raise HTTPException(status_code=401, detail="Invalid WHOOP signature")
        
    payload = await request.json()
    event_type = payload.get("type")
    user_id = payload.get("user_id")
    
    token_record = db.table("oauth_tokens").select("*").eq("provider", "whoop").eq("external_user_id", user_id).execute()
    if not token_record.data:
        return Response(status_code=200) 
        
    access_token = token_record.data[0]["access_token"]
    athlete_id = token_record.data[0]["athlete_id"]

    try:
        if event_type == "recovery.updated":
            recovery_data = await whoop.fetch_recovery_data(access_token, payload["data"]["id"])
            bio_payload = DailyBiometrics(
                date=recovery_data["created_at"][:10],
                source="whoop",
                hrv_rmssd=recovery_data["score"]["hrv_rmssd_ms"],
                resting_hr=recovery_data["score"]["resting_heart_rate"],
                recovery_score=recovery_data["score"]["recovery_score"]
            )
            background_tasks.add_task(process_and_save_biometrics, bio_payload, athlete_id, db)
            
        elif event_type == "sleep.updated":
            sleep_data = await whoop.fetch_sleep_data(access_token, payload["data"]["id"])
            bio_payload = DailyBiometrics(
                date=sleep_data["start"][:10],
                source="whoop",
                sleep_score=sleep_data["score"]["sleep_performance_percentage"],
                sleep_duration_min=sleep_data["score"]["asleep_duration_ms"] / 60000
            )
            background_tasks.add_task(process_and_save_biometrics, bio_payload, athlete_id, db)
            
        elif event_type == "workout.updated":
            workout_data = await whoop.fetch_workout_data(access_token, payload["data"]["id"])
            workout_payload = WorkoutPayload(
                source="whoop",
                external_id=str(workout_data["id"]),
                workout_type=map_whoop_sport(workout_data["sport_id"]),
                start_time=workout_data["start"],
                duration_seconds=int((datetime.fromisoformat(workout_data["end"].replace('Z','')) - datetime.fromisoformat(workout_data["start"].replace('Z',''))).total_seconds())
            )
            background_tasks.add_task(process_and_save_workout, workout_payload, athlete_id, db)
            
    except Exception as e:
        print(f"Error processing WHOOP webhook: {e}")
        return Response(status_code=200)

    return Response(status_code=200)

@router.get("/oauth/whoop/authorize")
async def whoop_oauth_authorize(athlete_id: str = None):
    """Step 1: Redirect user to WHOOP for authorization."""
    redirect_url = get_clean_redirect_url()
    state = athlete_id or settings.TEST_ATHLETE_ID or secrets.token_urlsafe(16)
    
    params = {
        "response_type": "code",
        "client_id": settings.WHOOP_CLIENT_ID,
        "redirect_uri": redirect_url,
        "scope": "offline read:recovery read:sleep read:cycles read:workout read:profile read:body_measurement",
        "state": state
    }
    
    query_string = urllib.parse.urlencode(params)
    return RedirectResponse(url=f"{settings.WHOOP_OAUTH_AUTH_URL}?{query_string}")

@router.get("/oauth/whoop/callback")
async def whoop_oauth_callback(code: str, state: str = None, db = Depends(get_db)):
    """Step 2: WHOOP redirects back here with a code."""
    redirect_url = get_clean_redirect_url()
    
    try:
        token_data = await whoop.exchange_oauth_code(code, redirect_url)
        access_token = token_data.get("access_token")
        athlete_id = state
        
        profile = await whoop.fetch_profile(access_token)
        measurements = await whoop.fetch_body_measurement(access_token)
        
        db.table("athletes").upsert({
            "id": athlete_id,
            "display_name": profile.get("first_name", "Athlete"),
            "weight_kg": measurements.get("weight_kilograms"),
            "max_hr": measurements.get("max_heart_rate"),
        }).execute()

        db.table("oauth_tokens").upsert({
            "athlete_id": athlete_id,
            "provider": "whoop",
            "external_user_id": str(profile.get("user_id")),
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token"),
        }).execute()
        
        return RedirectResponse(url=f"{settings.MOBILE_DEEP_LINK_SCHEME}://connected?status=success")
        
    except Exception as e:
        print(f"ERROR in Callback: {str(e)}")
        return {"status": "error", "message": str(e)}

@router.get("/status")
async def get_sync_status(athlete_id: str = Depends(get_current_athlete), db=Depends(get_db)):
    """Returns connection status for all integrations."""
    # This should check oauth_tokens table for existence
    tokens = db.table("oauth_tokens").select("provider").eq("athlete_id", athlete_id).execute()
    providers = [t["provider"] for t in tokens.data]
    
    return {
        "integrations": {
            "garmin": {"connected": "garmin" in providers, "last_sync": "2026-04-26T10:14:00Z"},
            "whoop": {"connected": "whoop" in providers, "last_sync": None},
            "healthkit": {"connected": True, "last_sync": "2026-04-26T06:12:00Z"}
        }
    }

def get_athlete_by_garmin_id(db, garmin_id: str):
    """Looks up internal athlete_id by Garmin ID."""
    if not garmin_id: return None
    record = db.table("oauth_tokens").select("athlete_id").eq("provider", "garmin").eq("external_user_id", str(garmin_id)).execute()
    return record.data[0]["athlete_id"] if record.data else None

def map_garmin_sport(garmin_type: str) -> str:
    """Maps Garmin sports to internal enums."""
    mapping = {"RUNNING": "run", "CYCLING": "bike", "SWIMMING": "swim", "STRENGTH_TRAINING": "strength"}
    return mapping.get(garmin_type, "other")

def map_whoop_sport(sport_id: int) -> str:
    """Maps WHOOP sports to internal enums."""
    mapping = {1: "run", 8: "bike", 66: "strength", 70: "swim"} 
    return mapping.get(sport_id, "other")