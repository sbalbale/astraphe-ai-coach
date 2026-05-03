from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

import numpy as np
from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.dependencies import get_current_athlete, get_current_gemini_model, get_current_user_tier, get_user_db
from app.services.algorithms import compute_z_score
from app.services.analysis_cache import (
    fingerprint_context,
    generate_gemini_analysis,
    get_cached_analysis,
    upsert_analysis,
)


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


def _zscore_for(rows: list[dict], field: str, latest: Optional[float], span: int = 7) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute (z, baseline, sd) over `rows` history for `latest`. Returns Nones if no history."""
    if latest is None or not rows:
        return None, None, None
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
        return None, None, None
    arr = np.array(vals, dtype=float)
    z, mean, sd = compute_z_score(float(latest), arr, span=span)
    return float(z), float(mean), float(sd)


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

    # 7-day EWMA z-scores for HRV/RHR (baseline excludes today, since base_rows is
    # the prior 30-day window). These are also surfaced to the LLM context so
    # narrative analyses can mention z-score deviations explicitly.
    today_hrv = (b or {}).get("hrv_rmssd") if b else None
    today_rhr = (b or {}).get("resting_hr") if b else None
    hrv_z, hrv_base_7d, hrv_sd_7d = _zscore_for(base_rows, "hrv_rmssd", float(today_hrv) if today_hrv is not None else None)
    rhr_z, rhr_base_7d, rhr_sd_7d = _zscore_for(base_rows, "resting_hr", float(today_rhr) if today_rhr is not None else None)

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
        "ewma_7d": {
            "hrv_baseline_7d": hrv_base_7d,
            "hrv_sd_7d": hrv_sd_7d,
            "hrv_z": hrv_z,
            "rhr_baseline_7d": rhr_base_7d,
            "rhr_sd_7d": rhr_sd_7d,
            "rhr_z": rhr_z,
        },
        "sleep_debt_min": (b or {}).get("sleep_debt_min") if b else None,
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


def _load_dashboard_context(db: Client, athlete_id: str, day: date) -> Dict[str, Any]:
    """
    Dashboard needs a blended snapshot of today's core metrics:
    readiness/recovery + sleep + HRV/RHR + training load (CTL/ATL/TSB, weekly TSS).
    """
    biom = _load_biometrics_context(db, athlete_id, day)
    load = _load_training_load_context(db, athlete_id, day)
    # Keep the payload compact and explicit for the LLM.
    return {
        "day": day.isoformat(),
        "biometrics": biom,
        "training_load": load,
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


def _n(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _fallback_content(analysis_type: str, context: Dict[str, Any]) -> str:
    """
    Deterministic backup copy so insights render consistently even when the user
    isn't eligible for Gemini (tier gating) or when the model returns empty.
    Must be 1–2 sentences, no lists.
    """
    ctx = context or {}

    if analysis_type == "dashboard_summary":
        biom_block = (ctx.get("biometrics") or {}) if isinstance(ctx, dict) else {}
        load_block = (ctx.get("training_load") or {}) if isinstance(ctx, dict) else {}

        b = (biom_block.get("biometrics") or {}) if isinstance(biom_block, dict) else {}
        bases = (biom_block.get("baselines_30d") or {}) if isinstance(biom_block, dict) else {}
        cur = (load_block.get("current") or {}) if isinstance(load_block, dict) else {}

        recovery = _n(b.get("recovery_score"))
        sleep_score = _n(b.get("sleep_score"))
        sleep_min = _n(b.get("sleep_duration_min"))
        hrv = _n(b.get("hrv_rmssd"))
        rhr = _n(b.get("resting_hr"))
        ctl = _n(cur.get("ctl"))
        atl = _n(cur.get("atl"))
        tsb = _n(cur.get("tsb"))
        weekly_tss = _n(load_block.get("weekly_tss"))

        hrv_base = _n(bases.get("hrv_rmssd"))
        rhr_base = _n(bases.get("resting_hr"))

        if all(v is None for v in (recovery, sleep_score, sleep_min, hrv, rhr, ctl, atl, tsb, weekly_tss)):
            return "Your dashboard summary isn't available yet because your biometrics and training load metrics haven't synced."

        parts: list[str] = []
        if recovery is not None:
            parts.append(f"recovery {round(recovery)}/100")
        if sleep_score is not None:
            parts.append(f"sleep {round(sleep_score)}%")
        if sleep_min is not None:
            parts.append(f"{round(sleep_min)} min asleep")
        if hrv is not None and hrv_base is not None:
            parts.append(f"HRV {round(hrv)} vs {round(hrv_base)}")
        elif hrv is not None:
            parts.append(f"HRV {round(hrv)}")
        if rhr is not None and rhr_base is not None:
            parts.append(f"RHR {round(rhr)} vs {round(rhr_base)}")
        elif rhr is not None:
            parts.append(f"RHR {round(rhr)}")
        if tsb is not None:
            parts.append(f"TSB {round(tsb)}")
        if weekly_tss is not None:
            parts.append(f"weekly TSS {round(weekly_tss)}")

        summary = ", ".join(parts) if parts else "today's key metrics"

        # Heuristic guidance that blends recovery + load.
        if (recovery is not None and recovery < 34) or (tsb is not None and tsb < -20):
            return f"You're showing fatigue today ({summary}); keep intensity low and focus on sleep/recovery to rebound."
        if (recovery is not None and recovery >= 67) and (tsb is None or tsb > -10):
            return f"You look ready to train ({summary}); it’s a good day for a quality session if you keep overall volume controlled."
        return f"Your signals are mixed but workable ({summary}); keep training controlled and use how you feel to decide intensity."

    if analysis_type == "training_load":
        cur = ctx.get("current") or {}
        weekly_tss = _n(ctx.get("weekly_tss"))
        ctl = _n(cur.get("ctl"))
        atl = _n(cur.get("atl"))
        tsb = _n(cur.get("tsb"))

        if weekly_tss is None and ctl is None and atl is None and tsb is None:
            return "Training-load insight isn't available yet because your TSS/PMC history hasn't synced."

        bits: list[str] = []
        if weekly_tss is not None:
            bits.append(f"weekly TSS {round(weekly_tss)}")
        if ctl is not None and atl is not None and tsb is not None:
            bits.append(f"CTL {round(ctl)}, ATL {round(atl)}, TSB {round(tsb)}")
        summary = ", ".join(bits) if bits else "your recent load metrics"

        if tsb is not None and tsb < -20:
            return f"Your load shows high fatigue ({summary}); keep intensity low and prioritize recovery so ATL can come down safely."
        if tsb is not None and tsb > 10:
            return f"You look fresh ({summary}); consider a quality session if sleep and recovery feel solid."
        return f"Your load looks stable ({summary}); stay consistent and adjust volume if soreness or sleep quality trends down."

    biom = ctx.get("biometrics") or {}
    baselines = ctx.get("baselines_30d") or {}

    hrv = _n(biom.get("hrv_rmssd"))
    rhr = _n(biom.get("resting_hr"))
    sleep_score = _n(biom.get("sleep_score"))
    recovery_score = _n(biom.get("recovery_score"))
    strain_score = _n(biom.get("strain_score"))

    hrv_base = _n(baselines.get("hrv_rmssd"))
    rhr_base = _n(baselines.get("resting_hr"))
    sleep_base = _n(baselines.get("sleep_score"))

    if analysis_type == "recovery":
        if recovery_score is None and hrv is None and rhr is None:
            return "Recovery insight isn't available yet because today's recovery/HRV/RHR data is missing."
        parts: list[str] = []
        if recovery_score is not None:
            parts.append(f"recovery {round(recovery_score)}")
        if hrv is not None and hrv_base is not None:
            parts.append(f"HRV {round(hrv)} vs {round(hrv_base)}")
        elif hrv is not None:
            parts.append(f"HRV {round(hrv)}")
        if rhr is not None and rhr_base is not None:
            parts.append(f"RHR {round(rhr)} vs {round(rhr_base)}")
        elif rhr is not None:
            parts.append(f"RHR {round(rhr)}")
        s = ", ".join(parts) if parts else "today's recovery signals"
        if recovery_score is not None and recovery_score < 34:
            return f"Your recovery looks suppressed ({s}); choose easy aerobic work or rest and focus on sleep quality tonight."
        if recovery_score is not None and recovery_score >= 67:
            return f"Your recovery looks strong ({s}); you're likely ready for a higher-quality session if training load is reasonable."
        return f"Your recovery is moderate ({s}); keep training controlled and scale intensity based on how you feel."

    if analysis_type == "sleep":
        if sleep_score is None and biom.get("sleep_duration_min") is None:
            return "Sleep insight isn't available yet because today's sleep score/duration data is missing."
        parts: list[str] = []
        if sleep_score is not None and sleep_base is not None:
            parts.append(f"sleep score {round(sleep_score)} vs {round(sleep_base)}")
        elif sleep_score is not None:
            parts.append(f"sleep score {round(sleep_score)}")
        dur = _n(biom.get("sleep_duration_min"))
        if dur is not None:
            parts.append(f"{round(dur)} min asleep")
        s = ", ".join(parts) if parts else "today's sleep signals"
        if sleep_score is not None and sleep_score < 34:
            return f"Your sleep quality looks poor ({s}); keep intensity low today and target an earlier bedtime."
        if sleep_score is not None and sleep_score >= 67:
            return f"Your sleep looks solid ({s}); maintain your routine and use the extra recovery capacity for productive training."
        return f"Your sleep is moderate ({s}); watch for cumulative fatigue and prioritize consistency for the next 2–3 nights."

    if analysis_type == "strain":
        pmc = ctx.get("pmc") or {}
        ctl = _n(pmc.get("ctl"))
        atl = _n(pmc.get("atl"))
        tsb = _n(pmc.get("tsb"))
        if strain_score is None and ctl is None and atl is None:
            return "Strain insight isn't available yet because today's strain/load data is missing."
        parts: list[str] = []
        if strain_score is not None:
            parts.append(f"strain {round(strain_score)}")
        if ctl is not None and atl is not None and tsb is not None:
            parts.append(f"CTL {round(ctl)}, ATL {round(atl)}, TSB {round(tsb)}")
        s = ", ".join(parts) if parts else "today's load metrics"
        if tsb is not None and tsb < -20:
            return f"Today's strain sits on top of high fatigue ({s}); prioritize low-intensity work and recovery behaviors."
        if strain_score is not None and strain_score >= 67:
            return f"High strain day ({s}); keep tomorrow easier unless recovery markers rebound."
        return f"Your strain is manageable ({s}); keep a steady aerobic focus and avoid stacking too many hard days."

    return "Insight isn't available yet because the required data hasn't synced."


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
        fb = _fallback_content(analysis_type, context)
        upsert_analysis(
            db=db,
            athlete_id=athlete_id,
            analysis_type=analysis_type,
            scope_key=scope_key,
            fingerprint=fp,
            content=fb,
            model="fallback",
        )
        return {
            "content": fb,
            "fingerprint": fp,
            "cached": False,
            "note": "tier_not_eligible",
            "model": "fallback",
        }

    try:
        text, used_model = generate_gemini_analysis(_prompt(analysis_type, context), model_name=model_name)
    except Exception:
        fb = _fallback_content(analysis_type, context)
        upsert_analysis(
            db=db,
            athlete_id=athlete_id,
            analysis_type=analysis_type,
            scope_key=scope_key,
            fingerprint=fp,
            content=fb,
            model="gemini:error_fallback",
        )
        return {
            "content": fb,
            "fingerprint": fp,
            "cached": False,
            "note": "model_error_fallback",
            "model": "gemini:error_fallback",
        }

    final_text = (text or "").strip()
    if not final_text:
        fb = _fallback_content(analysis_type, context)
        upsert_analysis(
            db=db,
            athlete_id=athlete_id,
            analysis_type=analysis_type,
            scope_key=scope_key,
            fingerprint=fp,
            content=fb,
            model=f"{used_model or 'gemini'}:empty_fallback",
        )
        return {
            "content": fb,
            "fingerprint": fp,
            "cached": False,
            "model": used_model,
            "note": "model_empty_fallback",
        }

    upsert_analysis(
        db=db,
        athlete_id=athlete_id,
        analysis_type=analysis_type,
        scope_key=scope_key,
        fingerprint=fp,
        content=final_text,
        model=used_model,
    )
    return {"content": final_text, "fingerprint": fp, "cached": False, "model": used_model}


@router.get("/recovery")
async def recovery_analysis(
    day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_model),
    db: Client = Depends(get_user_db),
):
    d = _parse_day(day)
    ctx = _load_biometrics_context(db, athlete_id, d)
    return {"status": "success", "analysis": _get_or_compute(db, athlete_id, tier, "recovery", d.isoformat(), ctx, model_name=model_name)}


@router.get("/sleep")
async def sleep_analysis(
    day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_model),
    db: Client = Depends(get_user_db),
):
    d = _parse_day(day)
    ctx = _load_biometrics_context(db, athlete_id, d)
    return {"status": "success", "analysis": _get_or_compute(db, athlete_id, tier, "sleep", d.isoformat(), ctx, model_name=model_name)}


@router.get("/strain")
async def strain_analysis(
    day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_model),
    db: Client = Depends(get_user_db),
):
    d = _parse_day(day)
    ctx = _load_strain_context(db, athlete_id, d)
    return {"status": "success", "analysis": _get_or_compute(db, athlete_id, tier, "strain", d.isoformat(), ctx, model_name=model_name)}


@router.get("/training-load")
async def training_load_analysis(
    end_day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_model),
    db: Client = Depends(get_user_db),
):
    d = _parse_day(end_day)
    ctx = _load_training_load_context(db, athlete_id, d)
    return {"status": "success", "analysis": _get_or_compute(db, athlete_id, tier, "training_load", d.isoformat(), ctx, model_name=model_name)}


@router.get("/dashboard-summary")
async def dashboard_summary_analysis(
    day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_model),
    db: Client = Depends(get_user_db),
):
    d = _parse_day(day)
    ctx = _load_dashboard_context(db, athlete_id, d)
    return {
        "status": "success",
        "analysis": _get_or_compute(db, athlete_id, tier, "dashboard_summary", d.isoformat(), ctx, model_name=model_name),
    }

