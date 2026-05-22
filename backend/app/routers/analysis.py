from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.dependencies import (
    get_current_athlete,
    get_current_gemini_analysis_model,
    get_current_user_tier,
    get_user_db,
)
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
            "sleep_bedtime,sleep_wakeup,spo2_pct,skin_temp,recovery_score,strain_score,sleep_need_min,sleep_debt_min"
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
        .select("date,hrv_rmssd,resting_hr,sleep_score,spo2_pct,skin_temp")
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
            "skin_temp": _baseline_30d(base_rows, "skin_temp"),
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


def _load_zones_context(db: Client, athlete_id: str, window_start: str, window_end: str, sport: str) -> Dict[str, Any]:
    def _parse_dt(val: Any) -> Optional[datetime]:
        if not val:
            return None
        try:
            s = str(val)
            # Supabase often returns `...Z` timestamps.
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)
        except Exception:
            return None

    sport_norm = (sport or "all").strip().lower()
    sport_aliases: dict[str, set[str]] = {
        "run": {"run", "running"},
        "bike": {"bike", "cycling", "ride"},
        "strength": {"strength", "strength_training", "gym"},
    }
    allowed_sports = sport_aliases.get(sport_norm, {sport_norm}) if sport_norm != "all" else None

    # Treat window as inclusive day bounds.
    start_ts = f"{str(window_start)[:10]}T00:00:00"
    end_ts = f"{str(window_end)[:10]}T23:59:59.999999"

    res = (
        db.table("workouts")
        .select(
            "started_at,ended_at,sport,hr_zone_1_pct,hr_zone_2_pct,hr_zone_3_pct,hr_zone_4_pct,hr_zone_5_pct"
        )
        .eq("athlete_id", athlete_id)
        .gte("started_at", start_ts)
        .lte("started_at", end_ts)
        .order("started_at")
        .execute()
    )
    rows = (res.data if res else None) or []

    if allowed_sports is not None:
        filtered: list[dict] = []
        for r in rows:
            s = (r.get("sport") or "").strip().lower()
            if s and s in allowed_sports:
                filtered.append(r)
        rows = filtered

    total_workouts = len(rows)
    workouts_with_zone_data = 0

    zone_weighted_sum = {"z1": 0.0, "z2": 0.0, "z3": 0.0, "z4": 0.0, "z5": 0.0}
    zone_weight_total = 0.0
    total_duration_min = 0.0

    for r in rows:
        started = _parse_dt(r.get("started_at"))
        ended = _parse_dt(r.get("ended_at"))
        dur_min = 0.0
        if started and ended:
            ms = (ended - started).total_seconds() * 1000.0
            if ms > 0:
                dur_min = ms / 60000.0
        total_duration_min += dur_min

        z1 = _n(r.get("hr_zone_1_pct"))
        if z1 is None:
            continue
        workouts_with_zone_data += 1

        z2 = _n(r.get("hr_zone_2_pct")) or 0.0
        z3 = _n(r.get("hr_zone_3_pct")) or 0.0
        z4 = _n(r.get("hr_zone_4_pct")) or 0.0
        z5 = _n(r.get("hr_zone_5_pct")) or 0.0

        # Weighted across workouts by workout duration (fallback weight=1 if duration missing).
        w = dur_min if dur_min > 0 else 1.0
        zone_weight_total += w
        zone_weighted_sum["z1"] += w * float(z1)
        zone_weighted_sum["z2"] += w * float(z2)
        zone_weighted_sum["z3"] += w * float(z3)
        zone_weighted_sum["z4"] += w * float(z4)
        zone_weighted_sum["z5"] += w * float(z5)

    if zone_weight_total <= 0:
        zone_distribution: dict[str, Optional[float]] = {"z1": None, "z2": None, "z3": None, "z4": None, "z5": None}
    else:
        zone_distribution = {
            k: round(v / zone_weight_total, 1)
            for k, v in zone_weighted_sum.items()
        }

    return {
        "window_start": str(window_start)[:10],
        "window_end": str(window_end)[:10],
        "sport": sport_norm,
        "total_workouts": total_workouts,
        "workouts_with_zone_data": workouts_with_zone_data,
        "zone_distribution": zone_distribution,
        "total_duration_min": round(float(total_duration_min), 1),
    }


def _prompt(analysis_type: str, context: Dict[str, Any]) -> str:
    # Tight output rules: 1–2 sentences, no lists, cite at least one metric from context.
    # We embed JSON so the model can quote exact numbers.
    if analysis_type == "workout":
        return (
            "You are ASTRAPE, a clinical performance analyst.\n"
            "Task: Write a concise 1–2 sentence analysis for this specific workout that includes a takeaway and a next-step.\n"
            "Rules:\n"
            "- Output 1–2 sentences only. No bullets, no headings, no emojis.\n"
            "- If you mention duration, convert duration_secs to minutes or hours+minutes (e.g., 45 min, 1h 15m). Do not quote raw seconds.\n"
            "- Mention at least one specific metric value from the JSON (TSS, strain_score, avg_hr/max_hr, avg_power/max_power, duration_secs, distance_meters, elevation_gain_meters).\n"
            "- Interpret the effort (easy/moderate/hard) using the metrics, not generic praise.\n"
            "- Include one actionable next step (e.g., keep it easy tomorrow, add carbs/hydration, include strides, schedule a recovery day) that matches the inferred effort.\n"
            "- If key workout metrics are missing (TSS or strain_score and either HR or duration), say what is missing in one sentence.\n\n"
            f"AnalysisType: {analysis_type}\n"
            f"ContextJSON: {context}\n"
        )

    if analysis_type == "time_in_zones":
        return (
            "You are ASTRAPE, a clinical performance analyst.\n"
            "Task: Write a concise 1–2 sentence analysis of the athlete's time-in-zones distribution for the selected window.\n"
            "Rules:\n"
            "- Output 1–2 sentences only. No bullets, no headings, no emojis.\n"
            "- Cite at least one zone percentage from the JSON (e.g., z2 48%).\n"
            "- Comment on aerobic base vs intensity ratio (e.g., polarized, pyramidal, threshold-heavy).\n"
            "- If zone data is missing, say what is missing in one sentence.\n\n"
            f"AnalysisType: {analysis_type}\n"
            f"ContextJSON: {context}\n"
        )

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

    if analysis_type == "time_in_zones":
        dist = (ctx.get("zone_distribution") or {}) if isinstance(ctx, dict) else {}
        z1 = _n(dist.get("z1"))
        z2 = _n(dist.get("z2"))
        z3 = _n(dist.get("z3"))
        z4 = _n(dist.get("z4"))
        z5 = _n(dist.get("z5"))

        with_data = ctx.get("workouts_with_zone_data")
        total = ctx.get("total_workouts")
        if z1 is None or z2 is None or z3 is None or z4 is None or z5 is None:
            return (
                "Zone insight is limited because your workouts are missing heart-rate zone distribution data "
                f"({with_data or 0} of {total or 0} sessions have zone data)."
            )

        low = float(z1) + float(z2)
        high = float(z4) + float(z5)
        if low > 75:
            return f"Your training is predominantly aerobic (Z1+Z2 {round(low)}%), which supports base development with limited high-intensity exposure."
        if high > 30:
            return f"Your week is carrying a high intensity load (Z4+Z5 {round(high)}%), so manage recovery and avoid stacking too many hard days."
        return f"Your zone balance is fairly mixed (Z2 {round(z2)}%, Z4 {round(z4)}%), suggesting a moderate distribution of aerobic and harder work."

    if analysis_type == "workout":
        def _i(v: Any) -> Optional[int]:
            try:
                if v is None:
                    return None
                return int(v)
            except Exception:
                return None

        sport = ctx.get("sport")
        title = ctx.get("title")
        duration_secs = _i(ctx.get("duration_secs"))
        tss = _n(ctx.get("tss"))
        strain = _n(ctx.get("strain_score"))
        avg_hr = _n(ctx.get("avg_hr"))
        max_hr = _n(ctx.get("max_hr"))
        avg_power = _n(ctx.get("avg_power"))
        max_power = _n(ctx.get("max_power"))
        dist_m = _n(ctx.get("distance_meters"))

        key_present = any(v is not None for v in (duration_secs, tss, strain, avg_hr, avg_power))
        if not key_present:
            return "Workout insight is limited because key metrics (duration, TSS/strain, HR, or power) are missing for this activity."

        label = title or sport or "workout"
        if isinstance(label, str):
            label = label.strip()
        if not label:
            label = "workout"

        def _duration_phrase(secs: Optional[int]) -> Optional[str]:
            if secs is None:
                return None
            s = max(0, int(secs))
            h = s // 3600
            m = (s % 3600) // 60
            if h > 0:
                return f"{h}h {m}m"
            return f"{max(0, m)} min"

        dur_phrase = _duration_phrase(duration_secs)
        tss_i = round(float(tss)) if tss is not None else None
        strain_i = round(float(strain)) if strain is not None else None
        avg_hr_i = round(float(avg_hr)) if avg_hr is not None else None
        max_hr_i = round(float(max_hr)) if max_hr is not None else None

        # Simple deterministic effort heuristic (bounded 0-100 scores).
        effort = None
        if strain_i is not None:
            effort = "easy" if strain_i < 34 else "moderate" if strain_i < 67 else "hard"
        elif tss_i is not None:
            effort = "easy" if tss_i < 40 else "moderate" if tss_i < 80 else "hard"

        metric_bits: list[str] = []
        if dur_phrase:
            metric_bits.append(dur_phrase)
        if strain_i is not None:
            metric_bits.append(f"strain {strain_i}")
        if tss_i is not None:
            metric_bits.append(f"TSS {tss_i}")
        if avg_hr_i is not None and max_hr_i is not None:
            metric_bits.append(f"HR {avg_hr_i}/{max_hr_i} bpm")
        elif avg_hr_i is not None:
            metric_bits.append(f"avg HR {avg_hr_i} bpm")
        if avg_power is not None:
            metric_bits.append(f"avg power {round(float(avg_power))} W")
        if dist_m is not None:
            km = float(dist_m) / 1000.0
            metric_bits.append(f"{round(km, 1)} km" if km >= 1 else f"{round(float(dist_m))} m")

        summary = ", ".join(metric_bits[:3]) if metric_bits else "available workout metrics"

        if effort == "easy":
            next_step = "Keep the next session easy or take a recovery day to consolidate the work."
        elif effort == "hard":
            next_step = "Prioritize carbs, hydration, and sleep, and keep tomorrow low intensity."
        elif effort == "moderate":
            next_step = "You can follow with easy aerobic volume; avoid stacking another hard day back-to-back."
        else:
            next_step = "Use how you feel to guide intensity next; more complete HR/power data will sharpen this insight."

        s1 = f"Your {label} looks like an {effort or 'steady'} session ({summary})."
        s2 = next_step
        return f"{s1} {s2}".strip()

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
    except Exception as e:
        try:
            print(f"[analysis] gemini_error type={analysis_type} scope={scope_key} err={e}")
        except Exception:
            pass
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
    model_name: str = Depends(get_current_gemini_analysis_model),
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
    model_name: str = Depends(get_current_gemini_analysis_model),
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
    model_name: str = Depends(get_current_gemini_analysis_model),
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
    model_name: str = Depends(get_current_gemini_analysis_model),
    db: Client = Depends(get_user_db),
):
    d = _parse_day(end_day)
    ctx = _load_training_load_context(db, athlete_id, d)
    return {"status": "success", "analysis": _get_or_compute(db, athlete_id, tier, "training_load", d.isoformat(), ctx, model_name=model_name)}


def _compute_and_store(
    db: Client,
    athlete_id: str,
    tier: str,
    analysis_type: str,
    scope_key: str,
    context: Dict[str, Any],
    model_name: str,
) -> None:
    """Synchronous worker for background regeneration. Errors are swallowed."""
    try:
        _get_or_compute(db, athlete_id, tier, analysis_type, scope_key, context, model_name=model_name)
    except Exception as e:
        try:
            print(f"[analysis] background_regen_error type={analysis_type} scope={scope_key} err={e}")
        except Exception:
            pass


@router.get("/dashboard-summary")
async def dashboard_summary_analysis(
    day: Optional[str] = Query(None, description="YYYY-MM-DD"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_analysis_model),
    db: Client = Depends(get_user_db),
):
    """
    Dashboard summary is on the critical render path, so we serve cached content
    immediately (even if the context fingerprint has drifted) and queue a
    background regeneration. Worst case the user sees yesterday's wording for
    one extra page load.
    """
    d = _parse_day(day)
    scope_key = d.isoformat()
    ctx = _load_dashboard_context(db, athlete_id, d)
    fp = fingerprint_context(ctx)

    cached = get_cached_analysis(db, athlete_id, "dashboard_summary", scope_key)
    if cached and cached.get("content"):
        stale = cached.get("fingerprint") != fp
        if stale and tier in ("trial", "premium"):
            asyncio.ensure_future(asyncio.to_thread(
                _compute_and_store, db, athlete_id, tier, "dashboard_summary", scope_key, ctx, model_name
            ))
        return {
            "status": "success",
            "analysis": {
                "content": cached["content"],
                "fingerprint": cached.get("fingerprint"),
                "cached": True,
                "stale": stale,
            },
        }

    # No cached content yet. Return a fast fallback now and let the LLM warm the
    # cache for the next page load — never block the dashboard for ~2-5s on a
    # first-time Gemini call.
    if tier in ("trial", "premium"):
        asyncio.ensure_future(asyncio.to_thread(
            _compute_and_store, db, athlete_id, tier, "dashboard_summary", scope_key, ctx, model_name
        ))

    fb = _fallback_content("dashboard_summary", ctx)
    return {
        "status": "success",
        "analysis": {
            "content": fb,
            "fingerprint": fp,
            "cached": False,
            "fallback": True,
        },
    }


@router.get("/workout/{workout_id}")
async def workout_analysis(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_analysis_model),
    db: Client = Depends(get_user_db),
):
    res = (
        db.table("workouts")
        .select("*")
        .eq("id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    row = res.data if res else None
    if not row:
        raise HTTPException(status_code=404, detail="Workout not found")

    # Build compact context: include only non-null fields.
    ctx: Dict[str, Any] = {"workout_id": workout_id}

    def _put(key: str, val: Any) -> None:
        if val is None:
            return
        if isinstance(val, str) and not val.strip():
            return
        ctx[key] = val

    _put("sport", row.get("sport") or row.get("workout_type"))
    _put("title", row.get("title"))
    _put("started_at", row.get("started_at") or row.get("start_time"))
    _put("duration_secs", row.get("duration_secs") or row.get("duration_seconds"))
    _put("tss", row.get("tss"))
    _put("strain_score", row.get("strain_score"))
    _put("avg_hr", row.get("avg_hr") or row.get("average_hr"))
    _put("max_hr", row.get("max_hr"))
    _put("avg_power", row.get("avg_power") or row.get("average_power"))
    _put("max_power", row.get("max_power"))
    _put("distance_meters", row.get("distance_meters") or row.get("distance_m") or row.get("distance"))
    _put("elevation_gain_meters", row.get("elevation_gain_meters") or row.get("elevation_gain"))
    _put("notes", row.get("notes"))

    return {
        "status": "success",
        "analysis": _get_or_compute(db, athlete_id, tier, "workout", workout_id, ctx, model_name=model_name),
    }


@router.get("/time-in-zones")
async def time_in_zones_analysis(
    window_start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    window_end: Optional[str] = Query(None, description="YYYY-MM-DD"),
    sport: str = Query("all"),
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_analysis_model),
    db: Client = Depends(get_user_db),
):
    end_d = _parse_day(window_end)
    start_d = _parse_day(window_start) if window_start else (end_d - timedelta(days=7))
    scope_key = f"{start_d.isoformat()}:{end_d.isoformat()}:{sport}"
    ctx = _load_zones_context(db, athlete_id, start_d.isoformat(), end_d.isoformat(), sport)
    return {
        "status": "success",
        "analysis": _get_or_compute(db, athlete_id, tier, "time_in_zones", scope_key, ctx, model_name=model_name),
    }

