import urllib.parse
import secrets
import asyncio
from fastapi import APIRouter, Request, Response, HTTPException, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse, HTMLResponse
from app.dependencies import get_current_athlete, get_user_db, get_admin_db
from app.services import whoop
from app.services.whoop_backfill import backfill_last_28_days
from app.config import settings
from datetime import datetime
from app.models.workout import WorkoutPayload
from app.models.biometrics import DailyBiometrics
from app.services.processing import process_and_save_workout, process_and_save_biometrics
from fastapi import status

router = APIRouter(prefix=f"{settings.API_PREFIX}/sync", tags=["Sync & Webhooks"])

def get_clean_redirect_url():
    """Helper to ensure the redirect URL is consistent across authorize and callback."""
    base = settings.APP_BASE_URL.strip().rstrip('/')
    return f"{base}{settings.API_PREFIX}/sync/oauth/whoop/callback"

@router.post("/garmin/webhook")
async def garmin_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
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
                    title=(str(activity.get("activityType") or "")).replace("_", " ").title() or None,
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
async def whoop_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    """Webhook receiver for WHOOP data push events."""
    signature = request.headers.get("X-WHOOP-Signature")
    if not signature:
        # raise HTTPException(status_code=401, detail="Missing WHOOP signature")
        pass
        
    body = await request.body()
    # if not whoop.verify_webhook_signature(body, signature):
    #     raise HTTPException(status_code=401, detail="Invalid WHOOP signature")

    if settings.WHOOP_WEBHOOK_LOG_RAW:
        try:
            raw = body.decode("utf-8", errors="replace")
            # Avoid flooding logs — WHOOP payloads can be large.
            print(f"[whoop.webhook.raw] {raw[:4000]}")
        except Exception as e:
            print(f"[whoop.webhook.raw] <failed to decode body>: {repr(e)}")
        
    payload = await request.json()
    event_type = payload.get("type")
    user_id = payload.get("user_id")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    event_id = data.get("id") or payload.get("id")

    # Lightweight debug line to confirm delivery + shape
    try:
        print(f"[whoop.webhook] type={event_type} user_id={user_id} event_id={event_id} keys={list(payload.keys())}")
    except Exception:
        pass
    
    token_record = (
        db.table("oauth_tokens")
        .select("*")
        .eq("provider", "whoop")
        .eq("external_user_id", str(user_id) if user_id is not None else "")
        .execute()
    )
    if not token_record.data:
        return Response(status_code=200) 
        
    token_row = token_record.data[0]
    access_token = token_row.get("access_token")
    refresh_token = token_row.get("refresh_token")
    athlete_id = token_row.get("athlete_id")

    async def _refresh_and_persist_token() -> str | None:
        if not refresh_token:
            return None
        token_data = await whoop.refresh_oauth_token(refresh_token)
        new_access = token_data.get("access_token")
        new_refresh = token_data.get("refresh_token") or refresh_token
        if new_access:
            db.table("oauth_tokens").update(
                {"access_token": new_access, "refresh_token": new_refresh}
            ).eq("provider", "whoop").eq("external_user_id", str(user_id)).execute()
        return new_access

    try:
        if event_type == "recovery.updated":
            if not event_id:
                return Response(status_code=200)
            try:
                recovery_data = await whoop.fetch_recovery_data(access_token, event_id)
            except HTTPException as e:
                if e.status_code == status.HTTP_401_UNAUTHORIZED:
                    new_access = await _refresh_and_persist_token()
                    if new_access:
                        recovery_data = await whoop.fetch_recovery_data(new_access, event_id)
                    else:
                        raise
                else:
                    raise
            bio_payload = DailyBiometrics(
                date=recovery_data["created_at"][:10],
                source="whoop",
                hrv_rmssd=recovery_data["score"]["hrv_rmssd_ms"],
                resting_hr=recovery_data["score"]["resting_heart_rate"],
                recovery_score=recovery_data["score"]["recovery_score"]
            )
            background_tasks.add_task(process_and_save_biometrics, bio_payload, athlete_id, db)
            
        elif event_type == "sleep.updated":
            if not event_id:
                return Response(status_code=200)
            try:
                sleep_data = await whoop.fetch_sleep_data(access_token, event_id)
            except HTTPException as e:
                if e.status_code == status.HTTP_401_UNAUTHORIZED:
                    new_access = await _refresh_and_persist_token()
                    if new_access:
                        sleep_data = await whoop.fetch_sleep_data(new_access, event_id)
                    else:
                        raise
                else:
                    raise
            score = sleep_data.get("score") or {}
            stage = score.get("stage_summary") or {}
            
            light = stage.get("total_light_sleep_time_milli")
            deep = stage.get("total_slow_wave_sleep_time_milli")
            rem = stage.get("total_rem_sleep_time_milli")
            awake = stage.get("total_awake_time_milli")
            total_sleep_ms = sum(v for v in (light, deep, rem) if isinstance(v, (int, float)))

            def _pct(ms):
                if not total_sleep_ms or not isinstance(ms, (int, float)):
                    return None
                return round((ms / total_sleep_ms) * 100.0, 1)

            bio_payload = DailyBiometrics(
                date=sleep_data["start"][:10],
                source="whoop",
                sleep_score=score.get("sleep_performance_percentage"),
                sleep_duration_min=int(total_sleep_ms / 60000) if total_sleep_ms else 0,
                sleep_deep_pct=_pct(deep),
                sleep_rem_pct=_pct(rem),
                sleep_light_pct=_pct(light),
                sleep_awake_pct=round((awake / (total_sleep_ms + awake)) * 100, 1) if (total_sleep_ms and awake) else 0.0,
                sleep_bedtime=sleep_data.get("start"),
                sleep_wakeup=sleep_data.get("end"),
                is_nap=sleep_data.get("nap", False)
            )
            background_tasks.add_task(process_and_save_biometrics, bio_payload, athlete_id, db)
            
        elif event_type == "workout.updated":
            if not event_id:
                return Response(status_code=200)
            try:
                workout_data = await whoop.fetch_workout_data(access_token, event_id)
            except HTTPException as e:
                if e.status_code == status.HTTP_401_UNAUTHORIZED:
                    new_access = await _refresh_and_persist_token()
                    if new_access:
                        workout_data = await whoop.fetch_workout_data(new_access, event_id)
                    else:
                        raise
                else:
                    raise
            # WorkoutPayload uses aliases: sport -> workout_type, started_at -> start_time
            start = workout_data.get("start") or workout_data.get("started_at")
            end = workout_data.get("end") or workout_data.get("ended_at")
            duration_seconds = None
            try:
                if start and end:
                    duration_seconds = int(
                        (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()
                    )
            except Exception:
                duration_seconds = None

            score = workout_data.get("score") if isinstance(workout_data.get("score"), dict) else {}
            zone = score.get("zone_durations") if isinstance(score.get("zone_durations"), dict) else {}
            total_zone_ms = sum(v for v in zone.values() if isinstance(v, (int, float)))
            def _pct(ms):
                if not total_zone_ms or not isinstance(ms, (int, float)):
                    return None
                return int(round((ms / total_zone_ms) * 100))

            workout_payload = WorkoutPayload(
                source="whoop",
                external_id=str(workout_data.get("id") or event_id),
                # Prefer sport_name when present; fall back to id mapping.
                sport=map_whoop_sport(workout_data.get("sport_name") or workout_data.get("sport_id") or workout_data.get("sport") or workout_data.get("sportId")),
                title=(workout_data.get("sport_name") or workout_data.get("sportName") or None),
                started_at=start,
                ended_at=end,
                duration_seconds=duration_seconds,
                distance_m=score.get("distance_meter") or score.get("distance_m") or workout_data.get("distance_m"),
                avg_hr=score.get("average_heart_rate") or score.get("avg_hr") or workout_data.get("avg_hr"),
                max_hr=score.get("max_heart_rate") or workout_data.get("max_hr"),
                hr_zone_0_pct=_pct(zone.get("zone_zero_milli")),
                hr_zone_1_pct=_pct(zone.get("zone_one_milli")),
                hr_zone_2_pct=_pct(zone.get("zone_two_milli")),
                hr_zone_3_pct=_pct(zone.get("zone_three_milli")),
                hr_zone_4_pct=_pct(zone.get("zone_four_milli")),
                hr_zone_5_pct=_pct(zone.get("zone_five_milli")),
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
    print(f"[whoop.oauth.authorize] redirect_uri={redirect_url} state={state}")
    
    params = {
        "response_type": "code",
        "client_id": settings.WHOOP_CLIENT_ID,
        "redirect_uri": redirect_url,
        "scope": "offline read:recovery read:sleep read:cycles read:workout read:profile read:body_measurement",
        "state": state
    }
    
    query_string = urllib.parse.urlencode(params)
    print(f"[whoop.oauth.authorize] auth_url={settings.WHOOP_OAUTH_AUTH_URL}?{query_string}")
    return RedirectResponse(url=f"{settings.WHOOP_OAUTH_AUTH_URL}?{query_string}")

@router.get("/oauth/whoop/callback")
async def whoop_oauth_callback(code: str, state: str = None, db = Depends(get_admin_db)):
    """Step 2: WHOOP redirects back here with a code."""
    redirect_url = get_clean_redirect_url()
    print(f"[whoop.oauth.callback] state={state} redirect_uri={redirect_url}")
    
    try:
        token_data = await whoop.exchange_oauth_code(code, redirect_url)
        access_token = token_data.get("access_token")
        athlete_id = state
        
        profile = await whoop.fetch_profile(access_token)
        measurements = await whoop.fetch_body_measurement(access_token)
        
        # The athlete row is created at signup and includes a NOT NULL user_id.
        # Do NOT upsert here (would try to insert with null user_id). Instead update the existing row.
        existing = db.table("athletes").select("id").eq("id", athlete_id).single().execute()
        if not getattr(existing, "data", None):
            raise HTTPException(status_code=404, detail="Athlete not found for WHOOP callback state")

        db.table("athletes").update({
            "display_name": profile.get("first_name", "Athlete"),
            "weight_kg": measurements.get("weight_kilograms"),
            "max_hr": measurements.get("max_heart_rate"),
        }).eq("id", athlete_id).execute()

        db.table("oauth_tokens").upsert({
            "athlete_id": athlete_id,
            "provider": "whoop",
            "external_user_id": str(profile.get("user_id")),
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token"),
        }).execute()

        # Kick off an initial backfill so the app has immediate history.
        # Runs in-process; in production we'd likely use a job queue.
        try:
            asyncio.create_task(backfill_last_28_days(athlete_id, access_token, db))
        except Exception as e:
            print(f"[whoop.backfill] failed to start: {repr(e)}")
        
        deep_link = f"{settings.MOBILE_DEEP_LINK_SCHEME}://connected?provider=whoop&status=success"
        # When this flow runs in a desktop browser, custom URI schemes won't open reliably.
        # Return a tiny HTML page that attempts the deep link and provides a manual link.
        return HTMLResponse(
            f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>WHOOP Connected</title>
  </head>
  <body style="font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; padding: 24px;">
    <h2>WHOOP connected</h2>
    <p>Your WHOOP account is connected. You can return to the app.</p>
    <p><a href="{deep_link}">Open ASTRAPE</a></p>
    <script>
      try {{ window.location.href = "{deep_link}"; }} catch (e) {{}}
    </script>
  </body>
</html>""",
            status_code=200,
        )
        
    except Exception as e:
        print(f"[whoop.oauth.callback] ERROR: {repr(e)}")
        return {"status": "error", "message": str(e)}

@router.get("/status")
async def get_sync_status(athlete_id: str = Depends(get_current_athlete), db=Depends(get_user_db)):
    """Returns connection status for all integrations."""
    # This should check oauth_tokens table for existence
    tokens = db.table("oauth_tokens").select("provider").eq("athlete_id", athlete_id).execute()
    providers = [t["provider"] for t in tokens.data]
    
    return {
        "integrations": {
            "garmin": {"connected": "garmin" in providers, "last_sync": "2026-04-26T10:14:00Z"},
            "whoop": {"connected": "whoop" in providers, "last_sync": None},
            # HealthKit does not use OAuth tokens. Until the mobile client sends a verifiable
            # handshake/sync marker, report it as disconnected.
            "healthkit": {"connected": False, "last_sync": None}
        }
    }

@router.delete("/{provider}")
async def unlink_integration(
    provider: str,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db)
):
    """Unlinks a third-party integration by removing its OAuth tokens."""
    db.table("oauth_tokens").delete().eq("athlete_id", athlete_id).eq("provider", provider).execute()
    return {"status": "success", "message": f"{provider.capitalize()} unlinked successfully"}

def get_athlete_by_garmin_id(db, garmin_id: str):
    """Looks up internal athlete_id by Garmin ID."""
    if not garmin_id: return None
    record = db.table("oauth_tokens").select("athlete_id").eq("provider", "garmin").eq("external_user_id", str(garmin_id)).execute()
    return record.data[0]["athlete_id"] if record.data else None

def map_garmin_sport(garmin_type: str) -> str:
    """Maps Garmin sports to internal enums."""
    mapping = {"RUNNING": "run", "CYCLING": "bike", "SWIMMING": "swim", "STRENGTH_TRAINING": "strength"}
    return mapping.get(garmin_type, "other")

def map_whoop_sport(sport: object) -> str:
    """Maps WHOOP sports to internal enums."""
    # If we get the sport_name string, map it first.
    if isinstance(sport, str):
        s = sport.strip().lower()
        if s in ("weightlifting", "weight lifting", "strength training", "strength_training", "gym", "strength"):
            return "strength"
        if s in ("running", "run"):
            return "run"
        if s in ("cycling", "bike", "biking"):
            return "bike"
        if s in ("swimming", "swim"):
            return "swim"
        if s in ("rowing", "row"):
            return "rowing"
        # If it's a numeric string, fall through to id mapping.
        if s.isdigit():
            sport = int(s)
        else:
            return "other"

    # Sport id mapping
    if isinstance(sport, int):
        mapping = {
            1: "run",
            8: "bike",
            66: "strength",   # WHOOP strength/weightlifting
            70: "swim",
        }
        return mapping.get(sport, "other")

    return "other"