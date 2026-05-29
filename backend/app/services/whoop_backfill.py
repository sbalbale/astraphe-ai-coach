from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timedelta, timezone, date as date_type
from typing import Any, Optional

from fastapi import HTTPException, status

from app.services import whoop
from app.models.biometrics import DailyBiometrics
from app.models.workout import WorkoutPayload
from app.services.ai_coach import invalidate_context_cache
from app.services.processing import process_and_save_biometrics, process_and_save_workout, recalculate_tss_history
from app.dependencies import get_admin_db
from app.services.token_refresh import token_expires_at


def _parse_dt(value: str) -> datetime:
    # WHOOP uses RFC3339 with Z.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _pct(part_ms: Optional[float], total_ms: Optional[float]) -> Optional[float]:
    if not part_ms or not total_ms:
        return None
    if total_ms <= 0:
        return None
    return round((part_ms / total_ms) * 100.0, 1)


def _load_whoop_tokens(db: Any, athlete_id: str) -> tuple[str | None, str | None]:
    res = (
        db.table("oauth_tokens")
        .select("access_token, refresh_token")
        .eq("athlete_id", athlete_id)
        .eq("provider", "whoop")
        .maybe_single()
        .execute()
    )
    row = res.data if res else None
    if not row:
        return None, None
    return row.get("access_token"), row.get("refresh_token")


async def _ensure_valid_whoop_access_token(
    athlete_id: str,
    access_token: str,
    refresh_token: str | None,
    db: Any,
) -> str:
    """
    Return a working WHOOP access token. Refresh and persist when the stored token expired.
    """
    try:
        await whoop.fetch_profile(access_token)
        return access_token
    except HTTPException as e:
        if e.status_code != status.HTTP_401_UNAUTHORIZED:
            raise

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="WHOOP access token expired; reconnect WHOOP in profile settings",
        )

    token_data = await whoop.refresh_oauth_token(refresh_token)
    new_access = token_data.get("access_token")
    new_refresh = token_data.get("refresh_token") or refresh_token
    if not new_access:
        raise HTTPException(
            status_code=502,
            detail="WHOOP token refresh returned no access_token",
        )

    new_expires = token_expires_at(token_data)
    bf_update: dict = {"access_token": new_access, "refresh_token": new_refresh}
    if new_expires:
        bf_update["expires_at"] = new_expires
    db.table("oauth_tokens").update(bf_update).eq("athlete_id", athlete_id).eq("provider", "whoop").execute()
    print(f"[whoop.backfill] refreshed access token athlete_id={athlete_id}")
    return new_access


async def backfill_historical_data(
    athlete_id: str,
    access_token: str,
    db: Any = None,
    days: int = 90,
    *,
    hours: int | None = None,
    include_workouts: bool = True,
) -> None:
    """
    Pull historical WHOOP sleep/recovery/workouts and persist into Supabase.
    This is intended to run right after OAuth connect.

    When ``hours`` is set it takes precedence over ``days`` (startup self-heal window).
    """
    try:
        await _backfill_historical_data_impl(
            athlete_id,
            access_token,
            db,
            days,
            hours=hours,
            include_workouts=include_workouts,
        )
    except Exception as e:
        print(f"[whoop.backfill] FAILED athlete_id={athlete_id}: {e!r}\n{traceback.format_exc()}")


async def backfill_biometrics_only(
    athlete_id: str, access_token: str, db: Any = None, days: int = 90
) -> None:
    """Fast path: sleep + recovery only (fills empty biometrics table)."""
    await backfill_historical_data(
        athlete_id, access_token, db, days, include_workouts=False
    )


async def _backfill_historical_data_impl(
    athlete_id: str,
    access_token: str,
    db: Any = None,
    days: int = 90,
    *,
    hours: int | None = None,
    include_workouts: bool = True,
) -> None:
    # If no DB provided (common for background tasks), create one.
    if db is None:
        db = get_admin_db()

    stored_access, refresh_token = _load_whoop_tokens(db, athlete_id)
    if stored_access:
        access_token = stored_access

    access_token = await _ensure_valid_whoop_access_token(
        athlete_id, access_token, refresh_token, db
    )

    # 0) Fetch Profile & Update Athlete (moved from sync.py for speed)
    print(f"[whoop.backfill] Fetching profile for athlete_id={athlete_id}")
    try:
        profile = await whoop.fetch_profile(access_token)
        measurements = await whoop.fetch_body_measurement(access_token)

        # Parse weight — WHOOP v2 returns weight_kilograms
        raw_weight = measurements.get("weight_kilograms") or measurements.get("weight_kg")
        weight_kg = round(float(raw_weight), 2) if raw_weight else None

        # Parse height — WHOOP v2 returns height_meters; convert to cm
        raw_height_cm = measurements.get("height_cm")
        raw_height_m = (measurements.get("height_meters")
                        or measurements.get("height_meter")
                        or measurements.get("height_m"))
        height_cm = (round(float(raw_height_cm), 1) if raw_height_cm
                     else round(float(raw_height_m) * 100.0, 1) if raw_height_m
                     else None)

        profile_update = {}
        if profile.get("first_name"):
            profile_update["display_name"] = profile["first_name"]
        if height_cm is not None:
            profile_update["height_cm"] = height_cm
        if measurements.get("max_heart_rate"):
            profile_update["max_hr"] = measurements["max_heart_rate"]

        # Also update the oauth_token with the external_user_id
        if profile.get("user_id"):
            db.table("oauth_tokens").update({
                "external_user_id": str(profile.get("user_id"))
            }).eq("athlete_id", athlete_id).eq("provider", "whoop").execute()

        if profile_update:
            db.table("athletes").update(profile_update).eq("id", athlete_id).execute()

        # Upsert weight/height into today's biometrics row
        today = datetime.now(timezone.utc).date()
        bio_update: dict = {"athlete_id": athlete_id, "date": today.isoformat()}
        if weight_kg is not None:
            bio_update["weight_kg"] = weight_kg
        if height_cm is not None:
            bio_update["height_cm"] = height_cm
        if len(bio_update) > 2:
            db.table("biometrics").upsert(bio_update, on_conflict="athlete_id,date").execute()
            print(f"[whoop.backfill] wrote body metrics to biometrics date={today.isoformat()} fields={[k for k in bio_update if k not in ('athlete_id','date')]}")
    except Exception as e:
        print(f"[whoop.backfill] Failed to update profile/measurements: {e}")

    end = datetime.now(timezone.utc)
    if hours is not None:
        start = end - timedelta(hours=hours)
    else:
        start = end - timedelta(days=days)
    start_s = start.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    end_s = end.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    print(f"[whoop.backfill] start={start_s} end={end_s} athlete_id={athlete_id}")

    # Fetch athlete timezone for correct date mapping
    try:
        athlete_res = (
            db.table("athletes")
            .select("timezone_offset_min")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        offset = (athlete_res.data.get("timezone_offset_min") or 0) if (athlete_res and athlete_res.data) else 0
    except Exception:
        offset = 0

    # Biometrics first (sleep + recovery) so the dashboard has HRV/sleep even if the
    # workout loop is slow or the Cloud Run instance times out later.
    sleeps = await whoop.fetch_collection(access_token, "activity/sleep", start_s, end_s)
    print(f"[whoop.backfill] sleeps={len(sleeps)}")

    cycle_wake_dates: dict[Any, date_type] = {}
    sleeps_saved = 0
    sleeps_skipped = 0

    for slp in sleeps:
        start_time = slp.get("start")
        if not start_time:
            sleeps_skipped += 1
            continue

        score_state = slp.get("score_state")
        if score_state and score_state != "SCORED":
            sleeps_skipped += 1
            continue

        score = (slp.get("score") or {}) if isinstance(slp.get("score"), dict) else {}
        stage = (score.get("stage_summary") or {}) if isinstance(score.get("stage_summary"), dict) else {}

        light = stage.get("total_light_sleep_time_milli")
        deep = stage.get("total_slow_wave_sleep_time_milli")
        rem = stage.get("total_rem_sleep_time_milli")
        awake = stage.get("total_awake_time_milli")

        total_sleep_ms = sum(v for v in (light, deep, rem) if isinstance(v, (int, float)))
        if not total_sleep_ms or total_sleep_ms <= 0:
            sleeps_skipped += 1
            continue

        wake_dt = _parse_dt(slp.get("end") or start_time)
        local_wake = wake_dt + timedelta(minutes=offset)
        d = local_wake.date()
        cycle_id = slp.get("cycle_id")
        if cycle_id is not None and not slp.get("nap"):
            cycle_wake_dates[cycle_id] = d
        external_id = str(slp.get("id"))

        payload = DailyBiometrics(
            date=d,
            source="whoop",
            external_id=external_id,
            hrv_rmssd=None,
            resting_hr=None,
            sleep_duration_min=int(total_sleep_ms / 60000),
            sleep_score=score.get("sleep_performance_percentage"),
            sleep_deep_pct=_pct(deep, total_sleep_ms),
            sleep_rem_pct=_pct(rem, total_sleep_ms),
            sleep_light_pct=_pct(light, total_sleep_ms),
            sleep_awake_pct=round((awake / (total_sleep_ms + awake)) * 100, 1) if (total_sleep_ms and awake) else 0.0,
            sleep_bedtime=datetime.fromisoformat(start_time.replace("Z", "+00:00")),
            sleep_wakeup=datetime.fromisoformat((slp.get("end") or start_time).replace("Z", "+00:00")),
            is_nap=slp.get("nap", False),
            sleep_need_min=None,
            sleep_debt_min=None,
            skin_temp=None,
            spo2_pct=None,
        )
        try:
            await asyncio.to_thread(
                process_and_save_biometrics, payload, athlete_id, db, skip_pmc_recalc=True
            )
            sleeps_saved += 1
        except Exception as e:
            print(
                f"[whoop.backfill] sleep_upsert_failed date={d} external_id={external_id}: {e}\n"
                f"{traceback.format_exc()}"
            )

    recoveries = await whoop.fetch_collection(access_token, "recovery", start_s, end_s)
    print(f"[whoop.backfill] recoveries={len(recoveries)}")

    recoveries_saved = 0
    recoveries_skipped = 0

    for rec in recoveries:
        score = (rec.get("score") or {}) if isinstance(rec.get("score"), dict) else {}
        if not whoop.recovery_is_scored(rec):
            recoveries_skipped += 1
            continue

        cycle_id = rec.get("cycle_id")
        d = cycle_wake_dates.get(cycle_id)
        if d is None:
            created_at = rec.get("created_at")
            if not created_at:
                recoveries_skipped += 1
                continue
            utc_created = _parse_dt(created_at)
            d = (utc_created + timedelta(minutes=offset)).date()

        payload = DailyBiometrics(
            date=d,
            source="whoop",
            hrv_rmssd=score.get("hrv_rmssd_milli") or score.get("hrv_rmssd_ms"),
            resting_hr=score.get("resting_heart_rate"),
            sleep_duration_min=None,
            sleep_score=None,
            sleep_deep_pct=None,
            sleep_rem_pct=None,
            sleep_need_min=None,
            sleep_debt_min=None,
            skin_temp=score.get("skin_temp_celsius"),
            spo2_pct=score.get("spo2_percentage"),
            recovery_score=score.get("recovery_score"),
        )
        try:
            await asyncio.to_thread(
                process_and_save_biometrics, payload, athlete_id, db, skip_pmc_recalc=True
            )
            recoveries_saved += 1
        except Exception as e:
            print(
                f"[whoop.backfill] recovery_upsert_failed date={d}: {e}\n"
                f"{traceback.format_exc()}"
            )

    bio_count_res = (
        db.table("biometrics")
        .select("id", count="exact")
        .eq("athlete_id", athlete_id)
        .execute()
    )
    bio_rows = bio_count_res.count if bio_count_res else 0
    print(
        f"[whoop.backfill] biometrics sleeps_saved={sleeps_saved} sleeps_skipped={sleeps_skipped} "
        f"recoveries_saved={recoveries_saved} recoveries_skipped={recoveries_skipped} "
        f"biometrics_rows={bio_rows}"
    )

    if include_workouts:
        workouts = await whoop.fetch_collection(access_token, "activity/workout", start_s, end_s)
        print(f"[whoop.backfill] workouts={len(workouts)}")
    else:
        workouts = []
        print("[whoop.backfill] skipping workout ingest (biometrics-only mode)")

    for idx, w in enumerate(workouts, start=1):
        w_start = w.get("start")
        w_end = w.get("end")
        if not w_start or not w_end:
            continue

        start_dt = _parse_dt(w_start)
        end_dt = _parse_dt(w_end)
        duration_seconds = int(max(0, (end_dt - start_dt).total_seconds()))

        score = (w.get("score") or {}) if isinstance(w.get("score"), dict) else {}
        zone = score.get("zone_durations") if isinstance(score.get("zone_durations"), dict) else {}
        z1_pct, z2_pct, z3_pct, z4_pct, z5_pct = whoop.hr_zone_pct_from_whoop_zone_millis(zone)

        external_id = str(w.get("v1_id") or w.get("id"))
        display_name = (w.get("sport_name") or "Workout")
        sport_name_raw = (w.get("sport_name") or "other")
        sport_name = str(sport_name_raw).strip().lower()
        # Normalize common WHOOP sport names into our internal enums.
        if sport_name in ("weightlifting", "weight lifting", "strength training", "strength_training", "gym", "strength"):
            sport_name = "strength"
        elif sport_name in ("cycling", "bike", "biking", "indoor cycling", "spin", "spinning", "stationary bike", "peloton"):
            # processing.py will normalize cycling -> bike
            sport_name = "cycling"
        elif sport_name in ("running", "run", "treadmill run", "treadmill"):
            sport_name = "run"
        elif sport_name in ("rowing", "row", "rower", "erg", "ergometer"):
            sport_name = "row"
        elif sport_name in (
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
            sport_name = "mobility"

        payload = WorkoutPayload(
            source="whoop",
            external_id=external_id,
            sport=sport_name,
            title=display_name,
            started_at=start_dt,
            ended_at=end_dt,
            duration_seconds=duration_seconds,
            distance_m=score.get("distance_meter"),
            avg_hr=score.get("average_heart_rate"),
            max_hr=score.get("max_heart_rate"),
            hr_zone_0_pct=None,
            hr_zone_1_pct=z1_pct,
            hr_zone_2_pct=z2_pct,
            hr_zone_3_pct=z3_pct,
            hr_zone_4_pct=z4_pct,
            hr_zone_5_pct=z5_pct,
        )
        try:
            await process_and_save_workout(payload, athlete_id, db, skip_tss_recalc=True)
        except Exception as e:
            # Don't let a single bad record kill the whole backfill.
            print(f"[whoop.backfill] workout_upsert_failed external_id={external_id} sport={sport_name}: {e}")
            continue
        if idx % 25 == 0 or idx == len(workouts):
            print(f"[whoop.backfill] workouts progress {idx}/{len(workouts)}")

    recalculate_tss_history(athlete_id, db)

    # Refresh readiness scores now that PMC exists (skipped per-row during batch ingest).
    if bio_rows and bio_rows > 0:
        dates_res = (
            db.table("biometrics")
            .select("date,hrv_rmssd,resting_hr,recovery_score,sleep_score")
            .eq("athlete_id", athlete_id)
            .gte("date", start.date().isoformat())
            .order("date")
            .execute()
        )
        for row in dates_res.data or []:
            try:
                d_raw = row.get("date")
                if not d_raw:
                    continue
                refresh = DailyBiometrics(
                    date=date_type.fromisoformat(str(d_raw)[:10]),
                    source="whoop",
                    hrv_rmssd=float(row["hrv_rmssd"]) if row.get("hrv_rmssd") is not None else None,
                    resting_hr=row.get("resting_hr"),
                    recovery_score=row.get("recovery_score"),
                    sleep_score=row.get("sleep_score"),
                )
                await asyncio.to_thread(
                    process_and_save_biometrics, refresh, athlete_id, db, skip_pmc_recalc=True
                )
            except Exception as e:
                print(f"[whoop.backfill] readiness_refresh_failed date={row.get('date')}: {e}")

    invalidate_context_cache(athlete_id)
    print(f"[whoop.backfill] complete athlete_id={athlete_id}")


async def backfill_recent(hours: int = 24) -> None:
    """Self-heal missed WHOOP webhooks after deploy/restart for all connected athletes."""
    db = get_admin_db()
    try:
        res = (
            db.table("oauth_tokens")
            .select("athlete_id, access_token")
            .eq("provider", "whoop")
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        print(f"[whoop.startup_backfill] failed to list WHOOP tokens: {e}")
        return

    print(f"[whoop.startup_backfill] starting hours={hours} athletes={len(rows)}")
    processed = 0
    for row in rows:
        athlete_id = row.get("athlete_id")
        access_token = row.get("access_token")
        if not athlete_id:
            continue
        if not access_token:
            print(f"[whoop.startup_backfill] skip athlete_id={athlete_id} (no access_token)")
            continue
        try:
            await backfill_historical_data(
                athlete_id, access_token, db, hours=hours, include_workouts=True
            )
            processed += 1
        except Exception as e:
            print(f"[whoop.startup_backfill] failed athlete_id={athlete_id}: {e!r}")

    print(
        f"[whoop.startup_backfill] complete hours={hours} "
        f"athletes={len(rows)} processed={processed}"
    )
