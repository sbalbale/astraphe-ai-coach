import hashlib
import hmac
import json
import urllib.parse
import secrets
import asyncio
from html import escape
from urllib.parse import urlparse
from fastapi import APIRouter, Request, Response, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from starlette.requests import ClientDisconnect
from app.dependencies import get_current_athlete, get_user_db, get_admin_db
from app.services import whoop
from app.services import strava as strava_service
from app.services.strava import backfill_historical_data as strava_backfill
from app.services.whoop_backfill import backfill_historical_data
from app.config import settings
from datetime import datetime, timedelta
from app.models.workout import WorkoutPayload
from app.models.biometrics import DailyBiometrics
from app.services.processing import process_and_save_workout, process_and_save_biometrics
from fastapi import status

router = APIRouter(prefix=f"{settings.API_PREFIX}/sync", tags=["Sync & Webhooks"])

# Allowlist of hosts that may be used as a post-OAuth web_return redirect target.
# Add your production and staging domains here.
_ALLOWED_RETURN_HOSTS: frozenset[str] = frozenset({
    "astrape.app",
    "localhost",
    "127.0.0.1",
})

def _safe_web_return(url: str | None) -> str | None:
    """Returns the URL only if its host is on the allowlist, else None."""
    if not url:
        return None
    try:
        host = urlparse(url).hostname or ""
        if host in _ALLOWED_RETURN_HOSTS or host.endswith(".astrape.app"):
            return url
    except Exception:
        pass
    return None


def get_clean_redirect_url():
    """Helper to ensure the redirect URL is consistent across authorize and callback."""
    base = settings.APP_BASE_URL.strip().rstrip('/')
    return f"{base}{settings.API_PREFIX}/sync/oauth/whoop/callback"


def get_clean_strava_redirect_url():
    """Strava OAuth redirect_uri — must match authorize and token exchange exactly."""
    base = settings.APP_BASE_URL.strip().rstrip("/")
    return f"{base}{settings.API_PREFIX}/sync/oauth/strava/callback"


def _oauth_connected_success_response(deep_link: str, provider: str) -> HTMLResponse:
    """In-app browser landing page after OAuth — same UX as WHOOP, themed per provider."""
    themes = {
        "whoop": {
            "page_title": "ASTRAPE • WHOOP Connected",
            "headline": "WHOOP connected",
            "body": "Your WHOOP account is now linked to ASTRAPE. You can safely return to the app.",
            "grad1": "rgba(124, 58, 237, 0.35)",
            "grad2": "rgba(34, 211, 238, 0.22)",
            "brand_a": "#7C3AED",
            "brand_b": "#22D3EE",
            "logo_shadow": "rgba(124, 58, 237, 0.25)",
            "btn_shadow": "rgba(124, 58, 237, 0.22)",
        },
        "strava": {
            "page_title": "ASTRAPE • Strava Connected",
            "headline": "Strava connected",
            "body": "Your Strava account is now linked to ASTRAPE. Recent activities will sync in the background—you can return to the app whenever you're ready.",
            "grad1": "rgba(252, 76, 2, 0.42)",
            "grad2": "rgba(255, 140, 90, 0.20)",
            "brand_a": "#FC4C02",
            "brand_b": "#FF9F66",
            "logo_shadow": "rgba(252, 76, 2, 0.40)",
            "btn_shadow": "rgba(252, 76, 2, 0.30)",
        },
    }
    t = themes.get(provider, themes["whoop"])
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{t["page_title"]}</title>
    <meta name="color-scheme" content="dark light" />
    <style>
      :root {{
        --bg0: #070A12;
        --bg1: #0B1022;
        --card: rgba(255, 255, 255, 0.06);
        --cardBorder: rgba(255, 255, 255, 0.10);
        --text: rgba(255, 255, 255, 0.92);
        --muted: rgba(255, 255, 255, 0.70);
        --brandA: {t["brand_a"]};
        --brandB: {t["brand_b"]};
        --ok: #34D399;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        color: var(--text);
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
        background:
          radial-gradient(1200px 600px at 20% -10%, {t["grad1"]}, transparent 60%),
          radial-gradient(900px 500px at 90% 10%, {t["grad2"]}, transparent 55%),
          linear-gradient(180deg, var(--bg0), var(--bg1));
        display: grid;
        place-items: center;
        padding: 24px;
      }}
      .wrap {{ width: min(560px, 100%); }}
      .card {{
        background: var(--card);
        border: 1px solid var(--cardBorder);
        border-radius: 18px;
        padding: 22px;
        backdrop-filter: blur(10px);
        box-shadow:
          0 24px 50px rgba(0, 0, 0, 0.45),
          inset 0 1px 0 rgba(255, 255, 255, 0.05);
      }}
      .brand {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 14px;
      }}
      .logo {{
        width: 36px;
        height: 36px;
        border-radius: 12px;
        background: linear-gradient(135deg, var(--brandA), var(--brandB));
        box-shadow: 0 10px 24px {t["logo_shadow"]};
      }}
      .brand h1 {{
        margin: 0;
        font-size: 14px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .title {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 6px 0 8px;
      }}
      .check {{
        width: 22px;
        height: 22px;
        border-radius: 999px;
        display: grid;
        place-items: center;
        background: rgba(52, 211, 153, 0.15);
        border: 1px solid rgba(52, 211, 153, 0.35);
        color: var(--ok);
        flex: 0 0 auto;
      }}
      h2 {{
        margin: 0;
        font-size: 22px;
        line-height: 1.2;
      }}
      p {{
        margin: 0;
        color: var(--muted);
        line-height: 1.5;
      }}
      .actions {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 16px;
      }}
      a.btn, button.btn {{
        appearance: none;
        border: 0;
        cursor: pointer;
        text-decoration: none;
        font-weight: 600;
        padding: 12px 14px;
        border-radius: 12px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
      }}
      .primary {{
        color: #081018;
        background: linear-gradient(135deg, var(--brandA), var(--brandB));
        box-shadow: 0 18px 34px {t["btn_shadow"]};
      }}
      .secondary {{
        color: var(--text);
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.12);
      }}
      .tiny {{
        font-size: 12px;
        margin-top: 14px;
        color: rgba(255, 255, 255, 0.55);
      }}
      code {{
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        font-size: 12px;
        color: rgba(255, 255, 255, 0.78);
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <div class="brand">
          <div class="logo" aria-hidden="true"></div>
          <h1>ASTRAPE AI Coach</h1>
        </div>

        <div class="title">
          <div class="check" aria-hidden="true">✓</div>
          <h2>{t["headline"]}</h2>
        </div>
        <p>{t["body"]}</p>

        <div class="actions">
          <a class="btn primary" href="{escape(deep_link, quote=True)}">Open ASTRAPE</a>
          <button class="btn secondary" type="button" id="copyBtn">Copy link</button>
        </div>

        <div class="tiny">
          If your browser didn’t open the app automatically, use the button above. Link:
          <br />
          <code id="dl">{escape(deep_link)}</code>
        </div>
      </div>
    </div>

    <script>
      const deepLink = {json.dumps(deep_link)};

      setTimeout(() => {{
        try {{ window.location.href = deepLink; }} catch (e) {{}}
      }}, 50);

      const copyBtn = document.getElementById("copyBtn");
      copyBtn?.addEventListener("click", async () => {{
        try {{
          await navigator.clipboard.writeText(deepLink);
          copyBtn.textContent = "Copied";
          setTimeout(() => (copyBtn.textContent = "Copy link"), 1200);
        }} catch (e) {{
          window.prompt("Copy this link:", deepLink);
        }}
      }});
    </script>
  </body>
</html>""",
        status_code=200,
    )

@router.post("/garmin/webhook")
async def garmin_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    """Webhook receiver for Garmin Connect push notifications."""
    body = await request.body()
    signature = request.headers.get("X-Garmin-Signature", "")
    garmin_secret = settings.GARMIN_WEBHOOK_SECRET
    if garmin_secret:
        expected = hmac.new(
            garmin_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=401, detail="Invalid Garmin signature")

    try:
        payload = json.loads(body)
    except Exception:
        return Response(status_code=400)
    
    if "activities" in payload:
        for activity in payload["activities"]:
            try:
                athlete_id = get_athlete_by_garmin_id(db, activity.get("userId"))
                if not athlete_id: continue

                # Fetch athlete timezone for correct date mapping
                athlete_res = db.table("athletes").select("timezone_offset_min").eq("id", athlete_id).single().execute()
                offset = (athlete_res.data.get("timezone_offset_min") or 0) if athlete_res.data else 0
                
                utc_start = datetime.utcfromtimestamp(activity.get("startTimeInSeconds"))
                local_start = utc_start + timedelta(minutes=offset)
                
                workout_payload = WorkoutPayload(
                    source="garmin",
                    external_id=str(activity.get("activityId")),
                    workout_type=map_garmin_sport(activity.get("activityType")),
                    title=(str(activity.get("activityType") or "")).replace("_", " ").title() or None,
                    start_time=utc_start,
                    duration_seconds=activity.get("durationInSeconds"),
                    tss=activity.get("trainingStressScore")
                )
                # Ensure the workout payload date (if used) is local
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
    try:
        body = await request.body()
    except ClientDisconnect:
        return Response(status_code=200)

    signature = request.headers.get("X-WHOOP-Signature", "")
    if not signature or not whoop.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid or missing WHOOP signature")

    if settings.WHOOP_WEBHOOK_LOG_RAW:
        try:
            raw = body.decode("utf-8", errors="replace")
            # Avoid flooding logs — WHOOP payloads can be large.
            print(f"[whoop.webhook.raw] {raw[:4000]}")
        except Exception as e:
            print(f"[whoop.webhook.raw] <failed to decode body>: {repr(e)}")
        
    try:
        payload = await request.json()
    except ClientDisconnect:
        return Response(status_code=200)
    except Exception:
        # Bad payload should not trigger retries if the sender is flaky.
        return Response(status_code=200)
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
            # Fetch athlete timezone for correct date mapping
            athlete_res = db.table("athletes").select("timezone_offset_min").eq("id", athlete_id).single().execute()
            offset = (athlete_res.data.get("timezone_offset_min") or 0) if athlete_res.data else 0
            
            # For recovery, created_at is usually the wake-up morning
            utc_created = datetime.fromisoformat(recovery_data["created_at"].replace("Z", "+00:00"))
            local_created = utc_created + timedelta(minutes=offset)

            bio_payload = DailyBiometrics(
                date=local_created.date(),
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

            # Fetch athlete timezone for correct date mapping
            athlete_res = db.table("athletes").select("timezone_offset_min").eq("id", athlete_id).single().execute()
            offset = (athlete_res.data.get("timezone_offset_min") or 0) if athlete_res.data else 0

            # For WHOOP, the "biological day" is most consistently represented 
            # by the day you wake up (end of sleep). This aligns with recovery scores.
            wake_dt = datetime.fromisoformat(sleep_data["end"].replace("Z", "+00:00"))
            local_wake_dt = wake_dt + timedelta(minutes=offset)
            
            bio_payload = DailyBiometrics(
                date=local_wake_dt.date(),
                source="whoop",
                external_id=str(sleep_data.get("id") or event_id),
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
            z1_pct, z2_pct, z3_pct, z4_pct, z5_pct = whoop.hr_zone_pct_from_whoop_zone_millis(zone)

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
                hr_zone_0_pct=None,
                hr_zone_1_pct=z1_pct,
                hr_zone_2_pct=z2_pct,
                hr_zone_3_pct=z3_pct,
                hr_zone_4_pct=z4_pct,
                hr_zone_5_pct=z5_pct,
            )
            background_tasks.add_task(process_and_save_workout, workout_payload, athlete_id, db)
            
    except Exception as e:
        print(f"Error processing WHOOP webhook: {e}")
        return Response(status_code=200)

    return Response(status_code=200)


def _webhook_int(value) -> int | None:
    """Coerce Strava JSON numeric ids to int for DB / service calls."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.get("/strava/webhook")
async def strava_webhook_verify(
    request: Request,
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Strava calls this once when you register the webhook subscription."""
    if hub_mode == "subscribe" and hub_verify_token == settings.STRAVA_WEBHOOK_VERIFY_TOKEN:
        return {"hub.challenge": hub_challenge}
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/strava/webhook")
async def strava_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db=Depends(get_admin_db),
):
    """Receives activity create/update/delete events from Strava."""
    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=200)

    print(
        f"[strava.webhook] aspect={payload.get('aspect_type')} "
        f"object={payload.get('object_type')} id={payload.get('object_id')}"
    )

    aspect = payload.get("aspect_type")
    obj_type = payload.get("object_type")
    activity_id = _webhook_int(payload.get("object_id"))
    owner_strava_id = _webhook_int(payload.get("owner_id"))

    # Strava does not sign webhook payloads, so we verify ownership against our
    # own database before acting on any event. This prevents unauthenticated
    # callers from triggering ingestion or corrupting workout data.
    if owner_strava_id is None:
        return Response(status_code=200)

    owner_token = (
        db.table("oauth_tokens")
        .select("athlete_id")
        .eq("provider", "strava")
        .eq("external_user_id", str(owner_strava_id))
        .maybe_single()
        .execute()
    )
    if not owner_token.data:
        return Response(status_code=200)

    athlete_id = owner_token.data["athlete_id"]

    if obj_type == "activity" and aspect == "create" and activity_id is not None:
        background_tasks.add_task(
            strava_service.ingest_strava_activity,
            owner_strava_id,
            activity_id,
            db,
        )
    elif obj_type == "activity" and aspect == "delete" and activity_id is not None:
        # Scope the delete to the verified athlete so a spoofed event cannot
        # null out strava_activity_id on another user's workout.
        db.table("workouts").update({"strava_activity_id": None}).eq(
            "athlete_id", athlete_id
        ).eq("strava_activity_id", activity_id).execute()

    return Response(status_code=200)


@router.get("/oauth/whoop/authorize")
async def whoop_oauth_authorize(
    web_return: str = None,
    athlete_id: str = Depends(get_current_athlete),
):
    """Step 1: Redirect authenticated user to WHOOP for authorization."""
    redirect_url = get_clean_redirect_url()
    state = athlete_id
    if web_return and _safe_web_return(web_return):
        state = f"{state}|{web_return}"
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
async def whoop_oauth_callback(
    code: str,
    background_tasks: BackgroundTasks,
    state: str = None,
    db = Depends(get_admin_db),
):
    """Step 2: WHOOP redirects back here with a code."""
    print(f"[whoop.oauth.callback] !!! COLD START callback reached !!! state={state}")
    redirect_url = get_clean_redirect_url()
    try:
        print(f"[whoop.oauth.callback] Exchanging code for tokens... redirect_uri={redirect_url}")
        token_data = await whoop.exchange_oauth_code(code, redirect_url)
        access_token = token_data.get("access_token")
        print(f"[whoop.oauth.callback] Token exchange SUCCESS")
        
        web_return = None
        if state and "|" in state:
            athlete_id, web_return = state.split("|", 1)
        else:
            athlete_id = state if state != "undefined" else None
        if not athlete_id:
             print(f"[whoop.oauth.callback] ERROR: athlete_id is missing or undefined")
             raise HTTPException(status_code=400, detail="Missing athlete_id")

        # Save tokens first (lightweight)
        print(f"[whoop.oauth.callback] Saving tokens to DB for athlete {athlete_id}...")
        db.table("oauth_tokens").upsert({
            "athlete_id": athlete_id,
            "provider": "whoop",
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token"),
        }).execute()
        print(f"[whoop.oauth.callback] Token persistence SUCCESS")

        # Everything else in background.
        # NOTE: FastAPI only injects BackgroundTasks reliably when it is an explicit dependency.
        # When this handler is called without an injected instance (e.g. mis-configured signature),
        # fall back to running the backfill asynchronously in-process so we still populate data.
        print(f"[whoop.oauth.callback] Scheduling background backfill task (90d)...")
        # Fire-and-forget: backfill catches its own errors so OAuth redirect is never blocked.
        asyncio.create_task(backfill_historical_data(athlete_id, access_token, None, 90))
        print(f"[whoop.oauth.callback] Backfill scheduled")
        
        print(f"[whoop.oauth.callback] Sending HTML response...")
        
        
        deep_link = f"{settings.MOBILE_DEEP_LINK_SCHEME}://connected?provider=whoop&status=success"
        if safe_url := _safe_web_return(web_return):
            return RedirectResponse(url=f"{safe_url}?provider=whoop&status=success")
        return _oauth_connected_success_response(deep_link, "whoop")

    except Exception as e:
        print(f"[whoop.oauth.callback] ERROR: {repr(e)}")
        return {"status": "error", "message": "WHOOP connection failed. Please try again."}


@router.get("/oauth/strava/authorize")
async def strava_oauth_authorize(
    web_return: str = None,
    athlete_id: str = Depends(get_current_athlete),
):
    """Redirect authenticated user to Strava for authorization."""
    if not settings.STRAVA_CLIENT_ID or not settings.STRAVA_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Strava OAuth is not configured")
    callback_url = get_clean_strava_redirect_url()
    state = athlete_id
    if web_return and _safe_web_return(web_return):
        state = f"{state}|{web_return}"
    params = {
        "client_id": settings.STRAVA_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": callback_url,
        "approval_prompt": "auto",
        "scope": "activity:read_all,profile:read_all",
        "state": state,
    }
    return RedirectResponse(
        url=f"https://www.strava.com/oauth/authorize?{urllib.parse.urlencode(params)}"
    )


@router.get("/oauth/strava/callback")
async def strava_oauth_callback(
    code: str,
    background_tasks: BackgroundTasks,
    state: str | None = None,
    db=Depends(get_admin_db),
):
    """Exchange code for tokens, store, and kick off backfill."""
    callback_url = get_clean_strava_redirect_url()
    try:
        web_return = None
        if state and "|" in state:
            athlete_id, web_return = state.split("|", 1)
        else:
            athlete_id = state
        if not athlete_id or athlete_id == "undefined":
            raise HTTPException(status_code=400, detail="Missing athlete_id in state")

        token_data = await strava_service.exchange_oauth_code(code, callback_url)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_iso = strava_service.strava_oauth_expires_at_iso(token_data)

        strava_athlete = token_data.get("athlete") or {}
        strava_athlete_id = strava_athlete.get("id") if isinstance(strava_athlete, dict) else None
        if strava_athlete_id is None:
            strava_athlete_id = await strava_service.get_athlete_strava_id(access_token)
        if strava_athlete_id is not None:
            try:
                strava_athlete_id = int(strava_athlete_id)
            except (TypeError, ValueError):
                strava_athlete_id = None

        if not access_token:
            raise HTTPException(status_code=400, detail="Token exchange failed")

        token_row: dict = {
            "athlete_id": athlete_id,
            "provider": "strava",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "external_user_id": str(strava_athlete_id) if strava_athlete_id is not None else None,
        }
        if expires_iso is not None:
            token_row["expires_at"] = expires_iso

        db.table("oauth_tokens").upsert(
            token_row,
            on_conflict="athlete_id,provider",
        ).execute()

        if strava_athlete_id is not None:
            db.table("athletes").update({"strava_athlete_id": strava_athlete_id}).eq(
                "id", athlete_id
            ).execute()

        if strava_athlete_id is not None:
            if background_tasks is not None:
                background_tasks.add_task(
                    strava_backfill,
                    athlete_id,
                    strava_athlete_id,
                    access_token,
                    db,
                    90,
                )
            else:
                asyncio.create_task(
                    strava_backfill(athlete_id, strava_athlete_id, access_token, db, 90)
                )
        else:
            print(
                f"[strava.oauth.callback] Strava athlete id unresolved; "
                f"tokens saved, skipping backfill athlete_id={athlete_id}"
            )

        deep_link = f"{settings.MOBILE_DEEP_LINK_SCHEME}://connected?provider=strava&status=success"
        if safe_url := _safe_web_return(web_return):
            return RedirectResponse(url=f"{safe_url}?provider=strava&status=success")
        return _oauth_connected_success_response(deep_link, "strava")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[strava.oauth.callback] ERROR: {repr(e)}")
        return {"status": "error", "message": "Strava connection failed. Please try again."}


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
            "strava": {"connected": "strava" in providers, "last_sync": None},
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
    prov = (provider or "").strip().lower()
    if not prov:
        raise HTTPException(status_code=400, detail="Missing provider")

    # Delete tokens owned by this athlete for the provider.
    db.table("oauth_tokens").delete().eq("athlete_id", athlete_id).eq("provider", prov).execute()

    # Return whether anything remains (helps clients update UI deterministically).
    remaining = (
        db.table("oauth_tokens")
        .select("id")
        .eq("athlete_id", athlete_id)
        .eq("provider", prov)
        .execute()
    )
    still_connected = bool(getattr(remaining, "data", None))

    return {
        "status": "success",
        "provider": prov,
        "connected": still_connected,
        "message": f"{prov.capitalize()} unlinked successfully" if not still_connected else f"{prov.capitalize()} unlink requested",
    }


@router.post("/whoop/backfill")
async def whoop_backfill_now(
    days: int = 90,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
    admin_db=Depends(get_admin_db),
):
    """
    Manually trigger a WHOOP backfill for the authenticated athlete.
    Useful for local/dev recovery when the OAuth callback backfill fails mid-way.
    """
    d = max(1, min(int(days), 365))
    tok = (
        admin_db.table("oauth_tokens")
        .select("access_token")
        .eq("athlete_id", athlete_id)
        .eq("provider", "whoop")
        .maybe_single()
        .execute()
    )
    access_token = (tok.data or {}).get("access_token") if tok else None
    if not access_token:
        raise HTTPException(status_code=400, detail="WHOOP not connected")

    asyncio.create_task(backfill_historical_data(athlete_id, access_token, admin_db, d))
    return {"status": "success", "scheduled": True, "days": d}

def get_athlete_by_garmin_id(db, garmin_id: str):
    """Looks up internal athlete_id by Garmin ID."""
    if not garmin_id: return None
    record = db.table("oauth_tokens").select("athlete_id").eq("provider", "garmin").eq("external_user_id", str(garmin_id)).execute()
    return record.data[0]["athlete_id"] if record.data else None

def map_garmin_sport(garmin_type: str) -> str:
    """Maps Garmin sports to internal enums."""
    mapping = {
        "RUNNING": "run",
        "CYCLING": "bike",
        "SWIMMING": "swim",
        "STRENGTH_TRAINING": "strength",
        "YOGA": "mobility",
        "PILATES": "mobility",
        "MEDITATION": "mobility",
        "BREATHING": "mobility",
        "TAI_CHI": "mobility",
        "STRETCHING": "mobility",
        "MOBILITY": "mobility",
    }
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
            return "row"
        if s in (
            "yoga",
            "mobility",
            "stretching",
            "stretch",
            "pilates",
            "barre",
            "tai chi",
            "tai_chi",
            "meditation",
        ):
            return "mobility"
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
            44: "mobility",   # Yoga (WHOOP sport id)
        }
        return mapping.get(sport, "other")

    return "other"