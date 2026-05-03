from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.dependencies import get_current_athlete, get_current_user_tier, get_user_db
from app.services.analysis_cache import (
    fingerprint_context,
    generate_gemini_analysis,
    get_cached_analysis,
    upsert_analysis,
)
from app.services.ai_model import resolve_gemini_model_for_athlete


router = APIRouter(prefix="/v1/analysis", tags=["Analysis"])


def _parse_day(day: Optional[str]) -> date:
    if not day:
        return date.today()
    return date.fromisoformat(str(day)[:10])


def _baseline_30d(rows: list[dict], field: str) -> Optional[float]:
    vals: list[float] = []
    for r in rows:
        v = r.get(field)
        try:
            if v is None:
                continue
            fv = float(v)
            if fv == 0:
                continue
            vals.append(fv)
        except Exception:
            continue
    if not vals:
        return None
    return sum(vals) / len(vals)


def _load_biometrics_context(db: Client, athlete_id: str, day: date) -> Dict[str, Any]:
    day_str = day.isoformat()
    prev_day_str = (day - timedelta(days=1)).isoformat()

    b_res = (
        db.table("biometrics")
        .select(
            "date,hrv_rmssd,resting_hr,sleep_duration_min,sleep_score,sleep_deep_pct,sleep_rem_pct,sleep_light_pct,sleep_awake_pct,"
            "sleep_bedtime,sleep_wakeup,spo2_pct,skin_temp_deviation,recovery_score,strain_score,sleep_need_min,sleep_debt_min"
        )
        .eq("athlete_id", athlete_id)
        .eq("date", day_str)
        .maybe_single()
        .execute()
    )
    b = b_res.data if b_res else None

    # Prior 30 days baseline window (exclude selected day).
    base_start = (day - timedelta(days=30)).isoformat()
    base_end = (day - timedelta(days=1)).isoformat()
    base_rows_res = (
        db.table("biometrics")
        .select("date,hrv_rmssd,resting_hr,sleep_score,spo2_pct,skin_temp_deviation")
        .eq("athlete_id", athlete_id)
        .gte("date", base_start)
        .lte("date", base_end)
        .order("date")
        .execute()
    )
    base_rows = (base_rows_res.data if base_rows_res else None) or []

    prior_load_res = (
        db.table("tss_history")
        .select("date,daily_tss,atl,ctl,tsb")
        .eq("athlete_id", athlete_id)
        .eq("date", prev_day_str)
        .maybe_single()
        .execute()
    )
    prior_load = prior_load_res.data if prior_load_res else None

    return {
        "day": day_str,
        "biometrics": b or {"available": False},
        "baselines_30d": {
            "hrv_rmssd": _baseline_30d(base_rows, "hrv_rmssd"),
            "resting_hr": _baseline_30d(base_rows, "resting_hr"),
            "sleep_score": _baseline_30d(base_rows, "sleep_score"),
            "spo2_pct": _baseline_30d(base_rows, "spo2_pct"),
            "skin_temp_deviation": _baseline_30d(base_rows, "skin_temp_deviation"),
        },
        "prior_day_load": prior_load or {"available": False},
    }


def _load_strain_context(db: Client, athlete_id: str, day: date) -> Dict[str, Any]:
    day_str = day.isoformat()

    bio_res = (
        db.table("biometrics")
        .select("date,strain_score,recovery_score,sleep_score,hrv_rmssd,resting_hr")
        .eq("athlete_id", athlete_id)
        .eq("date", day_str)
        .maybe_single()
        .execute()
    )
    bio = bio_res.data if bio_res else None

    pmc_res = (
        db.table("tss_history")
        .select("date,ctl,atl,tsb,daily_tss")
        .eq("athlete_id", athlete_id)
        .eq("date", day_str)
        .maybe_single()
        .execute()
    )
    pmc = pmc_res.data if pmc_res else None

    return {
        "day": day_str,
        "biometrics": bio or {"available": False},
        "pmc": pmc or {"available": False},
    }


def _load_training_load_context(db: Client, athlete_id: str, end_day: date) -> Dict[str, Any]:
    end_str = end_day.isoformat()
    start = end_day - timedelta(days=6)
    start_str = start.isoformat()

    rows_res = (
        db.table("tss_history")
        .select("date,daily_tss,ctl,atl,tsb")
        .eq("athlete_id", athlete_id)
        .gte("date", start_str)
        .lte("date", end_str)
        .order("date")
        .execute()
    )
    rows = (rows_res.data if rows_res else None) or []

    weekly_tss = 0.0
    for r in rows:
        try:
            weekly_tss += float(r.get("daily_tss") or 0.0)
        except Exception:
            pass

    first = rows[0] if rows else {}
    last = rows[-1] if rows else {}

    def _f(v: Any) -> Optional[float]:
        try:
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    trend = {
        "ctl_delta_7d": None if not rows else (_f(last.get("ctl")) - _f(first.get("ctl")) if _f(last.get("ctl")) is not None and _f(first.get("ctl")) is not None else None),
        "atl_delta_7d": None if not rows else (_f(last.get("atl")) - _f(first.get("atl")) if _f(last.get("atl")) is not None and _f(first.get("atl")) is not None else None),
        "tsb_delta_7d": None if not rows else (_f(last.get("tsb")) - _f(first.get("tsb")) if _f(last.get("tsb")) is not None and _f(first.get("tsb")) is not None else None),
    }

    return {
        "end_day": end_str,
        "window_start": start_str,
        "weekly_tss": round(float(weekly_tss), 2),
        "current": {
            "date": last.get("date"),
            "ctl": _f(last.get("ctl")),
            "atl": _f(last.get("atl")),
            "tsb": _f(last.get("tsb")),
        },
        "trend": trend,
        "series": rows[-7:],
    }


def _prompt(analysis_type: str, context: Dict[str, Any]) -> str:
    # Tight output rules: 1–2 sentences, no lists, cite at least one metric from context.
    # We embed JSON so the model can quote exact numbers.
    return (
        "You are ASTRAPE, a clinical performance analyst.\n"
        "Task: Write a concise 1–2 sentence analysis for the athlete.\n"
        "Rules:\n"
        "- Output 1–2 sentences only. No bullets, no headings, no emojis.\n"
        "- Mention at least one specific metric value from the JSON (e.g., HRV, RHR, sleep score, CTL/ATL/TSB, TSS).\n"
        "- If data is missing, say what is missing in one sentence.\n\n"
        f"AnalysisType: {analysis_type}\n"
        f"ContextJSON: {context}\n"
    )


def _get_or_compute(
    db: Client,
    athlete_id: str,
    tier: str,
    analysis_type: str,
    scope_key: str,
    context: Dict[str, Any],
    model_name: str,
) -> Dict[str, Any]:
    fp = fingerprint_context(context)
    cached = get_cached_analysis(db, athlete_id, analysis_type, scope_key)
    if cached and cached.get("fingerprint") == fp and cached.get("content"):
        return {"content": cached.get("content"), "fingerprint": fp, "cached": True}

    # Only trial/premium get Gemini-generated narrative analysis.
    if tier not in ("trial", "premium"):
        return {
            "content": "",
            "fingerprint": fp,
            "cached": False,
            "note": "tier_not_eligible",
        }

    text, used_model = generate_gemini_analysis(_prompt(analysis_type, context), model_name=model_name)
    if text:
        upsert_analysis(
            db=db,
            athlete_id=athlete_id,
            analysis_type=analysis_type,
            scope_key=scope_key,
            fingerprint=fp,
            content=text,
            model=used_model,
        )
    return {"content": text, "fingerprint": fp, "cached": False, "model": used_model}


@router.get("/recovery")
async def recovery_analysis(
    day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    db: Client = Depends(get_user_db),
):
    d = _parse_day(day)
    ctx = _load_biometrics_context(db, athlete_id, d)
    model_name = resolve_gemini_model_for_athlete(db, athlete_id)
    return {"status": "success", "analysis": _get_or_compute(db, athlete_id, tier, "recovery", d.isoformat(), ctx, model_name=model_name)}


@router.get("/sleep")
async def sleep_analysis(
    day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    db: Client = Depends(get_user_db),
):
    d = _parse_day(day)
    ctx = _load_biometrics_context(db, athlete_id, d)
    model_name = resolve_gemini_model_for_athlete(db, athlete_id)
    return {"status": "success", "analysis": _get_or_compute(db, athlete_id, tier, "sleep", d.isoformat(), ctx, model_name=model_name)}


@router.get("/strain")
async def strain_analysis(
    day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    db: Client = Depends(get_user_db),
):
    d = _parse_day(day)
    ctx = _load_strain_context(db, athlete_id, d)
    model_name = resolve_gemini_model_for_athlete(db, athlete_id)
    return {"status": "success", "analysis": _get_or_compute(db, athlete_id, tier, "strain", d.isoformat(), ctx, model_name=model_name)}


@router.get("/training-load")
async def training_load_analysis(
    end_day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    db: Client = Depends(get_user_db),
):
    d = _parse_day(end_day)
    ctx = _load_training_load_context(db, athlete_id, d)
    model_name = resolve_gemini_model_for_athlete(db, athlete_id)
    return {"status": "success", "analysis": _get_or_compute(db, athlete_id, tier, "training_load", d.isoformat(), ctx, model_name=model_name)}

