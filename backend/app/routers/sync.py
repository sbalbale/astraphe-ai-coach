import hashlib
import hmac
import json
import urllib.parse
import secrets
import asyncio
from typing import Any
from html import escape
from urllib.parse import urlparse
from fastapi import APIRouter, Request, Response, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect
from app.dependencies import get_current_athlete, get_user_db, get_admin_db
from app.services import whoop
from app.services import strava as strava_service
from app.services import intervals_icu as intervals_icu_service
from app.services.strava import backfill_historical_data as strava_backfill
from app.services.whoop_backfill import backfill_biometrics_only, backfill_historical_data
from app.config import settings
from datetime import date, datetime, timedelta, timezone
from app.services.token_refresh import token_expires_at
from app.models.workout import WorkoutPayload
from app.models.biometrics import DailyBiometrics
from app.services.processing import (
    process_and_save_workout,
    process_and_save_biometrics,
    reprocess_athlete_metrics,
    refresh_all_daily_strain_sync,
)
from app.services.ai_coach import invalidate_context_cache
from fastapi import status
from typing import Optional, Tuple

router = APIRouter(prefix=f"{settings.API_PREFIX}/sync", tags=["Sync & Webhooks"])

# Allowlist of hosts that may be used as a post-OAuth web_return redirect target.
# Add your production and staging domains here.
_ALLOWED_RETURN_HOSTS: frozenset[str] = frozenset({
    "astrapheai.com",
    "app.astrapheai.com",
    "localhost",
    "127.0.0.1",
})

def _safe_web_return(url: str | None) -> str | None:
    """Returns the URL only if its host is on the allowlist, else None."""
    if not url:
        return None
    try:
        host = urlparse(url).hostname or ""
        if host in _ALLOWED_RETURN_HOSTS or host.endswith(".astrapheai.com"):
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


def _oauth_state(athlete_id: str, web_return: str | None) -> str:
    state = athlete_id
    if web_return and _safe_web_return(web_return):
        state = f"{state}|{web_return}"
    return state


class IntervalsIcuConnectPayload(BaseModel):
    intervals_athlete_id: str = Field(..., min_length=1, max_length=80)
    api_key: str = Field(..., min_length=1, max_length=512)
    days: int = Field(default=90, ge=1, le=365)


def _clean_intervals_athlete_id(raw: str) -> str:
    athlete_id = (raw or "").strip()
    if not athlete_id:
        raise HTTPException(status_code=400, detail="Intervals.icu athlete ID is required")
    return athlete_id


def _clean_intervals_api_key(raw: str) -> str:
    api_key = (raw or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="Intervals.icu API key is required")
    return api_key


def _schedule_intervals_backfill(
    background_tasks: BackgroundTasks | None,
    athlete_id: str,
    intervals_athlete_id: str,
    api_key: str,
    db,
    days: int,
) -> None:
    if background_tasks is not None:
        background_tasks.add_task(
            intervals_icu_service.backfill_historical_data,
            athlete_id,
            intervals_athlete_id,
            api_key,
            db,
            days,
        )
    else:
        asyncio.create_task(
            intervals_icu_service.backfill_historical_data(
                athlete_id,
                intervals_athlete_id,
                api_key,
                db,
                days,
            )
        )


def build_whoop_oauth_authorize_url(athlete_id: str, web_return: str | None = None) -> str:
    redirect_url = get_clean_redirect_url()
    state = _oauth_state(athlete_id, web_return)
    params = {
        "response_type": "code",
        "client_id": settings.WHOOP_CLIENT_ID,
        "redirect_uri": redirect_url,
        "scope": "offline read:recovery read:sleep read:cycles read:workout read:profile read:body_measurement",
        "state": state,
    }
    return f"{settings.WHOOP_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"


def build_strava_oauth_authorize_url(athlete_id: str, web_return: str | None = None) -> str:
    callback_url = get_clean_strava_redirect_url()
    state = _oauth_state(athlete_id, web_return)
    params = {
        "client_id": settings.STRAVA_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": callback_url,
        "approval_prompt": "auto",
        "scope": "activity:read_all,profile:read_all",
        "state": state,
    }
    return f"https://www.strava.com/oauth/authorize?{urllib.parse.urlencode(params)}"


def _oauth_connected_success_response(deep_link: str, provider: str) -> HTMLResponse:
    """In-app browser landing page after OAuth — same UX as WHOOP, themed per provider."""
    themes = {
        "whoop": {
            "page_title": "ASTRAPHE • WHOOP Connected",
            "headline": "WHOOP connected",
            "body": "Your WHOOP account is now linked to ASTRAPHE. You can safely return to the app.",
            "grad1": "rgba(124, 58, 237, 0.35)",
            "grad2": "rgba(34, 211, 238, 0.22)",
            "brand_a": "#7C3AED",
            "brand_b": "#22D3EE",
            "logo_shadow": "rgba(124, 58, 237, 0.25)",
            "btn_shadow": "rgba(124, 58, 237, 0.22)",
        },
        "strava": {
            "page_title": "ASTRAPHE • Strava Connected",
            "headline": "Strava connected",
            "body": "Your Strava account is now linked to ASTRAPHE. Recent activities will sync in the background—you can return to the app whenever you're ready.",
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
          <h1>ASTRAPHE AI Coach</h1>
        </div>

        <div class="title">
          <div class="check" aria-hidden="true">✓</div>
          <h2>{t["headline"]}</h2>
        </div>
        <p>{t["body"]}</p>

        <div class="actions">
          <a class="btn primary" href="{escape(deep_link, quote=True)}">Open ASTRAPHE</a>
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
                athlete_id = await asyncio.to_thread(get_athlete_by_garmin_id, db, activity.get("userId"))
                if not athlete_id: continue

                # Fetch athlete timezone for correct date mapping
                athlete_res = await asyncio.to_thread(
                    db.table("athletes").select("timezone_offset_min").eq("id", athlete_id).single().execute
                )
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
                athlete_id = await asyncio.to_thread(get_athlete_by_garmin_id, db, comp.get("userId"))
                if not athlete_id: continue

                weight_in_grams = comp.get("weightInGrams")
                if weight_in_grams:
                    await asyncio.to_thread(
                        db.table("athletes").update({
                            "weight_kg": round(weight_in_grams / 1000, 2)
                        }).eq("id", athlete_id).execute
                    )
            except Exception as e:
                print(f"Failed to process Garmin body comp: {e}")

    return Response(status_code=200)


WHOOP_RECOVERY_RETRY_DELAYS_SEC = (120, 600)


def _coerce_float(v) -> float | None:
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        f = float(v)
        return f if f > 0 else None
    except Exception:
        return None


def _parse_whoop_height_cm(profile: dict | None, body: dict | None) -> float | None:
    """
    WHOOP v2 returns different shapes depending on endpoint/version.
    Be permissive and extract height in cm from either profile/basic or measurement/body.
    """
    candidates = []
    for src in (profile or {}, body or {}):
        if not isinstance(src, dict):
            continue
        # Common/expected keys
        candidates.append(("height_cm", _coerce_float(src.get("height_cm"))))
        candidates.append(("height_centimeter", _coerce_float(src.get("height_centimeter"))))
        candidates.append(("height_m", _coerce_float(src.get("height_m"))))
        candidates.append(("height_meter", _coerce_float(src.get("height_meter"))))
        candidates.append(("height_in", _coerce_float(src.get("height_in"))))
        candidates.append(("height_inch", _coerce_float(src.get("height_inch"))))

        # Nested payloads sometimes wrap values
        meas = src.get("measurements") if isinstance(src.get("measurements"), dict) else None
        if meas:
            candidates.append(("measurements.height_cm", _coerce_float(meas.get("height_cm"))))
            candidates.append(("measurements.height_m", _coerce_float(meas.get("height_m"))))
            candidates.append(("measurements.height_in", _coerce_float(meas.get("height_in"))))

    # Convert to cm (prefer cm > m > in)
    for key, val in candidates:
        if val is None:
            continue
        if "cm" in key or "centimeter" in key:
            return val
    for key, val in candidates:
        if val is None:
            continue
        if "meter" in key or key.endswith("_m"):
            return val * 100.0
    for key, val in candidates:
        if val is None:
            continue
        if "in" in key or "inch" in key:
            return val * 2.54
    return None


def _parse_whoop_weight_kg(profile: dict | None, body: dict | None) -> float | None:
    """Extract weight in kg from WHOOP body measurement payloads."""
    candidates = []
    for src in (body or {}, profile or {}):
        if not isinstance(src, dict):
            continue
        candidates.append(("weight_kg", _coerce_float(src.get("weight_kg"))))
        candidates.append(("weight_kilograms", _coerce_float(src.get("weight_kilograms"))))
        candidates.append(("weight_kilogram", _coerce_float(src.get("weight_kilogram"))))
        candidates.append(("weight_lbs", _coerce_float(src.get("weight_lbs"))))
        candidates.append(("weight_lb", _coerce_float(src.get("weight_lb"))))

        meas = src.get("measurements") if isinstance(src.get("measurements"), dict) else None
        if meas:
            candidates.append(("measurements.weight_kg", _coerce_float(meas.get("weight_kg"))))
            candidates.append(("measurements.weight_lbs", _coerce_float(meas.get("weight_lbs"))))

    for key, val in candidates:
        if val is None:
            continue
        if "kg" in key or "kilogram" in key:
            return val
    for key, val in candidates:
        if val is None:
            continue
        if "lb" in key:
            return val / 2.2046226218
    return None


def _whoop_local_date_from_iso(iso_ts: str | None, offset_min: int) -> date | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return (dt + timedelta(minutes=offset_min)).date()
    except Exception:
        return None


def _whoop_biometrics_weight_kg_missing(db, athlete_id: str, bio_date: date) -> bool:
    """True when there is no non-null biometrics.weight_kg for athlete_id + date."""
    try:
        res = (
            db.table("biometrics")
            .select("weight_kg")
            .eq("athlete_id", athlete_id)
            .eq("date", bio_date.isoformat())
            .maybe_single()
            .execute()
        )
        row = res.data if res else None
    except Exception:
        return True
    if not row:
        return True
    return _coerce_float(row.get("weight_kg")) is None


async def _whoop_sync_whoop_body_measurements(
    athlete_id: str,
    *,
    bio_date: date,
    access_token: str,
    refresh_token: str | None,
    external_user_id: str,
    db,
    sync_weight_kg: bool = True,
) -> None:
    """
    Fetch WHOOP body measurements and upsert biometrics.weight_kg (time series).
    Fills athletes.height_cm only when missing. Never writes athletes.weight_kg.
    Runs in the background so webhook latency stays low.
    """
    try:
        existing = (
            db.table("athletes")
            .select("height_cm")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        row = existing.data or {}
        have_height = _coerce_float(row.get("height_cm")) is not None

        token = access_token

        async def _refresh() -> str | None:
            if not refresh_token:
                return None
            token_data = await whoop.refresh_oauth_token(refresh_token)
            new_access = token_data.get("access_token")
            new_refresh = token_data.get("refresh_token") or refresh_token
            new_expires = token_expires_at(token_data)
            if new_access:
                update: dict = {"access_token": new_access, "refresh_token": new_refresh}
                if new_expires:
                    update["expires_at"] = new_expires
                db.table("oauth_tokens").update(update).eq("provider", "whoop").eq("external_user_id", str(external_user_id)).execute()
            return new_access

        try:
            profile = await whoop.fetch_profile(token)
            body = await whoop.fetch_body_measurement(token)
        except HTTPException as e:
            if e.status_code == status.HTTP_401_UNAUTHORIZED:
                new_access = await _refresh()
                if not new_access:
                    return
                token = new_access
                profile = await whoop.fetch_profile(token)
                body = await whoop.fetch_body_measurement(token)
            else:
                return

        height_cm = None if have_height else _parse_whoop_height_cm(profile, body)
        weight_kg = _parse_whoop_weight_kg(profile, body) if sync_weight_kg else None

        bio_update: dict = {"athlete_id": athlete_id, "date": bio_date.isoformat()}
        if sync_weight_kg and weight_kg is not None:
            bio_update["weight_kg"] = round(float(weight_kg), 2)
        if height_cm is not None and not have_height:
            bio_update["height_cm"] = round(float(height_cm), 1)
        if len(bio_update.keys()) > 2:
            db.table("biometrics").upsert(bio_update, on_conflict="athlete_id,date").execute()
            fields = [k for k in bio_update if k not in ("athlete_id", "date")]
            print(f"[whoop.body] biometrics athlete_id={athlete_id} date={bio_date.isoformat()} fields={fields}")

        if height_cm is not None and not have_height:
            db.table("athletes").update({"height_cm": round(float(height_cm), 1)}).eq("id", athlete_id).execute()
    except Exception as e:
        print(f"[whoop.body] sync failed athlete_id={athlete_id}: {repr(e)}")


def _apply_whoop_recovery_vitals(bio_payload: DailyBiometrics, recovery_data: dict) -> None:
    """Merge scored recovery vitals into an existing DailyBiometrics payload."""
    vitals = whoop.build_whoop_vitals_from_recovery(recovery_data)
    for field in ("hrv_rmssd", "resting_hr", "spo2_pct", "skin_temp", "recovery_score"):
        val = vitals.get(field)
        if val is not None:
            setattr(bio_payload, field, val)


def _whoop_wake_date(sleep_data: dict, offset_min: int) -> date:
    wake_dt = datetime.fromisoformat(sleep_data["end"].replace("Z", "+00:00"))
    local_wake = wake_dt + timedelta(minutes=offset_min)
    return local_wake.date()


async def _whoop_fetch_recovery_with_refresh(
    access_token: str,
    refresh_token: str | None,
    event_id: Any,
    refresh_fn,
    *,
    sleep_data: dict | None = None,
) -> dict | None:
    """Fetch recovery; refresh OAuth token on 401. Returns None on 404 or not yet scored."""
    token = access_token
    for attempt in range(2):
        try:
            if sleep_data is not None and not str(event_id).isdigit():
                return await whoop.fetch_recovery_for_sleep(token, event_id, sleep_data=sleep_data)
            return await whoop.fetch_recovery_for_event_id(token, event_id)
        except HTTPException as e:
            if e.status_code == status.HTTP_401_UNAUTHORIZED and attempt == 0:
                try:
                    new_access = await refresh_fn()
                except Exception as refresh_err:
                    print(f"[whoop.recovery] token refresh failed, skipping recovery merge: {refresh_err}")
                    return None
                if not new_access:
                    return None
                token = new_access
                continue
            if e.status_code == 404:
                return None
            raise
    return None


async def _whoop_retry_recovery_vitals(
    athlete_id: str,
    sleep_id: str,
    bio_date: date,
    access_token: str,
    refresh_token: str | None,
    external_user_id: str,
    db,
) -> None:
    """Delayed retries when recovery is not SCORED at sleep webhook time."""
    token = access_token

    async def _refresh() -> str | None:
        nonlocal token
        # Re-read current token from DB to avoid using a stale refresh token
        # (the main handler may have already rotated it before the retry fires).
        try:
            cur = (
                db.table("oauth_tokens")
                .select("access_token,refresh_token")
                .eq("provider", "whoop")
                .eq("external_user_id", str(external_user_id))
                .single()
                .execute()
            )
            cur_data = cur.data or {}
        except Exception:
            cur_data = {}
        cur_access = cur_data.get("access_token")
        cur_refresh = cur_data.get("refresh_token") or refresh_token
        if cur_access and cur_access != token:
            token = cur_access
            return cur_access
        token_data = await whoop.refresh_oauth_token(cur_refresh)
        new_access = token_data.get("access_token")
        new_refresh = token_data.get("refresh_token") or cur_refresh
        new_expires = token_expires_at(token_data)
        if new_access:
            update: dict = {"access_token": new_access, "refresh_token": new_refresh}
            if new_expires:
                update["expires_at"] = new_expires
            db.table("oauth_tokens").update(update).eq("provider", "whoop").eq("external_user_id", str(external_user_id)).execute()
            token = new_access
        return new_access

    for delay_sec in WHOOP_RECOVERY_RETRY_DELAYS_SEC:
        await asyncio.sleep(delay_sec)
        try:
            recovery_data = await whoop.fetch_recovery_for_sleep(token, sleep_id)
        except HTTPException as e:
            if e.status_code == status.HTTP_401_UNAUTHORIZED:
                if not await _refresh():
                    continue
                try:
                    recovery_data = await whoop.fetch_recovery_for_sleep(token, sleep_id)
                except HTTPException as retry_e:
                    if retry_e.status_code == 404:
                        recovery_data = None
                    else:
                        print(f"[whoop.recovery.retry] error athlete_id={athlete_id}: {retry_e}")
                        continue
            elif e.status_code == 404:
                recovery_data = None
            else:
                print(f"[whoop.recovery.retry] error athlete_id={athlete_id}: {e}")
                continue
        if not recovery_data:
            continue
        bio_payload = DailyBiometrics(date=bio_date, source="whoop")
        _apply_whoop_recovery_vitals(bio_payload, recovery_data)
        process_and_save_biometrics(bio_payload, athlete_id, db)
        print(
            f"[whoop.recovery.retry] success after {delay_sec}s "
            f"athlete_id={athlete_id} sleep_id={sleep_id}"
        )
        return

    print(
        f"[whoop.recovery.retry] exhausted retries athlete_id={athlete_id} sleep_id={sleep_id}"
    )


@router.post("/whoop/webhook")
async def whoop_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    """Webhook receiver for WHOOP data push events."""
    try:
        body = await request.body()
    except ClientDisconnect:
        return Response(status_code=200)

    signature = request.headers.get("X-WHOOP-Signature", "")
    timestamp = request.headers.get("X-WHOOP-Signature-Timestamp", "")
    if settings.WHOOP_WEBHOOK_SKIP_SIG_CHECK:
        if signature and timestamp:
            whoop.verify_webhook_signature(body, signature, timestamp)  # log mismatch but don't block
    elif (
        not signature
        or not timestamp
        or not whoop.verify_webhook_signature(body, signature, timestamp)
    ):
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
        print(f"[whoop.webhook] unknown user_id={user_id} — dropping")
        return Response(status_code=200)
        
    token_row = token_record.data[0]
    access_token = token_row.get("access_token")
    refresh_token = token_row.get("refresh_token")
    athlete_id = token_row.get("athlete_id")
    if athlete_id:
        invalidate_context_cache(athlete_id)  # bust 5-min coach context cache on any data event

    async def _refresh_and_persist_token() -> str | None:
        if not refresh_token:
            return None
        # Re-read from DB first: WHOOP sends sleep.updated + recovery.updated
        # simultaneously, so two handlers race to refresh the same token.
        # If the DB access_token has already changed, another handler won the
        # race — return the new token without attempting a second refresh.
        try:
            cur = (
                db.table("oauth_tokens")
                .select("access_token,refresh_token")
                .eq("provider", "whoop")
                .eq("external_user_id", str(user_id))
                .single()
                .execute()
            )
            cur_data = cur.data or {}
        except Exception:
            cur_data = {}
        if cur_data.get("access_token") and cur_data["access_token"] != access_token:
            return cur_data["access_token"]
        current_refresh = cur_data.get("refresh_token") or refresh_token
        token_data = await whoop.refresh_oauth_token(current_refresh)
        new_access = token_data.get("access_token")
        new_refresh = token_data.get("refresh_token") or current_refresh
        new_expires = token_expires_at(token_data)
        if new_access:
            update: dict = {"access_token": new_access, "refresh_token": new_refresh}
            if new_expires:
                update["expires_at"] = new_expires
            db.table("oauth_tokens").update(update).eq("provider", "whoop").eq("external_user_id", str(user_id)).execute()
        return new_access

    try:
        if event_type == "recovery.updated":
            if not event_id:
                return Response(status_code=200)
            athlete_res = db.table("athletes").select("timezone_offset_min").eq("id", athlete_id).single().execute()
            offset = (athlete_res.data.get("timezone_offset_min") or 0) if athlete_res.data else 0

            sleep_data_for_date: dict | None = None
            if not str(event_id).isdigit():
                try:
                    sleep_data_for_date = await whoop.fetch_sleep_data(access_token, event_id)
                except HTTPException as e:
                    if e.status_code == status.HTTP_401_UNAUTHORIZED:
                        new_access = await _refresh_and_persist_token()
                        if new_access:
                            sleep_data_for_date = await whoop.fetch_sleep_data(new_access, event_id)
                    elif e.status_code != 404:
                        raise

            recovery_data = await _whoop_fetch_recovery_with_refresh(
                access_token,
                refresh_token,
                event_id,
                _refresh_and_persist_token,
                sleep_data=sleep_data_for_date,
            )
            if not recovery_data:
                return Response(status_code=200)

            if sleep_data_for_date and sleep_data_for_date.get("end"):
                bio_date = _whoop_wake_date(sleep_data_for_date, offset)
            else:
                utc_created = datetime.fromisoformat(recovery_data["created_at"].replace("Z", "+00:00"))
                bio_date = (utc_created + timedelta(minutes=offset)).date()

            bio_payload = DailyBiometrics(date=bio_date, source="whoop")
            _apply_whoop_recovery_vitals(bio_payload, recovery_data)
            background_tasks.add_task(process_and_save_biometrics, bio_payload, athlete_id, db)
            if athlete_id and access_token and user_id is not None:
                background_tasks.add_task(
                    _whoop_sync_whoop_body_measurements,
                    athlete_id,
                    bio_date=bio_date,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    external_user_id=str(user_id),
                    db=db,
                )
            
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

            is_nap = bool(sleep_data.get("nap", False))
            recovery_merged = False
            if not is_nap:
                recovery_data = await _whoop_fetch_recovery_with_refresh(
                    access_token,
                    refresh_token,
                    event_id,
                    _refresh_and_persist_token,
                    sleep_data=sleep_data,
                )
                if recovery_data:
                    _apply_whoop_recovery_vitals(bio_payload, recovery_data)
                    recovery_merged = True
                else:
                    sleep_id = str(sleep_data.get("id") or event_id)
                    background_tasks.add_task(
                        _whoop_retry_recovery_vitals,
                        athlete_id,
                        sleep_id,
                        local_wake_dt.date(),
                        access_token,
                        refresh_token,
                        str(user_id),
                        db,
                    )

            background_tasks.add_task(process_and_save_biometrics, bio_payload, athlete_id, db)
            if athlete_id and access_token and user_id is not None:
                background_tasks.add_task(
                    _whoop_sync_whoop_body_measurements,
                    athlete_id,
                    bio_date=local_wake_dt.date(),
                    access_token=access_token,
                    refresh_token=refresh_token,
                    external_user_id=str(user_id),
                    db=db,
                )
            if not is_nap and not recovery_merged:
                print(
                    f"[whoop.sleep] recovery pending — scheduled retries "
                    f"athlete_id={athlete_id} sleep_id={sleep_data.get('id') or event_id}"
                )
            
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
            if athlete_id and access_token and user_id is not None:
                athlete_res = (
                    db.table("athletes")
                    .select("timezone_offset_min")
                    .eq("id", athlete_id)
                    .maybe_single()
                    .execute()
                )
                offset = (
                    (athlete_res.data.get("timezone_offset_min") or 0)
                    if athlete_res and athlete_res.data
                    else 0
                )
                bio_date = _whoop_local_date_from_iso(end, offset) or _whoop_local_date_from_iso(
                    start, offset
                )
                if bio_date and _whoop_biometrics_weight_kg_missing(db, athlete_id, bio_date):
                    background_tasks.add_task(
                        _whoop_sync_whoop_body_measurements,
                        athlete_id,
                        bio_date=bio_date,
                        access_token=access_token,
                        refresh_token=refresh_token,
                        external_user_id=str(user_id),
                        db=db,
                    )
            
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


async def _lookup_strava_owner_token(db, owner_strava_id: int):
    """Resolve athlete_id from Strava owner id; one retry on transient DB errors."""
    query = (
        db.table("oauth_tokens")
        .select("athlete_id")
        .eq("provider", "strava")
        .eq("external_user_id", str(owner_strava_id))
        .maybe_single()
    )
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            return query.execute()
        except Exception as e:
            last_err = e
            if attempt == 0:
                print(
                    f"[strava.webhook] oauth_tokens lookup failed strava_id={owner_strava_id} "
                    f"(retrying): {e}"
                )
                await asyncio.sleep(0.5)
    raise last_err  # type: ignore[misc]


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
        print("[strava.webhook] invalid JSON — dropping")
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
        print(
            f"[strava.webhook] missing owner_id — dropping payload keys={list(payload.keys())}"
        )
        return Response(status_code=200)

    try:
        owner_token = await _lookup_strava_owner_token(db, owner_strava_id)
    except Exception as e:
        print(
            f"[strava.webhook] oauth_tokens lookup failed strava_id={owner_strava_id}: {e}"
        )
        raise HTTPException(status_code=500, detail="Database lookup failed")

    if not owner_token.data:
        print(f"[strava.webhook] unknown owner strava_id={owner_strava_id} — dropping")
        return Response(status_code=200)

    athlete_id = owner_token.data["athlete_id"]

    # Strava sends ``create`` on first upload and ``update`` when metadata/streams change.
    # WHOOP often creates the canonical row first; Strava enrichment usually arrives as ``update``.
    if obj_type == "activity" and aspect in ("create", "update") and activity_id is not None:
        background_tasks.add_task(
            strava_service.ingest_strava_activity,
            owner_strava_id,
            activity_id,
            db,
            athlete_id=athlete_id,
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
    json_url: bool = Query(False, description="Return authorize URL as JSON (for SPA/native clients)"),
    athlete_id: str = Depends(get_current_athlete),
):
    """Step 1: Redirect authenticated user to WHOOP for authorization."""
    redirect_url = get_clean_redirect_url()
    state = _oauth_state(athlete_id, web_return)
    print(f"[whoop.oauth.authorize] redirect_uri={redirect_url} state={state}")
    auth_url = build_whoop_oauth_authorize_url(athlete_id, web_return)
    print(f"[whoop.oauth.authorize] auth_url={auth_url}")
    if json_url:
        return {"url": auth_url}
    return RedirectResponse(url=auth_url)

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

        # Fetch WHOOP user_id so webhook lookups can find this token record.
        whoop_user_id = None
        try:
            profile = await whoop.fetch_profile(access_token)
            whoop_user_id = profile.get("user_id")
            print(f"[whoop.oauth.callback] WHOOP user_id={whoop_user_id}")
        except Exception as e:
            print(f"[whoop.oauth.callback] Could not fetch WHOOP profile: {e}")

        # Save tokens first (lightweight)
        print(f"[whoop.oauth.callback] Saving tokens to DB for athlete {athlete_id}...")
        initial_expires = token_expires_at(token_data)
        _upsert: dict = {
            "athlete_id": athlete_id,
            "provider": "whoop",
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token"),
            "external_user_id": str(whoop_user_id) if whoop_user_id is not None else None,
        }
        if initial_expires:
            _upsert["expires_at"] = initial_expires
        db.table("oauth_tokens").upsert(_upsert).execute()
        print(f"[whoop.oauth.callback] Token persistence SUCCESS")

        # Everything else in background.
        # NOTE: FastAPI only injects BackgroundTasks reliably when it is an explicit dependency.
        # When this handler is called without an injected instance (e.g. mis-configured signature),
        # fall back to running the backfill asynchronously in-process so we still populate data.
        print(f"[whoop.oauth.callback] Scheduling background backfill task (90d)...")
        # Prefer FastAPI BackgroundTasks (keeps work tied to the request lifecycle on Cloud Run).
        if background_tasks is not None:
            background_tasks.add_task(backfill_historical_data, athlete_id, access_token, None, 90)
        else:
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
    json_url: bool = Query(False, description="Return authorize URL as JSON (for SPA/native clients)"),
    athlete_id: str = Depends(get_current_athlete),
):
    """Redirect authenticated user to Strava for authorization."""
    if not settings.STRAVA_CLIENT_ID or not settings.STRAVA_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Strava OAuth is not configured")
    auth_url = build_strava_oauth_authorize_url(athlete_id, web_return)
    if json_url:
        return {"url": auth_url}
    return RedirectResponse(url=auth_url)


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


@router.post("/intervals-icu/connect")
async def intervals_icu_connect(
    payload: IntervalsIcuConnectPayload,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    admin_db=Depends(get_admin_db),
):
    """Store Intervals.icu API credentials and queue an initial backfill."""
    intervals_athlete_id = _clean_intervals_athlete_id(payload.intervals_athlete_id)
    api_key = _clean_intervals_api_key(payload.api_key)

    await intervals_icu_service.verify_credentials(intervals_athlete_id, api_key)

    admin_db.table("oauth_tokens").upsert(
        {
            "athlete_id": athlete_id,
            "provider": intervals_icu_service.PROVIDER,
            "access_token": api_key,
            "refresh_token": None,
            "external_user_id": intervals_athlete_id,
        },
        on_conflict="athlete_id,provider",
    ).execute()

    _schedule_intervals_backfill(
        background_tasks,
        athlete_id,
        intervals_athlete_id,
        api_key,
        admin_db,
        payload.days,
    )
    return {
        "status": "success",
        "provider": intervals_icu_service.PROVIDER,
        "connected": True,
        "scheduled": True,
        "days": payload.days,
    }


@router.get("/status")
async def get_sync_status(athlete_id: str = Depends(get_current_athlete), db=Depends(get_user_db)):
    """Returns connection status for all integrations."""
    tokens = await asyncio.to_thread(
        db.table("oauth_tokens").select("provider").eq("athlete_id", athlete_id).execute
    )
    providers = [t["provider"] for t in tokens.data]
    
    return {
        "integrations": {
            "garmin": {"connected": "garmin" in providers, "last_sync": "2026-04-26T10:14:00Z"},
            "whoop": {"connected": "whoop" in providers, "last_sync": None},
            "strava": {"connected": "strava" in providers, "last_sync": None},
            "intervals_icu": {"connected": "intervals_icu" in providers, "last_sync": None},
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

    # Delete tokens owned by this athlete for the provider, then verify in parallel
    # whether any remain (helps clients update UI deterministically).
    await asyncio.to_thread(
        db.table("oauth_tokens").delete().eq("athlete_id", athlete_id).eq("provider", prov).execute
    )
    remaining = await asyncio.to_thread(
        db.table("oauth_tokens")
        .select("id")
        .eq("athlete_id", athlete_id)
        .eq("provider", prov)
        .execute
    )
    still_connected = bool(getattr(remaining, "data", None))

    return {
        "status": "success",
        "provider": prov,
        "connected": still_connected,
        "message": f"{prov.capitalize()} unlinked successfully" if not still_connected else f"{prov.capitalize()} unlink requested",
    }



@router.post("/refresh-strain")
async def refresh_strain_scores_now(
    athlete_id: str = Depends(get_current_athlete),
    admin_db=Depends(get_admin_db),
):
    """
    Recompute daily biometrics.strain_score from stored workout HR zones only.
    Fast (seconds). Prefer this over /reprocess-metrics when fixing strain display.
    """
    counts = await asyncio.to_thread(refresh_all_daily_strain_sync, admin_db, athlete_id)
    invalidate_context_cache(athlete_id)
    return {"status": "success", **counts}


@router.post("/reprocess-metrics")
async def reprocess_metrics_now(
    full: bool = Query(
        False,
        description="If true, rebuild all workouts + biometrics + PMC (slow; may timeout). "
        "Default false runs fast strain refresh only.",
    ),
    athlete_id: str = Depends(get_current_athlete),
    admin_db=Depends(get_admin_db),
):
    """
    Default (full=false): refresh daily biometrics.strain_score from workout zones — fast, safe from the app.

    full=true: rebuild workout TSS, all biometrics aggregates, and CTL/ATL/TSB. Use only from
    backend/scripts/reprocess_athlete_data.py for large histories (can exceed HTTP timeouts).
    """
    if not full:
        counts = await asyncio.to_thread(refresh_all_daily_strain_sync, admin_db, athlete_id)
        invalidate_context_cache(athlete_id)
        return {"status": "success", "mode": "strain_refresh", **counts}

    try:
        counts = await reprocess_athlete_metrics(athlete_id, admin_db)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Full reprocess failed. Run: python backend/scripts/reprocess_athlete_data.py <athlete_id> "
                f"Error: {e}"
            ),
        ) from e
    invalidate_context_cache(athlete_id)
    return {"status": "success", "mode": "full", **counts}


@router.post("/whoop/backfill-biometrics")
async def whoop_backfill_biometrics_now(
    days: int = 90,
    athlete_id: str = Depends(get_current_athlete),
    admin_db=Depends(get_admin_db),
):
    """
    Backfill WHOOP sleep + recovery only (fast). Use when workouts exist but biometrics is empty.
    """
    d = max(1, min(int(days), 365))
    tok = (
        admin_db.table("oauth_tokens")
        .select("access_token, refresh_token")
        .eq("athlete_id", athlete_id)
        .eq("provider", "whoop")
        .maybe_single()
        .execute()
    )
    row = tok.data if tok else None
    access_token = (row or {}).get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="WHOOP not connected")

    asyncio.create_task(backfill_biometrics_only(athlete_id, access_token, admin_db, d))
    return {"status": "success", "scheduled": True, "days": d, "mode": "biometrics_only"}


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
        .select("access_token, refresh_token")
        .eq("athlete_id", athlete_id)
        .eq("provider", "whoop")
        .maybe_single()
        .execute()
    )
    row = tok.data if tok else None
    access_token = (row or {}).get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="WHOOP not connected")

    asyncio.create_task(backfill_historical_data(athlete_id, access_token, admin_db, d))
    return {"status": "success", "scheduled": True, "days": d}


@router.post("/strava/backfill")
async def strava_backfill_now(
    days: int = 90,
    athlete_id: str = Depends(get_current_athlete),
    admin_db=Depends(get_admin_db),
):
    """
    Manually trigger a Strava backfill for the authenticated athlete.
    Useful for local/dev recovery or to re-sync after an extended gap.
    Automatically refreshes an expired access token before starting.
    """
    d = max(1, min(int(days), 365))

    # get_valid_token refreshes and persists if expired.
    access_token = await strava_service.get_valid_token(athlete_id, admin_db)
    if not access_token:
        raise HTTPException(status_code=400, detail="Strava not connected")

    tok = (
        admin_db.table("oauth_tokens")
        .select("external_user_id")
        .eq("athlete_id", athlete_id)
        .eq("provider", "strava")
        .maybe_single()
        .execute()
    )
    strava_athlete_id = (tok.data or {}).get("external_user_id") if tok else None
    if not strava_athlete_id:
        raise HTTPException(status_code=400, detail="Strava athlete ID not found — try re-linking Strava")

    try:
        owner_strava_id = int(strava_athlete_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid Strava athlete ID: {strava_athlete_id}")

    asyncio.create_task(strava_backfill(athlete_id, owner_strava_id, access_token, admin_db, d))
    return {"status": "success", "scheduled": True, "days": d}


@router.post("/intervals-icu/backfill")
async def intervals_icu_backfill_now(
    days: int = 90,
    athlete_id: str = Depends(get_current_athlete),
    admin_db=Depends(get_admin_db),
):
    """Manually trigger an Intervals.icu biometrics and workouts backfill."""
    d = max(1, min(int(days), 365))
    tok = (
        admin_db.table("oauth_tokens")
        .select("access_token, external_user_id")
        .eq("athlete_id", athlete_id)
        .eq("provider", intervals_icu_service.PROVIDER)
        .maybe_single()
        .execute()
    )
    row = tok.data if tok else None
    api_key = (row or {}).get("access_token")
    intervals_athlete_id = (row or {}).get("external_user_id")
    if not api_key or not intervals_athlete_id:
        raise HTTPException(status_code=400, detail="Intervals.icu not connected")

    asyncio.create_task(
        intervals_icu_service.backfill_historical_data(
            athlete_id,
            str(intervals_athlete_id),
            str(api_key),
            admin_db,
            d,
        )
    )
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
